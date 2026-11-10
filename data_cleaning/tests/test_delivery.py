"""Delivery branch: ¿Datamatch? -> Front -> QA -> Azure, with in-memory ports."""

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.entrypoints.cli import run_resume as cli_resume
from tests.fakes import (
    CLIENTS_FILE,
    DATAMATCH_FILE,
    PATHS,
    RAW,
    FakeDatasets,
    FakeQA,
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


def _kind(view: dict[str, Any]) -> str | None:
    return (view.get("interrupt") or {}).get("kind")


def _to_datamatch_question(deps: Dependencies) -> Any:
    # Mode 'no cleaning': no bronze upload, so Azure is only used by the final upload
    assert isinstance(deps.datasets, FakeDatasets)
    deps.datasets.inputs[RAW] = sample_df()
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True})
    view = run_resume(app, "t1", {"approved": True})
    assert _kind(view) == "ask_datamatch"
    return app


def test_full_delivery_with_datamatch_qa_and_azure():
    qa, storage = FakeQA(), FakeStorage()
    deps, *_ = make_deps(qa=qa, storage=storage)
    app = _to_datamatch_question(deps)

    view = run_resume(app, "t1", {"run_datamatch": True})
    assert _kind(view) == "front_datamatch"
    assert view["interrupt"]["front_url"] == "https://front.example/home"
    assert view["interrupt"]["file_to_upload"] == PATHS["output_csv"]
    assert view["interrupt"]["defaults"]["client_name"] == "femsa"
    assert view["interrupt"]["defaults"]["clients_file"] == CLIENTS_FILE

    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})
    assert _kind(view) == "qa_thresholds"
    assert view["interrupt"]["qa_report"] == "t1/threshold_report.html"

    view = run_resume(app, "t1", {"match": 0.75})  # super_match keeps its default
    assert _kind(view) == "confirm_upload"
    assert view["interrupt"]["storage_configured"] is True
    assert view["interrupt"]["files"] == [
        PATHS["output_csv"],
        "t1/Datamatch_Final_femsa.csv",
    ]
    assert view["interrupt"]["defaults"] == {
        "container": "prospeccion",
        "blob_prefix": "p/mx/femsa",
    }

    view = run_resume(app, "t1", {"approved": True})

    assert view["status"] == "uploaded"
    assert qa.runs == [(0.75, 0.8)]
    assert storage.uploads == [
        (
            [PATHS["output_csv"], "t1/Datamatch_Final_femsa.csv"],
            "prospeccion",
            "p/mx/femsa",
        )
    ]


def test_no_datamatch_goes_straight_to_upload_and_can_stay_local():
    storage = FakeStorage()
    deps, *_ = make_deps(storage=storage)
    app = _to_datamatch_question(deps)

    view = run_resume(app, "t1", {"run_datamatch": False})
    assert _kind(view) == "confirm_upload"
    assert view["interrupt"]["files"] == [PATHS["output_csv"]]
    view = run_resume(app, "t1", {"approved": False, "note": "lo subo mañana"})

    assert view["status"] == "kept_local"
    assert storage.uploads == []


def test_front_reasks_when_the_datamatch_file_is_missing():
    deps, *_ = make_deps()
    app = _to_datamatch_question(deps)
    run_resume(app, "t1", {"run_datamatch": True})

    view = run_resume(app, "t1", {"datamatch_file": "data/front/otro.csv"})
    assert view["interrupt"]["errors"] == [
        "datamatch_file: file not found data/front/otro.csv"
    ]
    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})

    assert _kind(view) == "qa_thresholds"


def test_front_rejects_unsafe_client_names():
    deps, *_ = make_deps()
    app = _to_datamatch_question(deps)
    run_resume(app, "t1", {"run_datamatch": True})

    view = run_resume(
        app, "t1", {"datamatch_file": DATAMATCH_FILE, "client_name": "../x"}
    )

    assert _kind(view) == "front_datamatch"
    assert "client_name" in view["interrupt"]["errors"][0]


def test_thresholds_must_be_ordered():
    deps, *_ = make_deps()
    app = _to_datamatch_question(deps)
    run_resume(app, "t1", {"run_datamatch": True})
    run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})

    view = run_resume(app, "t1", {"match": 0.9, "super_match": 0.8})

    assert _kind(view) == "qa_thresholds"
    assert "super_match cannot be lower" in view["interrupt"]["errors"][0]


def test_upload_needs_configured_storage_and_valid_container():
    storage = FakeStorage(configured=False)
    deps, *_ = make_deps(storage=storage)
    app = _to_datamatch_question(deps)
    view = run_resume(app, "t1", {"run_datamatch": False})
    assert view["interrupt"]["storage_configured"] is False

    view = run_resume(app, "t1", {"approved": True, "container": "Bad_Name"})
    assert "container" in view["interrupt"]["errors"][0]
    # Retry keeps the previous (invalid) answer as the new default; fix only the container
    storage.configured = False
    view = run_resume(app, "t1", {"approved": True, "container": "prospeccion"})

    assert view["status"] == "cancelled"  # max_attempts=2: Azure still not configured
    assert storage.uploads == []


def test_qa_failure_marks_the_run_failed():
    deps, *_ = make_deps(qa=FakeQA(error=RuntimeError("QA_datamatch 'explore' failed")))
    app = _to_datamatch_question(deps)
    run_resume(app, "t1", {"run_datamatch": True})

    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})

    assert view["status"] == "failed"
    assert "QA datamatch (explore)" in view["error"]


def test_upload_failure_marks_the_run_failed():
    deps, *_ = make_deps(storage=FakeStorage(error=RuntimeError("Upload of x failed")))
    app = _to_datamatch_question(deps)
    run_resume(app, "t1", {"run_datamatch": False})

    view = run_resume(app, "t1", {"approved": True})

    assert view["status"] == "failed"
    assert "Azure upload" in view["error"]
