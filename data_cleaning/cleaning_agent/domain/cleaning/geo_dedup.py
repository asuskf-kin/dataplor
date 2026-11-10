from collections import defaultdict

import numpy as np
import polars as pl
from sklearn.neighbors import BallTree
from unidecode import unidecode

from cleaning_agent.domain.cleaning.drop_audit import (
    join_partners,
    report_drop_lines,
    strip_audit_cols,
)


def balltree_spatial_deduplication(
    df: pl.DataFrame,
    radius_meters: int = 50,
    items_to_track: list[str] | None = None,
) -> tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]:
    """Finds exact duplicates (by normalized name) within a defined spatial radius using a BallTree.

    Keeps a single record per duplicate group and removes the rest. Updates tracked items list upon auditing.

    Parameters
    ----------
    df : pl.DataFrame
        Input DataFrame containing 'name', 'latitude', 'longitude', and 'dataplor_id' columns.
    radius_meters : int, default 50
        Spatial search radius in meters to evaluate proximity between potential duplicates.
    items_to_track : list[str], optional
        List of specific strings to trace for auditing purposes.

    Returns
    -------
    tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]
        A tuple containing:
        - The deduplicated DataFrame.
        - The updated `items_to_track` list (unmodified if not auditing).
        - An audit report string if `items_to_track` was provided and items were found,
          otherwise None.
        - The dropped records, annotated with 'drop_reason', 'drop_match' (the
          normalized name they shared), 'drop_group_size', 'drop_partners' (the ids of
          the group) and 'drop_detail' (the id kept instead).

    Raises
    ------
    ValueError
        If required columns ('name', 'latitude', 'longitude', 'dataplor_id') are missing.
    """
    required_cols = {"name", "latitude", "longitude", "dataplor_id"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    is_auditing = items_to_track is not None and len(items_to_track) > 0

    def normalize_name(name):
        if name is None:
            return ""
        return " ".join(unidecode(str(name)).lower().split())

    df_prep = df.with_columns(
        pl.col("name")
        .map_elements(normalize_name, return_dtype=pl.String)
        .alias("name_norm")
    )

    # Separate records with valid coordinates from invalid ones
    valid_mask = pl.col("latitude").is_not_null() & pl.col("longitude").is_not_null()
    df_valid = df_prep.filter(valid_mask)

    if df_valid.height == 0:
        cleaned_df = df_prep.drop("name_norm", strict=False)
        return cleaned_df, items_to_track, None, cleaned_df.clear()

    # Extract arrays to native memory for fast iteration
    coords = np.radians(df_valid.select(["latitude", "longitude"]).to_numpy())
    names = df_valid.get_column("name_norm").to_list()
    ids = df_valid.get_column("dataplor_id").to_list()

    tree = BallTree(coords, metric="haversine")
    earth_radius_m = 6371000.0  # Earth's radius in meters
    indices_list = tree.query_radius(coords, r=radius_meters / earth_radius_m)

    # Group duplicates by spatial vicinity and name
    groups = defaultdict(set)
    for i, indices in enumerate(indices_list):
        name_i = names[i]
        id_i = ids[i]
        for j in indices:
            if i != j and name_i == names[j]:
                groups[name_i].add(id_i)
                groups[name_i].add(ids[j])

    # Select duplicate IDs to drop (keeping the first encountered ID)
    # and record, per dropped id, the group it collided with
    reason = f"Geo_Spatial_Duplicate_(<{radius_meters}m)"
    ids_to_remove = set()
    audit_rows = []
    for name, ids_set in groups.items():
        ids_list = list(ids_set)
        if len(ids_list) > 1:
            kept_id = ids_list[0]
            partners = join_partners(ids_list)
            ids_to_remove.update(ids_list[1:])
            for dropped_id in ids_list[1:]:
                audit_rows.append(
                    {
                        "dataplor_id": dropped_id,
                        "drop_reason": reason,
                        "drop_match": name,
                        "drop_group_size": len(ids_list),
                        "drop_partners": partners,
                        "drop_detail": f"kept: {kept_id}",
                    }
                )

    # Flag dropped rows and attach the group they belonged to
    df_clean = df_prep.with_columns(
        pl.when(pl.col("dataplor_id").is_in(list(ids_to_remove)))
        .then(pl.lit(reason))
        .otherwise(pl.lit(None))
        .alias("drop_reason")
    )

    df_survivors = strip_audit_cols(
        df_clean.filter(pl.col("drop_reason").is_null()), extra=["name_norm"]
    )
    df_dropped = df_clean.filter(pl.col("drop_reason").is_not_null()).drop("name_norm")

    if audit_rows:
        audit_df = pl.DataFrame(audit_rows).with_columns(
            pl.col("dataplor_id").cast(df_dropped.schema["dataplor_id"]),
            pl.col("drop_group_size").cast(pl.UInt32),
        )
        df_dropped = df_dropped.drop("drop_reason").join(
            audit_df, on="dataplor_id", how="left"
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
            # Mark item as dropped to remove it from items_to_track
            dropped_items_set.add(text)
            report_lines.extend(report_drop_lines(dropped))

    # Filter out dropped elements from the original items_to_track list
    updated_items_to_track = [
        item for item in items_to_track if item not in dropped_items_set
    ]

    if len(report_lines) == 0:
        return df_survivors, updated_items_to_track, None, df_dropped

    final_report_text = (
        "=" * 45
        + "\n🎯 AUDIT: MODULE 3 (Spatial Deduplication)\n"
        + "=" * 45
        + "".join(report_lines)
        + "\n"
    )

    return df_survivors, updated_items_to_track, final_report_text, df_dropped
