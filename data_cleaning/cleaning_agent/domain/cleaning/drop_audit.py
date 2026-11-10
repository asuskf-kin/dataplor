"""Shared vocabulary so every pipeline step explains its drops the same way.

Each module tags the rows it removes with the columns listed in DROP_AUDIT_COLS and
returns them as the 4th element of its result tuple. main.py then writes those rows
to data/dropped/<step>.csv, so a discarded record always carries the rule that hit
it, what it matched on and which records it was grouped with.
"""

import polars as pl

# Audit columns attached to dropped records. Modules fill in what applies to them.
DROP_AUDIT_COLS = [
    "drop_reason",  # rule that removed the row
    "drop_match",  # value/text that triggered the rule
    "drop_pattern",  # exact regex or keyword behind the match
    "drop_group_size",  # how many records shared the group
    "drop_partners",  # ids the row was grouped with / compared against
    "drop_detail",  # extra context: kept id, similarity, distance, hours...
]

# Identifier columns, in order of preference, used to report grouping partners
_ID_CANDIDATES = ["dataplor_id", "place_id", "id"]

# Partner ids listed per group; 'drop_group_size' still holds the real total
MAX_PARTNERS_LISTED = 10

PARTNER_SEPARATOR = " | "


def pick_id_col(df: pl.DataFrame) -> str | None:
    """Returns the best identifier column available in `df`, or None."""
    return next((c for c in _ID_CANDIDATES if c in df.columns), None)


def partners_expr(
    id_col: str, group_col: str, limit: int = MAX_PARTNERS_LISTED
) -> pl.Expr:
    """Builds an expression listing up to `limit` ids sharing the same `group_col`."""
    return (
        pl.col(id_col)
        .cast(pl.String)
        .head(limit)
        .str.join(PARTNER_SEPARATOR)
        .over(group_col)
    )


def join_partners(ids: list, limit: int = MAX_PARTNERS_LISTED) -> str:
    """Formats a list of ids as a single 'a | b | c' string, capped at `limit`."""
    return PARTNER_SEPARATOR.join(str(i) for i in ids[:limit])


def strip_audit_cols(df: pl.DataFrame, extra: list[str] | None = None) -> pl.DataFrame:
    """Removes audit and helper columns, keeping survivors identical to the input schema."""
    to_drop = [*DROP_AUDIT_COLS, *(extra or [])]
    return df.drop([c for c in to_drop if c in df.columns])


def report_drop_lines(dropped: pl.DataFrame) -> list[str]:
    """Renders the '❌ DROPPED' block of the audit report for one tracked item.

    Groups the dropped rows by reason and match so the report states not only which
    rule fired but what it matched on and, when relevant, the records involved.
    """
    group_cols = [c for c in ["drop_reason", "drop_match"] if c in dropped.columns]
    if not group_cols:
        return [
            f"\n    ❌ DROPPED: Removed at this step ({dropped.height} records dropped)."
        ]

    detail_cols = [
        c
        for c in ["drop_pattern", "drop_partners", "drop_detail"]
        if c in dropped.columns
    ]
    grouped = dropped.group_by(group_cols).agg(
        pl.len().alias("count"), *[pl.col(c).first() for c in detail_cols]
    )

    labels = {
        "drop_pattern": "regex used",
        "drop_partners": "grouped with",
        "drop_detail": "detail",
    }

    lines = []
    for row in grouped.iter_rows(named=True):
        reason = row["drop_reason"]
        lines.append(
            f"\n    ❌ DROPPED: Removed at this step due to: [{reason}] "
            f"({row['count']} records dropped)."
        )
        if row.get("drop_match") is not None:
            lines.append(f"\n        ↳ matched on: '{row['drop_match']}'")
        for col in detail_cols:
            if row.get(col) is not None:
                lines.append(f"\n        ↳ {labels[col]}: {row[col]}")
    return lines
