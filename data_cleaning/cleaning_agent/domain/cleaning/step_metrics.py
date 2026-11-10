"""Rows dropped by a step and the most frequent dropped names."""

import polars as pl


def analyze_step_drop(
    df_before: pl.DataFrame, df_after: pl.DataFrame, step_name: str
) -> dict:
    """
    Compares the DataFrame before and after a module to extract metrics
    and the Top 5 most frequent dropped records dynamically based on available columns.
    """
    count_before = len(df_before)
    count_after = len(df_after)
    dropped_count = count_before - count_after

    top_dropped = []
    if dropped_count > 0:
        # Dynamically detect which name/identifier column exists
        name_col = None
        for col in ["name_normalized", "name", "business_name", "title"]:
            if col in df_before.columns:
                name_col = col
                break

        # Build join keys based on existing common columns
        join_keys = []
        if name_col and name_col in df_after.columns:
            join_keys.append(name_col)
        for c in ["latitude", "longitude", "id", "place_id"]:
            if c in df_before.columns and c in df_after.columns:
                join_keys.append(c)

        if join_keys:
            # Use anti-join to isolate the exact dropped rows
            dropped_df = df_before.join(df_after, on=join_keys, how="anti")
        else:
            # If no clear join keys exist, safely skip the difference report
            dropped_df = pl.DataFrame()

        if len(dropped_df) > 0 and name_col and name_col in dropped_df.columns:
            top_counts = (
                dropped_df.group_by(name_col)
                .agg(pl.len().alias("freq"))
                .sort("freq", descending=True)
                .head(5)
            )
            top_dropped = [(row[0], row[1]) for row in top_counts.iter_rows()]
        elif len(dropped_df) > 0:
            top_dropped = [("Records without a detected name column", len(dropped_df))]

    return {
        "step_name": step_name,
        "dropped_count": dropped_count,
        "remaining_count": count_after,
        "top_dropped": top_dropped,
    }
