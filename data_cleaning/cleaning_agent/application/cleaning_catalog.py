"""Catalog of the cleaning modules (0-6) and the rules to build a run plan.

The modules themselves are the pure Polars functions in ``src/``; this file only
fixes their parameters, as ``main.py``'s PIPELINE_STEPS used to.
"""

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

import cleaning_agent.domain.patterns as patterns_package
from cleaning_agent.domain.cleaning.adv_filters import apply_hours_and_fuzzy_filters
from cleaning_agent.domain.cleaning.chain_removal import filter_chains_and_duplicates
from cleaning_agent.domain.cleaning.crowded_property import filter_crowded_same_property
from cleaning_agent.domain.cleaning.dedup import deduplicate_records_with_audit
from cleaning_agent.domain.cleaning.final_regex import final_keyword_exclusion
from cleaning_agent.domain.cleaning.geo_dedup import balltree_spatial_deduplication
from cleaning_agent.domain.cleaning.nightlife_filter import keep_nightlife_businesses
from cleaning_agent.domain.cleaning.normalize import normalize_names

NIGHTLIFE_MODULE = 0
FINAL_REGEX_MODULE = 5


@dataclass(frozen=True)
class ModuleOutcome:
    """Normalised return of every module (they return 3- or 4-tuples in ``src/``)."""

    df: pl.DataFrame
    items_to_track: list[str]
    report: str | None
    dropped: pl.DataFrame | None


ModuleFn = Callable[[pl.DataFrame, list[str]], tuple[Any, ...]]


@dataclass(frozen=True)
class CleaningModule:
    module_id: int
    name: str
    file_stem: str
    run_fn: ModuleFn

    def run(self, df: pl.DataFrame, items_to_track: list[str]) -> ModuleOutcome:
        result = self.run_fn(df, items_to_track)
        if len(result) == 4:
            out_df, items, report, dropped = result
        else:
            out_df, items, report = result
            dropped = None
        return ModuleOutcome(out_df, list(items or []), report, dropped)


def _normalize(df: pl.DataFrame, items: list[str]) -> tuple[Any, ...]:
    df_norm, df_dropped = deduplicate_records_with_audit(
        df=normalize_names(df), subset=["name_normalized", "latitude", "longitude"]
    )
    return df_norm, items, None, df_dropped


# Country codes with a chain-pattern file (config/patterns_<code>.py). ISO 2 'do'
# (República Dominicana) maps to the historical 'rd' file.
COUNTRY_ALIASES = {"do": "rd"}


def supported_countries() -> list[str]:
    folder = Path(patterns_package.__file__).parent
    codes = {p.stem.removeprefix("patterns_") for p in folder.glob("patterns_*.py")}
    aliased = {alias for alias, code in COUNTRY_ALIASES.items() if code in codes}
    # Offer ISO 2 codes only: the file 'rd' is reached through its alias 'do'
    return sorted((codes - set(COUNTRY_ALIASES.values())) | aliased)


def chain_regex_for(country: str) -> list[str]:
    """CHAIN_REGEX of the run's country (the country is chosen per run, not in config)."""
    code = COUNTRY_ALIASES.get(country.lower(), country.lower())
    try:
        module = importlib.import_module(
            f"cleaning_agent.domain.patterns.patterns_{code}"
        )
    except ModuleNotFoundError as exc:
        raise ValueError(
            f"No chain patterns for country '{country}'. Available: {supported_countries()}"
        ) from exc
    return list(module.CHAIN_REGEX)


# Module 0 defaults; config.yaml (nightlife_filter) overrides them through the wiring
NIGHTLIFE_DEFAULTS: dict[str, Any] = {
    "include_probable": True,
    "include_night_hours": True,
    "night_close_hour": 21,
    "late_open_hour": 16,
}


def catalog_for(
    country: str, nightlife: Mapping[str, Any] | None = None
) -> dict[int, CleaningModule]:
    """The seven cleaning modules with their parameters for one country."""
    chain_regex = chain_regex_for(country)
    night = {**NIGHTLIFE_DEFAULTS, **(nightlife or {})}
    return {
        module.module_id: module
        for module in (
            CleaningModule(
                0,
                "Module 0: Nightlife Filter",
                "00_nightlife_kept",
                lambda df, items: keep_nightlife_businesses(
                    df,
                    include_probable=night["include_probable"],
                    include_night_hours=night["include_night_hours"],
                    night_close_hour=night["night_close_hour"],
                    late_open_hour=night["late_open_hour"],
                    items_to_track=items,
                ),
            ),
            CleaningModule(
                1, "Module 1: Normalization", "01_normalized_deduped", _normalize
            ),
            CleaningModule(
                2,
                "Module 2: Chain Filter",
                "02_chains_filtered",
                lambda df, items: filter_chains_and_duplicates(
                    df,
                    filter_duplicates=False,
                    max_appearances=4,
                    items_to_track=items,
                    chain_regex=chain_regex,
                ),
            ),
            CleaningModule(
                3,
                "Module 3: BallTree Dedup",
                "03_geo_balltree_deduped",
                lambda df, items: balltree_spatial_deduplication(
                    df, radius_meters=50, items_to_track=items
                ),
            ),
            CleaningModule(
                4,
                "Module 4: Hours & Fuzzy",
                "04_hours_fuzzy_filtered",
                lambda df, items: apply_hours_and_fuzzy_filters(
                    df,
                    min_hours=20,
                    night_start=19,
                    fuzzy_thresh=80,
                    dist_m=100,
                    items_to_track=items,
                    apply_hours_filter=False,
                ),
            ),
            CleaningModule(
                5,
                "Module 5: Final Regex",
                "05_external_regex_excluded",
                lambda df, items: final_keyword_exclusion(df, items_to_track=items),
            ),
            CleaningModule(
                6,
                "Module 6: Crowded Property",
                "06_crowded_properties_filtered",
                lambda df, items: filter_crowded_same_property(
                    df, threshold=4, radius_m=100.0, items_to_track=items
                ),
            ),
        )
    }


MODULE_IDS = (0, 1, 2, 3, 4, 5, 6)
# Shown in the plan before the country's patterns exist (they may be created later)
MODULE_NAMES = {
    0: "Module 0: Nightlife Filter",
    1: "Module 1: Normalization",
    2: "Module 2: Chain Filter",
    3: "Module 3: BallTree Dedup",
    4: "Module 4: Hours & Fuzzy",
    5: "Module 5: Final Regex",
    6: "Module 6: Crowded Property",
}


def build_module_plan(
    requested: list[int], catalog: Mapping[int, CleaningModule] | None = None
) -> tuple[list[int], list[str]]:
    """Validates and orders the modules to run.

    Returns:
        ``(modules, notes)``: the ids in pipeline order and why any was left out.

    Raises:
        ValueError: On unknown ids or an empty plan.
    """
    valid = set(catalog) if catalog is not None else set(MODULE_IDS)
    unknown = sorted(set(requested) - valid)
    if unknown:
        raise ValueError(f"Unknown modules {unknown}. Valid: {sorted(valid)}")
    modules = sorted(set(requested))
    notes: list[str] = []
    # With the nightlife filter every record is a bar, so the Final Regex would only
    # remove bars by keyword (same rule main.py applied)
    if NIGHTLIFE_MODULE in modules and FINAL_REGEX_MODULE in modules:
        modules.remove(FINAL_REGEX_MODULE)
        notes.append("Module 5 skipped: Module 0 (nightlife) is active")
    if not modules:
        raise ValueError("The plan must run at least one module")
    return modules, notes
