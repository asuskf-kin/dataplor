"""Module 7: rented flats (Airbnb / departamento) leave the cleaning pipeline.

User, 2026-11-23: "lo de Airbnb es un paso que se debe agregar al pipeline de limpieza".
Before, these points were only removed after the Datamatch, so they travelled through the
whole Datamatch cycle and the person read them as part of it. The rule is the same
(``LODGING_RENTAL_REGEX``, only inside the lodging category); the Datamatch closing keeps
it as a safety net for runs cleaned before this module existed.
"""

from typing import Any

import polars as pl

from cleaning_agent.domain.datamatch_steps import (
    LODGING_REASON,
    LODGING_RENTAL_REGEX,
    lodging_rentals,
    lodging_term,
)

LODGING_MODULE = 7


def remove_lodging_rentals(
    df: pl.DataFrame, items_to_track: list[str]
) -> tuple[pl.DataFrame, list[str], Any, pl.DataFrame]:
    """Drops the Airbnb / apartment rentals; returns (kept, items, report, dropped).

    ``dropped`` carries ``drop_reason`` and ``drop_match`` (the word that matched), so the
    executive report lists them as their own step and sheet.
    """
    mask = lodging_rentals(df)
    if not mask.any():
        return df, items_to_track, None, df.clear()
    dropped = df.filter(mask)
    dropped = dropped.with_columns(
        pl.lit(LODGING_REASON).alias("drop_reason"),
        pl.Series(
            "drop_match",
            [lodging_term(n) for n in dropped.get_column("name").to_list()],
            dtype=pl.String,
        ),
        pl.lit(LODGING_RENTAL_REGEX).alias("drop_pattern"),
    )
    return df.filter(~mask), items_to_track, None, dropped
