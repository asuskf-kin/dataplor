import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def save_dropped_records(
    prev_df: pl.DataFrame,
    current_df: pl.DataFrame,
    data_dir: Path,
    filename: str,
    save_drops: bool = True,
    id_col: str | None = None,
    dropped_df: pl.DataFrame | None = None,
) -> None:
    """
    Compares two DataFrames and saves the rows that were removed into data/dropped.

    Parameters
    ----------
    prev_df : pl.DataFrame
        DataFrame before applying the filter.
    current_df : pl.DataFrame
        DataFrame after applying the filter.
    data_dir : Path
        Base data directory (DATA_DIR).
    filename : str
        Name of the CSV file (should match the intermediate step name).
    save_drops : bool
        Flag to enable or disable saving the dropped records.
    id_col : str, optional
        Unique identifier column (e.g., 'place_id'). If not provided, it compares the entire row.
    dropped_df : pl.DataFrame, optional
        Dropped rows already computed by the module, typically carrying a 'drop_reason'
        column. When provided it is saved as-is and the anti join is skipped.
    """
    if not save_drops:
        return

    # If the module did not hand us the drops, fall back to comparing heights
    if dropped_df is None and prev_df.height <= current_df.height:
        return

    dropped_dir = data_dir / "dropped"
    dropped_dir.mkdir(parents=True, exist_ok=True)

    if dropped_df is not None:
        if dropped_df.height > 0:
            out_path = dropped_dir / filename
            dropped_df.write_csv(out_path, include_bom=True)
            logger.info(
                f"💾 Saved {dropped_df.height} dropped records (with drop_reason) to {out_path}"
            )
        return

    try:
        if id_col and id_col in prev_df.columns and id_col in current_df.columns:
            # If a unique ID exists, anti join is much faster and safer
            join_cols = [id_col]
        else:
            # If no ID exists, we find common columns to avoid errors
            # in case the module added new columns (e.g., name_normalized)
            join_cols = [col for col in prev_df.columns if col in current_df.columns]

        # The "anti join" extracts everything from prev_df that DOES NOT exist in current_df
        dropped_df = prev_df.join(
            current_df.select(join_cols), on=join_cols, how="anti"
        )

        if dropped_df.height > 0:
            out_path = dropped_dir / filename
            dropped_df.write_csv(out_path, include_bom=True)
            logger.info(f"💾 Saved {dropped_df.height} dropped records to {out_path}")

    except (OSError, pl.exceptions.PolarsError) as e:
        # The drop CSV is an audit aid: a write or join failure must not stop the run
        logger.error(f"⚠️ Could not save dropped records for {filename}: {e}")
