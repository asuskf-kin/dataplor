"""Exact-duplicate removal with an explanation per dropped row."""

import logging
from typing import Literal

import polars as pl

from cleaning_agent.domain.cleaning.drop_audit import (
    partners_expr,
    pick_id_col,
    strip_audit_cols,
)

logger = logging.getLogger(__name__)


def deduplicate_records(
    df: pl.DataFrame,
    subset: list[str] | None = None,
    keep: Literal["first", "last", "any", "none"] = "first",
) -> pl.DataFrame:
    """
    Removes duplicate rows from a Polars DataFrame and logs the exact
    number of rows before and after, alongside the reduction percentage.

    Args:
        df (pl.DataFrame): The input DataFrame.
        subset (Optional[List[str]]): Columns to consider for identifying duplicates.
                                      If None, evaluates all columns.
        keep (str): Which duplicate to keep ('first', 'last', 'any', or 'none').

    Returns:
        pl.DataFrame: A new deduplicated DataFrame.
    """
    initial_count = df.height

    if initial_count == 0:
        logger.warning("The DataFrame is empty. Skipping deduplication.")
        return df

    # Validate subset columns exist to prevent cryptic ComputeErrors
    if subset is not None:
        missing_cols = [col for col in subset if col not in df.columns]
        if missing_cols:
            raise ValueError(
                f"Columns not found in DataFrame for deduplication: {missing_cols}"
            )

    # maintain_order=True keeps the original row sequence
    df_dedup = df.unique(subset=subset, keep=keep, maintain_order=True)

    final_count = df_dedup.height
    removed_count = initial_count - final_count

    if removed_count > 0:
        reduction_pct = (removed_count / initial_count) * 100
        msg = (
            f"Deduplication: Removed {removed_count} rows. "
            f"Dataset reduced by {reduction_pct:.2f}%. "
            f"Original count: {initial_count} | New count: {final_count} rows."
        )
        logger.info(msg)
    else:
        logger.info(
            f"Deduplication: No duplicates found. Total rows remains {initial_count}."
        )

    return df_dedup


def deduplicate_records_with_audit(
    df: pl.DataFrame,
    subset: list[str] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Same as `deduplicate_records` with keep='first', but also explains every removal.

    Args:
        df (pl.DataFrame): The input DataFrame.
        subset (Optional[List[str]]): Columns identifying a duplicate. None = all columns.

    Returns:
        tuple[pl.DataFrame, pl.DataFrame]: the deduplicated DataFrame and the dropped
        rows, annotated with 'drop_reason', 'drop_match' (the key they collided on),
        'drop_group_size', 'drop_partners' and 'drop_detail' (the id kept instead).
    """
    if df.height == 0:
        logger.warning("The DataFrame is empty. Skipping deduplication.")
        return df, df.clear()

    key_cols = subset if subset is not None else df.columns
    missing_cols = [col for col in key_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Columns not found in DataFrame for deduplication: {missing_cols}"
        )

    id_col = pick_id_col(df)
    reason = f"1_Exact_Duplicate_({'+'.join(key_cols)})"

    df_work = df.with_columns(
        pl.concat_str(
            [pl.col(c).cast(pl.String).fill_null("") for c in key_cols], separator=" | "
        ).alias("_dup_key")
    )

    # Row order decides the winner, matching unique(keep='first', maintain_order=True)
    occurrence = pl.int_range(pl.len()).over("_dup_key")
    is_duplicate = occurrence > 0

    df_work = df_work.with_columns(
        pl.when(is_duplicate)
        .then(pl.lit(reason))
        .otherwise(None)
        .cast(pl.String)
        .alias("drop_reason"),
        pl.when(is_duplicate)
        .then(pl.col("_dup_key"))
        .otherwise(None)
        .alias("drop_match"),
        pl.when(is_duplicate)
        .then(pl.len().over("_dup_key"))
        .otherwise(None)
        .cast(pl.UInt32)
        .alias("drop_group_size"),
    )

    if id_col:
        df_work = df_work.with_columns(
            pl.when(is_duplicate)
            .then(partners_expr(id_col, "_dup_key"))
            .otherwise(None)
            .cast(pl.String)
            .alias("drop_partners"),
            # The first row of the group is the one that survives
            pl.when(is_duplicate)
            .then(
                pl.concat_str(
                    pl.lit("kept: "),
                    pl.col(id_col).cast(pl.String).first().over("_dup_key"),
                )
            )
            .otherwise(None)
            .cast(pl.String)
            .alias("drop_detail"),
        )

    df_dropped = df_work.filter(pl.col("drop_reason").is_not_null()).drop("_dup_key")
    df_dedup = strip_audit_cols(
        df_work.filter(pl.col("drop_reason").is_null()), extra=["_dup_key"]
    )

    log_row_reduction(df, df_dedup, "Deduplication")
    return df_dedup, df_dropped


def log_row_reduction(
    df_before: pl.DataFrame, df_after: pl.DataFrame, step_name: str = "Process"
) -> None:
    """
    Simply compares the height (rows) of two Polars DataFrames
    and logs the exact reduction metrics.
    """
    initial_count = df_before.height
    final_count = df_after.height
    removed_count = initial_count - final_count

    # Evita el error de división por cero por si el df original viene vacío
    reduction_pct = (removed_count / initial_count * 100) if initial_count > 0 else 0

    logger.info(
        f"[{step_name}] Removed {removed_count} rows. "
        f"Dataset reduced by {reduction_pct:.2f}%. "
        f"Original count: {initial_count} | New count: {final_count} rows."
    )
