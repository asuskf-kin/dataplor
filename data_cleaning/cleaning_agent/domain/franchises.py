"""Franchise marks: columns, never deletions (the person decides removal)."""

import polars as pl

NAME_COLUMNS = ("name_normalized", "name")


def name_column(df: pl.DataFrame) -> str:
    for column in NAME_COLUMNS:
        if column in df.columns:
            return column
    raise ValueError(f"No name column for the franchise review ({NAME_COLUMNS})")


def mark_franchises(df: pl.DataFrame, flags: dict[str, str]) -> pl.DataFrame:
    """Adds es_franquicia (Sí/No) and franquicia_marca for the flagged names."""
    column = name_column(df)
    brand = pl.col(column).cast(pl.String).replace_strict(flags, default=None)
    return df.with_columns(
        pl.when(brand.is_not_null())
        .then(pl.lit("Sí"))
        .otherwise(pl.lit("No"))
        .alias("es_franquicia"),
        brand.fill_null("").alias("franquicia_marca"),
    )
