"""Domain contracts and plan rules."""

import pytest
from pydantic import ValidationError

from cleaning_agent.application.cleaning_catalog import (
    build_module_plan,
    catalog_for,
    chain_regex_for,
    supported_countries,
)
from cleaning_agent.domain.models import (
    CleaningChoice,
    ClientInputs,
    GeojsonInputs,
    IntakeAnswer,
    NoPrefilterInputs,
    PlanDecision,
    StepMetric,
)
from cleaning_agent.entrypoints.cli import (
    _check_thread_id,
    _merge_answer,
    _parse_answer,
)
from tests.fakes import CLIENTS, GEO, PATHS


def test_intake_normalises_country_and_validates_choices():
    answer = IntakeAnswer.model_validate(
        {
            "country": "MX",
            "bottler": "Centro Pacifico",
            "channel": "moderno",
            "premise": "ambos",
            "dataplor_raw": "data/raw/mx/part-*.parquet",
        }
    )
    assert answer.country == "mx"
    with pytest.raises(ValidationError):
        IntakeAnswer.model_validate({**answer.model_dump(), "channel": "online"})
    with pytest.raises(ValidationError):
        IntakeAnswer.model_validate({**answer.model_dump(), "country": "mex"})
    with pytest.raises(ValidationError):
        IntakeAnswer.model_validate({**answer.model_dump(), "dataplor_raw": "raw.xlsx"})


def test_cleaning_choice_maps_to_modes():
    assert CleaningChoice(clean=True, type="distancia").mode == "geojson"
    assert CleaningChoice(clean=True, type="client_bottler").mode == "clientes_bottler"
    assert CleaningChoice(clean=False).mode == "ninguno"
    with pytest.raises(ValidationError, match="type is required"):
        CleaningChoice(clean=True)


def test_geojson_inputs_apply_defaults():
    inputs = GeojsonInputs.model_validate(GEO)

    assert (
        inputs.only_active_open
        and inputs.batch_size == 200_000
        and inputs.bottler == ""
    )


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"parquet": "data/raw/x.csv"}, "parquet"),
        ({"geojson": "data/raw/x.shp"}, "geojson"),
        ({"raw_csv": ""}, "raw_csv"),
        ({"output_csv": PATHS["raw_csv"]}, "different files"),
        ({"batch_size": 0}, "batch_size"),
        ({"unexpected": True}, "unexpected"),
        ({"raw_csv": "a\x00.csv"}, "null byte"),
    ],
)
def test_geojson_inputs_reject_bad_values(changes, field):
    with pytest.raises(ValidationError, match=field):
        GeojsonInputs.model_validate({**GEO, **changes})


def test_client_inputs_bound_the_radius():
    assert ClientInputs.model_validate(CLIENTS).radius_m == 900
    with pytest.raises(ValidationError, match="radius_m"):
        ClientInputs.model_validate({**CLIENTS, "radius_m": 0})
    with pytest.raises(ValidationError, match="radius_m"):
        ClientInputs.model_validate({**CLIENTS, "radius_m": 60_000})


def test_no_prefilter_inputs_only_need_paths():
    assert NoPrefilterInputs.model_validate(PATHS).raw_csv == PATHS["raw_csv"]


def test_plan_decision_limits_note_length():
    with pytest.raises(ValidationError):
        PlanDecision.model_validate({"approved": True, "note": "x" * 2001})


def test_step_metric_dropped():
    assert (
        StepMetric(module_id=1, step_name="m", rows_before=10, rows_after=7).dropped
        == 3
    )


def test_build_module_plan_orders_dedups_and_skips_regex_with_nightlife():
    assert build_module_plan([3, 1, 1]) == ([1, 3], [])
    modules, notes = build_module_plan([5, 0, 6])
    assert modules == [0, 6] and "Module 5 skipped" in notes[0]


def test_build_module_plan_rejects_unknown_or_empty():
    with pytest.raises(ValueError, match="Unknown modules"):
        build_module_plan([7])
    with pytest.raises(ValueError, match="at least one"):
        build_module_plan([])


def test_catalog_is_built_per_country():
    assert sorted(catalog_for("mx")) == [0, 1, 2, 3, 4, 5, 6]
    assert chain_regex_for("do") == chain_regex_for("rd")  # ISO 2 alias
    assert "rd" not in supported_countries() and "do" in supported_countries()
    with pytest.raises(ValueError, match="No chain patterns"):
        catalog_for("zz")


def test_merge_answer_only_for_path_forms():
    pending = {"kind": "collect_inputs", "defaults": {"a": 1, "b": 2}}

    assert _merge_answer(pending, {"b": 3}) == {"a": 1, "b": 3}
    assert _merge_answer({"kind": "choose_cleaning"}, {"clean": False}) == {
        "clean": False
    }


def test_cli_rejects_bad_thread_ids_and_json():
    assert _check_thread_id("dataplor-2026_11") == "dataplor-2026_11"
    with pytest.raises(SystemExit):
        _check_thread_id("../etc")
    with pytest.raises(SystemExit, match="not valid JSON"):
        _parse_answer("{mode: geojson}")
