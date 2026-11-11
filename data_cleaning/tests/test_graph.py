"""End-to-end tests of the cleaning graph with in-memory ports (no real data, no network)."""

from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.application.graph.nodes import CLEANING_QUESTION, Dependencies
from cleaning_agent.entrypoints.cli import describe, run_start
from cleaning_agent.entrypoints.cli import run_resume as cli_resume
from tests.fakes import (
    INTAKE,
    PATHS,
    RAW,
    FakeStorage,
    answer_layer_and_front,
    begin,
    make_deps,
    sample_df,
)


def run_resume(app: Any, thread_id: str, answer: Any) -> dict[str, Any]:
    """Resumes like the CLI, passing bronze and the Front for tests about later steps."""
    return answer_layer_and_front(
        cli_resume, app, thread_id, cli_resume(app, thread_id, answer)
    )


def _app(deps: Dependencies) -> Any:
    return build_graph(deps).compile(checkpointer=InMemorySaver())


def _kind(view: dict[str, Any]) -> str | None:
    return (view.get("interrupt") or {}).get("kind")


def test_flow_starts_with_country_bottler_channel_premise_and_raw():
    deps, *_ = make_deps()

    view = run_start(_app(deps), "t1")

    assert view["status"] == "waiting_for_human"
    assert view["interrupt"]["kind"] == "intake"
    fields = view["interrupt"]["fields"]
    assert [f["name"] for f in fields] == [
        "country",
        "bottler",
        "channel",
        "premise",
        "dataplor_raw",
    ]
    assert fields[0]["options"] == ["mx", "pe"]
    assert fields[2]["options"] == ["tradicional", "moderno"]
    assert fields[3]["options"] == ["off_premise", "on_premise", "ambos"]


def test_second_question_is_whether_to_clean_dataplor():
    deps, *_ = make_deps()
    app = _app(deps)
    run_start(app, "t1")

    view = run_resume(app, "t1", dict(INTAKE))

    assert view["interrupt"]["kind"] == "choose_cleaning"
    assert view["interrupt"]["question"] == CLEANING_QUESTION
    assert view["interrupt"]["options"][2] == {
        "clean": False,
        "label": "No: el Dataplor raw va directo al Pipeline Data clean",
    }


def test_intake_accepts_any_iso2_and_rejects_a_missing_raw():
    deps, *_ = make_deps()
    app = _app(deps)
    run_start(app, "t1")

    view = run_resume(
        app, "t1", {**INTAKE, "country": "CO", "dataplor_raw": "x/nada.parquet"}
    )

    assert view["interrupt"]["kind"] == "intake"
    # Countries without patterns are fine here: check_patterns creates them later
    assert view["interrupt"]["errors"] == [
        "dataplor_raw: no local file matches x/nada.parquet",
    ]
    # The retry keeps what was typed, so only the wrong fields need fixing
    assert view["interrupt"]["defaults"]["bottler"] == "Femsa"


def test_forms_are_prefilled_from_the_intake():
    deps, *_ = make_deps()
    app = _app(deps)

    view = begin(app, "t1", "geojson")

    defaults = view["interrupt"]["defaults"]
    assert defaults["parquet"] == RAW
    assert defaults["raw_csv"] == PATHS["raw_csv"]
    assert defaults["output_csv"] == PATHS["output_csv"]


@pytest.mark.parametrize("mode", ["geojson", "clientes_bottler"])
def test_prefilter_modes_run_to_publication(mode):
    deps, datasets, audit, prefilter = make_deps()
    app = _app(deps)
    view = begin(app, "t1", mode)
    assert _kind(view) == "collect_inputs"
    view = run_resume(app, "t1", {})  # accept the defaults
    assert _kind(view) == "confirm_plan"
    assert [m["id"] for m in view["interrupt"]["modules"]] == [1, 2]
    view = run_resume(app, "t1", {"approved": True})
    assert _kind(view) == "confirm_layer_upload"
    qa = view["interrupt"]["qa"]  # silver validation shows the cleaning QA
    assert view["interrupt"]["layer"] == "silver"
    view = run_resume(app, "t1", {"approved": True})

    assert (
        _kind(view) == "front_datamatch"
    )  # CSV published, report done, then the Front
    assert prefilter.calls == ["t1"]  # thread id travels as the correlation id
    assert qa["filas_leidas"] == 4
    assert qa["filas_conservadas"] == 2  # module 1 drops OXXO, module 2 drops one more
    assert list(qa["eliminadas_por_motivo"].values()) == [1, 1]
    assert datasets.published[PATHS["output_csv"]].height == 2
    assert datasets.drops == ["01_fake", "02_fake"]
    assert datasets.cleared == 1
    assert audit.finished and audit.steps == ["MODULE 1 (Fake 1: chains)"]
    assert Path(view["result"]["report_path"]).parent.parts[:2] == ("data", "silver")


def test_no_cleaning_sends_the_raw_dataplor_to_the_pipeline():
    deps, datasets, _, prefilter = make_deps()
    datasets.inputs[RAW] = sample_df()
    app = _app(deps)

    view = begin(app, "t1", "ninguno")
    assert view["interrupt"]["defaults"]["raw_csv"] == RAW
    view = run_resume(app, "t1", {})
    assert _kind(view) == "confirm_plan"
    view = run_resume(app, "t1", {"approved": True, "modules": [2]})
    view = run_resume(app, "t1", {"approved": True})

    assert _kind(view) == "front_datamatch"
    assert datasets.published[PATHS["output_csv"]].height == 3
    assert prefilter.calls == []
    assert view["result"]["modules"] == [2]


def test_invalid_answers_are_reasked_then_the_run_is_cancelled():
    deps, *_ = make_deps()  # max_attempts=2
    app = _app(deps)
    run_start(app, "t1")
    run_resume(app, "t1", dict(INTAKE))

    view = run_resume(app, "t1", {"clean": True})  # type missing
    assert _kind(view) == "choose_cleaning"
    assert "type is required" in view["interrupt"]["errors"][0]
    view = run_resume(app, "t1", {"clean": True, "type": "otro"})

    assert view["status"] == "cancelled"
    assert "Too many invalid answers" in view["error"]


def test_missing_files_are_reported_and_corrected_answer_is_merged():
    deps, *_ = make_deps()
    app = _app(deps)
    begin(app, "t1", "geojson")

    view = run_resume(app, "t1", {"geojson": "data/raw/mx/femsa/otro.geojson"})
    assert view["interrupt"]["errors"] == [
        "geojson: not found locally or in Azure (data/raw/mx/femsa/otro.geojson)"
    ]
    # The retry pre-fills the previous answer, so only the fix is needed
    assert view["interrupt"]["defaults"]["geojson"] == "data/raw/mx/femsa/otro.geojson"
    view = run_resume(app, "t1", {"geojson": "data/raw/mx/femsa/territorio.geojson"})

    assert _kind(view) == "confirm_plan"


def test_rejected_plan_cancels_without_touching_data():
    deps, datasets, _, prefilter = make_deps()
    app = _app(deps)
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})

    view = run_resume(app, "t1", {"approved": False, "note": "otro día"})

    assert view["status"] == "cancelled"
    assert prefilter.calls == [] and datasets.steps == {}


def test_unknown_module_in_plan_is_reasked():
    deps, *_ = make_deps()
    app = _app(deps)
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})

    view = run_resume(app, "t1", {"approved": True, "modules": [9]})

    assert _kind(view) == "confirm_plan"
    assert "Unknown modules [9]" in view["interrupt"]["errors"][0]


def test_nightlife_plan_skips_final_regex():
    deps, *_ = make_deps()
    app = _app(deps)
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})

    view = run_resume(app, "t1", {"approved": True, "modules": [0, 5, 1]})
    view = run_resume(app, "t1", {"approved": True})

    assert view["result"]["modules"] == [0, 1]


def test_declined_silver_stays_local_after_the_report_is_shown():
    deps, datasets, *_ = make_deps()
    app = _app(deps)
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True})

    view = run_resume(app, "t1", {"approved": False, "note": "faltan columnas"})

    # The local CSV + report are built for the review; declining keeps them local only
    assert view["status"] == "kept_local"
    assert PATHS["output_csv"] in datasets.published
    assert not [u for u in deps.storage.uploads if u[2].startswith("silver/")]
    assert view["result"]["note"] == "faltan columnas"


def test_prefilter_error_marks_the_run_failed():
    deps, *_ = make_deps(prefilter_error=ValueError("No Dataplor point fell inside"))
    app = _app(deps)
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})

    view = run_resume(app, "t1", {"approved": True})

    assert view["status"] == "failed"
    assert "No Dataplor point fell inside" in view["error"]


def test_run_resumes_from_sqlite_in_a_new_process(tmp_path: Path):
    deps, *_ = make_deps()
    db = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(db) as saver:
        app = build_graph(deps).compile(checkpointer=saver)
        begin(app, "t1", "geojson")

    # A fresh graph + connection, as after closing the terminal
    with SqliteSaver.from_conn_string(db) as saver:
        app = build_graph(deps).compile(checkpointer=saver)
        view = describe(app, "t1")

    assert view["status"] == "waiting_for_human"
    assert _kind(view) == "collect_inputs"


def test_start_twice_and_resume_without_question_are_refused():
    deps, *_ = make_deps()
    app = _app(deps)
    run_start(app, "t1")

    with pytest.raises(SystemExit, match="already exists"):
        run_start(app, "t1")
    with pytest.raises(SystemExit, match="not waiting"):
        run_resume(app, "unknown", {"clean": False})
    assert describe(app, "unknown")["status"] == "not_found"


BLOB_RAW = "dataplorraw/dataplor_raw_parquet/2026-10-15_ar.csv.parquet/part-00000-x.snappy.parquet"


def test_raw_dataplor_in_blob_is_checked_and_downloaded():
    storage = FakeStorage(blobs=[BLOB_RAW.removeprefix("dataplorraw/")])
    deps, *_ = make_deps(storage=storage)
    app = _app(deps)
    run_start(app, "t1")

    view = run_resume(app, "t1", {**INTAKE, "dataplor_raw": BLOB_RAW})
    assert view["interrupt"]["kind"] == "choose_cleaning"
    view = run_resume(app, "t1", {"clean": False})

    assert storage.downloads == [("dataplorraw", BLOB_RAW.removeprefix("dataplorraw/"))]
    local = view["interrupt"]["defaults"]["raw_csv"]
    assert local.replace("\\", "/").endswith(
        "mx/femsa/dataplor_raw/part-00000-x.snappy.parquet"
    )


def test_raw_blob_requires_configured_azure_and_existing_blob():
    deps, *_ = make_deps(storage=FakeStorage(configured=False))
    app = _app(deps)
    run_start(app, "t1")

    view = run_resume(app, "t1", {**INTAKE, "dataplor_raw": BLOB_RAW})
    assert "Azure is not configured" in view["interrupt"]["errors"][0]

    deps, *_ = make_deps(storage=FakeStorage(blobs=[]))
    app = _app(deps)
    run_start(app, "t2")
    view = run_resume(app, "t2", {**INTAKE, "dataplor_raw": BLOB_RAW})
    assert view["interrupt"]["errors"] == [f"dataplor_raw: no blob matches {BLOB_RAW}"]


def test_dataplorraw_default_applies_only_to_the_raw_path():
    from cleaning_agent.domain.models import raw_blob_location

    assert raw_blob_location(BLOB_RAW, "dataplorraw") == (
        "dataplorraw",
        BLOB_RAW.removeprefix("dataplorraw/"),
    )
    assert raw_blob_location("data/raw/mx/x.parquet", "dataplorraw") is None
    assert raw_blob_location("otrocontenedor/x.parquet", "dataplorraw") is None


def test_geojson_in_another_container_is_downloaded_before_the_plan():
    blob = "global_geojson/Argentina_Andina.geojson"
    storage = FakeStorage(blobs=[blob])
    deps, *_ = make_deps(storage=storage)
    app = _app(deps)
    begin(app, "t1", "geojson")

    view = run_resume(app, "t1", {"geojson": f"prospection-datacleaning/{blob}"})

    assert view["interrupt"]["kind"] == "confirm_plan"
    assert storage.downloads == [("prospection-datacleaning", blob)]
    local = view["interrupt"]["inputs"]["geojson"].replace("\\", "/")
    assert local.endswith("mx/femsa/insumos/Argentina_Andina.geojson")


def _statuses(view: dict[str, Any]) -> dict[str, str]:
    return {step["step"]: step["status"] for step in view["steps"]}


def test_every_step_has_a_visible_status():
    deps, *_ = make_deps()
    app = _app(deps)

    view = begin(app, "t1", "geojson")

    status = _statuses(view)
    assert view["current_step"] == "collect_inputs"
    assert (
        status["intake"] == status["choose_cleaning"] == status["fetch_raw"] == "done"
    )
    assert status["collect_inputs"] == "waiting_for_human"
    assert status["prefilter"] == status["upload_prospects"] == "pending"
    intake = next(s for s in view["steps"] if s["step"] == "intake")
    assert intake["started_at"] <= intake["finished_at"]


def test_status_map_tracks_retries_modules_and_skips():
    deps, datasets, *_ = make_deps()
    datasets.inputs[RAW] = sample_df()
    app = _app(deps)
    run_start(app, "t1")
    view = run_resume(app, "t1", {**INTAKE, "country": "mex"})
    assert _statuses(view)["intake"] == "retry"

    run_resume(app, "t1", dict(INTAKE))
    run_resume(app, "t1", {"clean": False})
    run_resume(app, "t1", {})
    view = run_resume(app, "t1", {"approved": True, "modules": [1, 2]})

    status = _statuses(view)
    assert status["prefilter"] == "skipped"
    assert status["run_module:1"] == status["run_module:2"] == "done"
    assert status["confirm_silver"] == "waiting_for_human"


def test_progress_markdown_lists_the_flow():
    from cleaning_agent.application.graph.progress import progress_markdown

    deps, *_ = make_deps()
    view = begin(_app(deps), "t1", "geojson")

    text = progress_markdown("t1", view["status"], view["steps"])

    assert "Datos de la corrida" in text and "⏸️" in text and "⬜" in text
