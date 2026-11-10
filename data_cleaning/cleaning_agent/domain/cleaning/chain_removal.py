import re

import polars as pl

from cleaning_agent.domain.cleaning.drop_audit import (
    partners_expr,
    pick_id_col,
    report_drop_lines,
    strip_audit_cols,
)


def _source_pattern(matched_text: str, patterns: list[str]) -> str | None:
    """Returns the first CHAIN_REGEX entry that matches `matched_text`, if any."""
    for pattern in patterns:
        if re.search(pattern, matched_text, re.IGNORECASE):
            return pattern
    return None


def _explain_drops(
    df_dropped: pl.DataFrame,
    dup_reason: str,
    id_col: str | None,
    patterns: list[str],
) -> pl.DataFrame:
    """Enriches the dropped rows with the regex that matched and the duplicate partners.

    Parameters
    ----------
    df_dropped : pl.DataFrame
        Rows already tagged with 'drop_reason' / 'drop_match', still holding '_filter_key'.
    dup_reason : str
        Label used for the duplicates rule, needed to target only those rows.
    id_col : str | None
        Identifier column used to list the partners of each duplicate group.

    Returns
    -------
    pl.DataFrame
        The dropped rows with 'drop_pattern' and 'drop_partners' filled in, and the
        internal helper columns removed.
    """
    # 'drop_pattern': which CHAIN_REGEX entry produced the match.
    # Resolved over the distinct matched texts only (a handful of values), never row by row.
    matched_texts = (
        df_dropped.filter(pl.col("drop_reason") == "1_Regex_Chain")
        .get_column("drop_match")
        .unique()
        .drop_nulls()
        .to_list()
    )
    pattern_lookup = {text: _source_pattern(text, patterns) for text in matched_texts}

    df_dropped = df_dropped.with_columns(
        pl.when(pl.col("drop_reason") == "1_Regex_Chain")
        .then(pl.col("drop_match").replace_strict(pattern_lookup, default=None))
        .otherwise(None)
        .cast(pl.String)
        .alias("drop_pattern")
    )

    # 'drop_partners': the records a duplicate got lumped together with.
    # Whole groups are dropped at once, so the group inside df_dropped is complete.
    partner_col = id_col or "name_normalized"
    if "drop_group_size" in df_dropped.columns and partner_col in df_dropped.columns:
        df_dropped = df_dropped.with_columns(
            pl.when(pl.col("drop_reason") == dup_reason)
            .then(partners_expr(partner_col, "_filter_key"))
            .otherwise(None)
            .cast(pl.String)
            .alias("drop_partners")
        )

    return df_dropped.drop(
        [c for c in ["_filter_key", "_matched_text"] if c in df_dropped.columns]
    )


def filter_chains_and_duplicates(
    df: pl.DataFrame,
    filter_duplicates: bool = True,
    max_appearances: int = 4,
    items_to_track: list[str] | None = None,
    chain_regex: list[str] | None = None,
) -> tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]:
    """Filters commercial chains and duplicate entries from a DataFrame, and updates tracked items.

    Parameters
    ----------
    df : pl.DataFrame
        Input DataFrame containing a 'name_normalized' column.
    filter_duplicates : bool, default True
        Whether to filter out entries that exceed `max_appearances`.
    max_appearances : int, default 4
        Maximum allowed occurrences of a normalized name before being flagged as a duplicate.
    items_to_track : list[str], optional
        List of specific strings to trace for auditing purposes.
    chain_regex : list[str], optional
        Chain patterns of the run's country (required: the country is chosen per run).

    Returns
    -------
    tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]
        A tuple containing:
        - The filtered/cleaned DataFrame.
        - The updated `items_to_track` list (unmodified if not auditing).
        - An audit report string if `items_to_track` was provided and items were found,
          otherwise None.
        - The dropped records, annotated with:
            * 'drop_reason'     : which rule removed the row.
            * 'drop_match'      : the text it matched on (chain substring, shared
                                  duplicate key, or chain name from the source).
            * 'drop_pattern'    : the exact CHAIN_REGEX entry that matched.
            * 'drop_group_size' : size of the duplicate group it belonged to.
            * 'drop_partners'   : ids of the records it was grouped with.

    Raises
    ------
    ValueError
        If 'name_normalized' column is missing from the input DataFrame.
    """
    if "name_normalized" not in df.columns:
        raise ValueError(
            "Column 'name_normalized' is missing. Run normalize_names first."
        )

    if not chain_regex:
        raise ValueError(
            "chain_regex is required: pass the CHAIN_REGEX of the run's country"
        )
    patterns = chain_regex
    chain_pattern = "(?i)" + "|".join(f"(?:{p})" for p in patterns)

    df_clean = df.with_columns(
        pl.col("name_normalized")
        .str.replace_all(r"[´`‘’ʼ]", "'")
        .str.to_lowercase()
        .alias("_filter_key")
    )

    is_auditing = items_to_track is not None and len(items_to_track) > 0
    dup_reason = f"2_Too_Many_Duplicates_(>{max_appearances})"
    id_col = pick_id_col(df)

    # ==========================================
    # 🏷️ TAG EVERY ROW WITH ITS DROP REASON
    # (first matching rule wins, so the reason is traceable)
    # ==========================================
    df_clean = df_clean.with_columns(
        pl.lit(None).cast(pl.String).alias("drop_reason"),
        pl.lit(None).cast(pl.String).alias("drop_match"),
        # Substring of the name that actually triggered the chain regex (null = no match)
        pl.col("_filter_key").str.extract(chain_pattern, 0).alias("_matched_text"),
    )

    # 1. Regex Filter (Chains)
    regex_mask = pl.col("_matched_text").is_not_null()
    df_clean = df_clean.with_columns(
        pl.when(regex_mask)
        .then(pl.lit("1_Regex_Chain"))
        .otherwise(pl.col("drop_reason"))
        .alias("drop_reason"),
        pl.when(regex_mask)
        .then(pl.col("_matched_text"))
        .otherwise(pl.col("drop_match"))
        .alias("drop_match"),
    )

    # 2. Duplicates Filter
    if filter_duplicates:
        group_size = pl.len().over("_filter_key")
        dup_mask = (
            pl.col("_filter_key").is_not_null()
            & (group_size > max_appearances)
            & pl.col("drop_reason").is_null()
        )
        df_clean = df_clean.with_columns(
            pl.when(dup_mask)
            .then(pl.lit(dup_reason))
            .otherwise(pl.col("drop_reason"))
            .alias("drop_reason"),
            # The shared key is what they collided on
            pl.when(dup_mask)
            .then(pl.col("_filter_key"))
            .otherwise(pl.col("drop_match"))
            .alias("drop_match"),
            pl.when(dup_mask)
            .then(group_size)
            .otherwise(None)
            .cast(pl.UInt32)
            .alias("drop_group_size"),
        )

    # 3. Source Flag Filter
    if "identified_as_chain" in df_clean.columns:
        flag_mask = (
            pl.col("identified_as_chain").cast(pl.String).fill_null("") == "True"
        ) & pl.col("drop_reason").is_null()
        # If the source names the chain, report it; otherwise just the flag itself
        flag_value = (
            pl.col("chain_name").cast(pl.String)
            if "chain_name" in df_clean.columns
            else pl.lit("identified_as_chain=True")
        )
        df_clean = df_clean.with_columns(
            pl.when(flag_mask)
            .then(pl.lit("3_Flagged_As_Chain_In_Source"))
            .otherwise(pl.col("drop_reason"))
            .alias("drop_reason"),
            pl.when(flag_mask)
            .then(flag_value.fill_null("identified_as_chain=True"))
            .otherwise(pl.col("drop_match"))
            .alias("drop_match"),
        )

    # Separate survivors and dropped records
    df_dropped = df_clean.filter(pl.col("drop_reason").is_not_null())
    df_survivors = strip_audit_cols(
        df_clean.filter(pl.col("drop_reason").is_null()),
        extra=["_filter_key", "_matched_text"],
    )

    df_dropped = _explain_drops(df_dropped, dup_reason, id_col, patterns)

    # Without tracked items there is no report to build, but drops are still explained
    if not is_auditing:
        return df_survivors, items_to_track, None, df_dropped

    # --- BUILD AUDIT REPORT & UPDATE TRACKED ITEMS ---
    report_lines = []
    dropped_items_set = set()

    for text in items_to_track:
        text_lower = text.lower()
        survived = df_survivors.filter(
            pl.col("name_normalized")
            .str.to_lowercase()
            .str.contains(text_lower, literal=True)
        )
        dropped = df_dropped.filter(
            pl.col("name_normalized")
            .str.to_lowercase()
            .str.contains(text_lower, literal=True)
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
        + "\n🎯 AUDIT: MODULE 2 (Chains)\n"
        + "=" * 45
        + "".join(report_lines)
        + "\n"
    )

    return df_survivors, updated_items_to_track, final_report_text, df_dropped
