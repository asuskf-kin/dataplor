import logging
import math

import polars as pl

from cleaning_agent.domain.cleaning.drop_audit import (
    partners_expr,
    pick_id_col,
    report_drop_lines,
)

logger = logging.getLogger(__name__)


def filter_crowded_same_property(
    df: pl.DataFrame,
    threshold: int = 4,
    radius_m: float = 100.0,
    items_to_track: list | None = None,
):
    """
    Removes points genuinely co-located in the same property (same parent_location)
    when there are `threshold` or more grouped together[cite: 1].

    Parameters
    ----------
    df : pl.DataFrame
        Input dataframe.
    threshold : int
        Minimum number of points within the radius to be considered crowded[cite: 1].
    radius_m : float
        Radius in meters around the centroid to define the dense sub-cluster[cite: 1].
    items_to_track : list, optional
        List of strings to track for the audit report.

    Returns
    -------
    tuple
        The survivors, the updated tracked items, the audit report, and the dropped
        records annotated with 'drop_reason', 'drop_match' (the shared
        parent_location), 'drop_group_size' (dense points in that property),
        'drop_partners' (ids sharing the property) and 'drop_detail' (distance to the
        property centroid).
    """
    is_auditing = items_to_track is not None and len(items_to_track) > 0
    id_col = pick_id_col(df)

    # Ensure required columns exist
    required_cols = ["parent_location", "latitude", "longitude"]
    for col in required_cols:
        if col not in df.columns:
            logger.warning(f"Missing column '{col}'. Skipping crowded property filter.")
            return df, items_to_track, None, df.clear()

    # Keep track of original rows to safely drop them later
    df_working = df.with_row_index("__row_id")

    # 1. Filter valid rows for calculation (must have parent_location and coordinates)
    valid_mask = (
        pl.col("parent_location").is_not_null()
        & pl.col("latitude").is_not_null()
        & pl.col("longitude").is_not_null()
    )

    # 2. Find parent_locations that have at least `threshold` valid points
    counts = (
        df_working.filter(valid_mask)
        .group_by("parent_location")
        .agg(pl.len().alias("prop_count"))
    )

    # 3. Join counts and filter down to the candidate groups
    candidates = df_working.join(counts, on="parent_location", how="left").filter(
        pl.col("prop_count") >= threshold
    )

    # If no groups meet the threshold, return the original DataFrame early
    if candidates.height == 0:
        return df, items_to_track, None, df.clear()

    # 4. Calculate the centroid (mean lat/lon) for each candidate parent_location[cite: 1]
    candidates = candidates.with_columns(
        [
            pl.col("latitude").mean().over("parent_location").alias("lat_mean"),
            pl.col("longitude").mean().over("parent_location").alias("lon_mean"),
        ]
    )

    # 5. Native Haversine Distance Calculation (Vectorized in Polars)[cite: 1]
    RAD = math.pi / 180.0
    lat1 = pl.col("latitude") * RAD
    lon1 = pl.col("longitude") * RAD
    lat2 = pl.col("lat_mean") * RAD
    lon2 = pl.col("lon_mean") * RAD

    dlat = lat1 - lat2
    dlon = lon1 - lon2

    a = (dlat / 2.0).sin().pow(2) + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().pow(2)
    # Clip values between 0 and 1 to prevent floating point errors before arcsin[cite: 1]
    a = pl.when(a < 0.0).then(0.0).when(a > 1.0).then(1.0).otherwise(a)

    dist_expr = 2.0 * 6371000.0 * a.sqrt().arcsin()

    candidates = candidates.with_columns(dist_expr.alias("dist_from_centroid"))

    # 6. Flag points that are within the dense radius[cite: 1]
    candidates = candidates.with_columns(
        (pl.col("dist_from_centroid") <= radius_m).alias("is_dense")
    )

    # 7. Count how many dense points exist in that specific property[cite: 1]
    dense_counts = candidates.group_by("parent_location").agg(
        pl.col("is_dense").sum().alias("dense_count")
    )

    candidates = candidates.join(dense_counts, on="parent_location", how="left")

    # 8. Identify the specific row IDs to drop (dense points in a property with >= threshold dense points)[cite: 1]
    dropped_candidates = candidates.filter(
        pl.col("is_dense") & (pl.col("dense_count") >= threshold)
    )
    to_drop_ids = dropped_candidates.get_column("__row_id")

    # 9. Apply the drop to the original DataFrame
    df_clean = df_working.filter(~pl.col("__row_id").is_in(to_drop_ids)).drop(
        "__row_id"
    )
    df_dropped = df_working.filter(pl.col("__row_id").is_in(to_drop_ids))

    # 10. Explain each drop: the property they share, how crowded it was and how far
    # each point sat from the centroid
    audit = dropped_candidates.select(
        "__row_id",
        pl.lit(f"1_Crowded_Property_(>={threshold}_within_{radius_m:g}m)").alias(
            "drop_reason"
        ),
        pl.col("parent_location").cast(pl.String).alias("drop_match"),
        pl.col("dense_count").cast(pl.UInt32).alias("drop_group_size"),
        pl.concat_str(
            pl.col("dist_from_centroid").round(1).cast(pl.String),
            pl.lit("m from the property centroid"),
        ).alias("drop_detail"),
    )
    df_dropped = df_dropped.join(audit, on="__row_id", how="left").drop("__row_id")

    if id_col:
        df_dropped = df_dropped.with_columns(
            partners_expr(id_col, "drop_match").alias("drop_partners")
        )

    # --- AUDIT REPORTING LOGIC ---
    if not is_auditing or df_dropped.height == 0:
        return df_clean, items_to_track, None, df_dropped

    report_lines = []
    dropped_items_set = set()

    for text in items_to_track:
        text_lower = text.lower()

        survived = df_clean.filter(
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
        return df_clean, updated_items_to_track, None, df_dropped

    final_report_text = (
        "=" * 45 + "\n"
        "🎯 AUDIT: MODULE 6 (Crowded Same Property)\n"
        + "=" * 45
        + "".join(report_lines)
        + "\n"
    )

    return df_clean, updated_items_to_track, final_report_text, df_dropped
