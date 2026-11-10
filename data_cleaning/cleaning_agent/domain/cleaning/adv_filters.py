import re

import numpy as np
import polars as pl
from sklearn.neighbors import BallTree

from cleaning_agent.domain.cleaning.drop_audit import (
    pick_id_col,
    report_drop_lines,
    strip_audit_cols,
)
from cleaning_agent.domain.cleaning.hours_filter import apply_hours_filter_logic
from cleaning_agent.domain.patterns.global_exclude import GLOBAL_EXCLUDE_KEYWORDS

try:
    from rapidfuzz import fuzz as _rfuzz

    _name_sim = lambda a, b: _rfuzz.token_set_ratio(a, b)
except ImportError:
    from difflib import SequenceMatcher

    _name_sim = lambda a, b: SequenceMatcher(None, a, b).ratio() * 100


def apply_hours_and_fuzzy_filters(
    df: pl.DataFrame,
    apply_hours_filter: bool = True,
    min_hours: int = 20,
    night_start: int = 19,
    fuzzy_thresh: int = 80,
    dist_m: int = 100,
    items_to_track: list[str] | None = None,
) -> tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]:
    """
    Applies hours filters (optional), global mislabeling filter, and fuzzy + spatial deduplication.

    Returns the survivors, the updated tracked items, the audit report and the dropped
    records annotated with 'drop_reason', 'drop_match' (excluded keyword, opening hours
    or the name it was fuzzy-matched against), 'drop_partners' (the record kept instead)
    and 'drop_detail' (similarity score or weekly hours).
    """
    is_auditing = items_to_track is not None and len(items_to_track) > 0
    id_col = pick_id_col(df)

    # Add row index for precise tracking of drop reasons
    df = df.with_row_index("__row_id")

    # 1. Normalization for name filters
    def normalize_name(name):
        if name is None:
            return ""
        name_str = str(name).lower()
        from unidecode import unidecode

        return unidecode(name_str).strip()

    df = df.with_columns(
        pl.col("name")
        .map_elements(normalize_name, return_dtype=pl.String)
        .alias("_name_lower")
    )

    # 2. Global Mislabeling Filter
    pattern_global = "|".join(re.escape(k) for k in GLOBAL_EXCLUDE_KEYWORDS)
    df = df.with_columns(
        pl.col("_name_lower")
        .str.contains(pattern_global)
        .not_()
        .alias("flag_global_keywords"),
        # The keywords are literals, so the extracted text IS the offending keyword
        pl.col("_name_lower").str.extract(pattern_global, 0).alias("_matched_keyword"),
    )

    # Initialize drop_reason / drop_match for records failing global keywords
    failed_keywords = pl.col("flag_global_keywords").not_()
    df = df.with_columns(
        pl.when(failed_keywords)
        .then(pl.lit("1_Global_Keywords"))
        .otherwise(pl.lit(None))
        .alias("drop_reason"),
        pl.when(failed_keywords)
        .then(pl.col("_matched_keyword"))
        .otherwise(pl.lit(None))
        .alias("drop_match"),
    )

    # 3. Hours Filter (Delegado al nuevo módulo)
    if apply_hours_filter:
        df = apply_hours_filter_logic(df, min_hours, night_start)
    else:
        # Si el filtro está desactivado, todos los registros pasan
        df = df.with_columns(pl.lit(True).alias("flag_hours"))

    # 4. Fuzzy + Spatial Filter
    cands_mask_expr = (
        pl.col("flag_global_keywords")
        & pl.col("flag_hours")
        & pl.col("latitude").is_not_null()
        & pl.col("longitude").is_not_null()
    )

    cands_mask = df.select(cands_mask_expr).to_series().to_numpy()
    df_cands = df.filter(cands_mask_expr)

    # Maps each dropped candidate to the one it matched: j -> (i, similarity)
    dup_local = {}
    if df_cands.height > 0:
        coords_rad = np.radians(df_cands.select(["latitude", "longitude"]).to_numpy())
        tree = BallTree(coords_rad, metric="haversine")
        nbrs_list = tree.query_radius(coords_rad, r=dist_m / 6_371_000)

        cands_names = df_cands.get_column("_name_lower").to_list()

        for i, nbrs in enumerate(nbrs_list):
            if i in dup_local:
                continue
            name_i = cands_names[i]
            for j in nbrs:
                if j <= i or j in dup_local:
                    continue
                sim_score = _name_sim(name_i, cands_names[j])
                if sim_score >= fuzzy_thresh:
                    dup_local[j] = (i, sim_score)

    cands_indices = np.where(cands_mask)[0]
    fuzzy_dropped_row_ids = set()
    fuzzy_audit_rows = []
    if dup_local:
        cands_ids = (
            df_cands.get_column(id_col).cast(pl.String).to_list() if id_col else None
        )
        for j, (i, sim_score) in dup_local.items():
            row_id = int(cands_indices[j])
            fuzzy_dropped_row_ids.add(row_id)
            fuzzy_audit_rows.append(
                {
                    "__row_id": row_id,
                    # The name of the record it was considered a duplicate of
                    "_fuzzy_match": cands_names[i],
                    "_fuzzy_partner": cands_ids[i] if cands_ids else None,
                    "_fuzzy_detail": f"similarity={sim_score:.0f}% (kept the other one)",
                }
            )

    flag_fuzzy_list = [
        row_id not in fuzzy_dropped_row_ids
        for row_id in df.get_column("__row_id").to_list()
    ]
    df = df.with_columns(
        pl.Series("flag_fuzzy_dedup", flag_fuzzy_list, dtype=pl.Boolean)
    )

    # Attach the fuzzy match details before deciding the reason
    if fuzzy_audit_rows:
        fuzzy_df = pl.DataFrame(fuzzy_audit_rows).with_columns(
            pl.col("__row_id").cast(df.schema["__row_id"])
        )
        df = df.join(fuzzy_df, on="__row_id", how="left")
    else:
        df = df.with_columns(
            pl.lit(None).cast(pl.String).alias("_fuzzy_match"),
            pl.lit(None).cast(pl.String).alias("_fuzzy_partner"),
            pl.lit(None).cast(pl.String).alias("_fuzzy_detail"),
        )

    # Update drop_reason if dropped at fuzzy dedup
    dropped_by_fuzzy = pl.col("drop_reason").is_null() & (
        pl.col("flag_fuzzy_dedup") == False
    )
    df = df.with_columns(
        pl.when(dropped_by_fuzzy)
        .then(pl.lit("3_Fuzzy_Dedup"))
        .otherwise(pl.col("drop_reason"))
        .alias("drop_reason"),
        pl.when(dropped_by_fuzzy)
        .then(pl.col("_fuzzy_match"))
        .otherwise(pl.col("drop_match"))
        .alias("drop_match"),
        pl.when(dropped_by_fuzzy)
        .then(pl.col("_fuzzy_partner"))
        .otherwise(None)
        .cast(pl.String)
        .alias("drop_partners"),
        pl.when(dropped_by_fuzzy)
        .then(pl.col("_fuzzy_detail"))
        .otherwise(pl.col("drop_detail") if "drop_detail" in df.columns else None)
        .cast(pl.String)
        .alias("drop_detail"),
    )

    # Separate survivors and dropped records
    helper_cols = [
        "__row_id",
        "_name_lower",
        "_matched_keyword",
        "_total_weekly_hours",
        "_is_night_only",
        "_fuzzy_match",
        "_fuzzy_partner",
        "_fuzzy_detail",
        "flag_global_keywords",
        "flag_hours",
        "flag_fuzzy_dedup",
    ]
    df_dropped = df.filter(pl.col("drop_reason").is_not_null()).drop(
        helper_cols, strict=False
    )
    df_survivors = strip_audit_cols(
        df.filter(pl.col("drop_reason").is_null()), extra=helper_cols
    )

    if not is_auditing:
        return df_survivors, items_to_track, None, df_dropped

    # --- BUILD AUDIT REPORT & UPDATE TRACKED ITEMS ---
    report_lines = []
    dropped_items_set = set()

    for text in items_to_track:
        text_lower = text.lower()
        survived = df_survivors.filter(
            pl.col("name").str.to_lowercase().str.contains(text_lower, literal=True)
        )
        dropped = df_dropped.filter(
            pl.col("name").str.to_lowercase().str.contains(text_lower, literal=True)
        )

        if len(survived) == 0 and len(dropped) == 0:
            continue

        report_lines.append(f"\n🔍 Tracked text: '{text}'")

        if len(survived) > 0:
            report_lines.append(
                f"\n    ✅ SURVIVED: Passed this filter successfully ({len(survived)} records)."
            )

        if len(dropped) > 0:
            dropped_items_set.add(text)
            report_lines.extend(report_drop_lines(dropped))

    updated_items_to_track = [
        item for item in items_to_track if item not in dropped_items_set
    ]

    if len(report_lines) == 0:
        return df_survivors, updated_items_to_track, None, df_dropped

    final_report_text = (
        "=" * 45
        + "\n🎯 AUDIT: MODULE 4 (Hours and Fuzzy Filters)\n"
        + "=" * 45
        + "".join(report_lines)
        + "\n"
    )

    return df_survivors, updated_items_to_track, final_report_text, df_dropped
