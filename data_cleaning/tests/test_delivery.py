"""Delivery: report -> Front Datamatch loop -> gold prospects -> priorización (fakes)."""

import dataclasses
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.application.graph.warehouse_nodes import _cleaned_dataplor
from cleaning_agent.entrypoints.cli import run_resume as cli_resume
from tests.fakes import (
    CLIENTS_FILE,
    DATAMATCH_FILE,
    RAW,
    FakeDatasets,
    FakeStorage,
    answer_layer_and_front,
    begin,
    make_deps,
    sample_df,
)


def run_resume(app: Any, thread_id: str, answer: Any) -> dict[str, Any]:
    """Resumes like the CLI, passing bronze, the Front and the franchise review."""
    return answer_layer_and_front(
        cli_resume, app, thread_id, cli_resume(app, thread_id, answer)
    )


def _kind(view: dict[str, Any]) -> str | None:
    return (view.get("interrupt") or {}).get("kind")


def _to_front_datamatch(deps: Dependencies) -> Any:
    # Mode 'no cleaning': no bronze upload, so Azure is only used by the final upload
    assert isinstance(deps.datasets, FakeDatasets)
    deps.datasets.inputs[RAW] = sample_df()
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True})  # plan -> Front -> cleaning -> review
    view = run_resume(app, "t1", {"approved": True})  # publish -> report -> 2nd Front
    assert _kind(view) == "front_datamatch", view
    return app


def _to_prospects(
    storage: FakeStorage, **steps: Any
) -> tuple[Any, Dependencies, dict[str, Any]]:
    """Front step -> loop done -> the gold prospects file waits for approval."""
    deps, *_ = make_deps(storage=storage)
    for name, value in steps.items():
        setattr(deps.datamatch_steps, name, value)
    app = _to_front_datamatch(deps)
    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})
    if view.get("status") != "failed":
        assert _kind(view) == "confirm_layer_upload"
        assert view["interrupt"]["layer"] == "gold"
    return app, deps, view


def test_datamatch_front_comes_right_after_the_executive_report():
    deps, *_ = make_deps()
    app = _to_front_datamatch(deps)

    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert steps["executive_report"] == steps["front_datamatch"] == "done"
    assert "ask_datamatch" not in steps and "qa_explore" not in steps


def test_loop_done_sends_the_prospects_to_gold_then_priorizacion():
    storage = FakeStorage()
    app, deps, pending = _to_prospects(storage)
    view = pending["interrupt"]

    prefix = view["defaults"]["blob_prefix"]
    assert prefix.startswith("gold/ko/mx/femsa/prospecting-data/")
    name = Path(view["files"][0]).name
    assert name.startswith("prospects_pdv_trad_on_mx_femsa_") and name.endswith(".csv")
    assert view["qa"]["qa_ok"] and view["qa"]["filas_conservadas"] == 90
    _, match_files, _ = deps.datamatch_steps.prospects[-1]
    assert len(match_files) == 1 and match_files[0].endswith(
        "datamatch_matches_femsa_paso1.csv"
    )

    asked = cli_resume(app, "t1", {"approved": True})
    assert _kind(asked) == "ask_priorizacion"
    assert storage.uploads[-1][2] == prefix
    # Priorización defaults to the uploaded prospects CSV
    assert asked["interrupt"]["defaults"]["input_blob"].endswith(name)

    done = cli_resume(app, "t1", {"run": False})
    assert done["status"] != "failed"


def test_prospects_declined_stay_local():
    storage = FakeStorage()
    app, _, _ = _to_prospects(storage)

    view = cli_resume(app, "t1", {"approved": False, "note": "lo subo mañana"})

    assert view["status"] == "kept_local"
    assert not [u for u in storage.uploads if u[2].startswith("gold/")]


def test_prospects_upload_needs_configured_storage():
    storage = FakeStorage()
    app, _, _ = _to_prospects(storage)
    storage.configured = False  # Azure becomes unavailable before the gold upload

    view = cli_resume(app, "t1", {"approved": True})

    assert _kind(view) == "confirm_layer_upload"
    assert "Azure is not configured" in view["interrupt"]["errors"][0]


def test_prospects_upload_failure_marks_the_run_failed():
    storage = FakeStorage()
    app, _, _ = _to_prospects(storage)
    storage.error = RuntimeError("Upload of x failed")  # fails only at the gold upload

    view = cli_resume(app, "t1", {"approved": True})

    assert view["status"] == "failed"
    assert "Upload gold" in view["error"]


def test_prospects_qa_failure_stops_before_gold():
    # Fewer matched ids found in the cleaned file than matched: counts do not add up
    _, _, view = _to_prospects(FakeStorage(), known_in_file=5)

    assert view["status"] == "failed"
    assert "QA de prospectos" in view["error"]


def test_front_defaults_and_missing_file_reask():
    deps, *_ = make_deps()
    app = _to_front_datamatch(deps)
    view = run_resume(app, "t1", {"datamatch_file": "data/front/otro.csv"})
    assert _kind(view) == "front_datamatch"
    assert view["interrupt"]["errors"] == [
        "datamatch_file: no blob matches data/front/otro.csv"
    ]
    assert view["interrupt"]["defaults"]["client_name"] == "femsa"
    assert view["interrupt"]["defaults"]["clients_file"] == CLIENTS_FILE


def test_front_rejects_unsafe_client_names():
    deps, *_ = make_deps()
    app = _to_front_datamatch(deps)

    view = cli_resume(
        app, "t1", {"datamatch_file": DATAMATCH_FILE, "client_name": "../x"}
    )

    assert _kind(view) == "front_datamatch"
    assert "client_name" in view["interrupt"]["errors"][0]


def test_priorizacion_runs_on_the_prospects_and_stages_its_outputs():
    storage = FakeStorage()
    app, deps, _ = _to_prospects(storage)
    view = cli_resume(app, "t1", {"approved": True})
    defaults = view["interrupt"]["defaults"]
    assert defaults["base_config"] == "mexico_cdf.yaml"  # same country first
    assert (
        defaults["input_blob"].endswith(".csv")
        and "prospects_" in defaults["input_blob"]
    )
    output_dir = defaults["output_dir"]
    assert output_dir.startswith(
        "bronze/ko/mx/femsa/providers/dataplor_on_premise_priority_femsa_mexico/"
    )

    staged = cli_resume(app, "t1", {"run": True})

    run = deps.priorizacion.runs[-1]
    assert (
        run.geodata_prefix == "bronze/providers/dataplor/mx/mexico/WorldPop_Overpass/"
    )
    assert run.step2_name.startswith("dataplor_on_premise_priority_femsa_mexico_")
    assert (
        _kind(staged) == "confirm_layer_upload"
        and staged["interrupt"]["layer"] == "bronze"
    )
    assert staged["interrupt"]["defaults"]["blob_prefix"] == output_dir
    assert staged["interrupt"]["qa"]["qa_ok"]
    names = [Path(f).name for f in staged["interrupt"]["files"]]
    # Only the new sidecars go up: the CSVs were written to Azure by priorización
    assert not [n for n in names if n.endswith(".csv")]
    assert (
        f"{run.step2_name}_metadata.json" in names
        and f"{run.step2_name}_qa.html" in names
    )

    gold = cli_resume(app, "t1", {"approved": True})
    steps = {s["step"]: s["status"] for s in gold["steps"]}
    assert steps["upload_priorizacion"] == "done"
    # Next: the gold delivery package, then the lineage
    assert (
        _kind(gold) == "confirm_layer_upload" and gold["interrupt"]["layer"] == "gold"
    )
    done = cli_resume(app, "t1", {"approved": True})
    steps = {s["step"]: s["status"] for s in done["steps"]}
    assert steps["upload_gold_package"] == steps["build_lineage"] == "done"


def _to_gold_package(
    storage: FakeStorage, **package: Any
) -> tuple[Any, Dependencies, dict[str, Any]]:
    app, deps, _ = _to_prospects(storage)
    for name, value in package.items():
        setattr(deps.gold_package, name, value)
    cli_resume(app, "t1", {"approved": True})  # prospects -> gold
    cli_resume(app, "t1", {"run": True})  # priorización
    view = cli_resume(app, "t1", {"approved": True})  # priorización sidecars
    return app, deps, view


def test_gold_package_follows_the_golfo_layout_in_the_prospects_folder():
    storage = FakeStorage()
    _, deps, view = _to_gold_package(storage)

    request = deps.gold_package.requests[-1]
    assert request.country_name == "mexico" and request.period_label.endswith("2026")
    assert request.clients_total == 100 and request.matched == 10
    pending = view["interrupt"]
    prefix = pending["defaults"]["blob_prefix"]
    assert prefix.startswith("gold/ko/mx/femsa/prospecting-data/")
    root = [Path(f).name for f in pending["files"]]
    assert any(
        n.endswith("_analisis_oportunidad_on_premise_" + request.period + ".xlsx")
        for n in root
    )
    assert any(
        n.startswith("prospecting_femsa_mexico_") and n.endswith(".pptx") for n in root
    )
    extra = {
        e["destination"]: [Path(f).name for f in e["files"]]
        for e in pending["extra_destinations"]
    }
    assert set(extra) == {
        f"prospecting-data/{prefix}/results_ko",
        f"prospecting-data/{prefix}/results_bottler",
    }
    ko = extra[f"prospecting-data/{prefix}/results_ko"]
    assert any(n.endswith("_ko.csv") for n in ko) and any(
        n.endswith("_ko_metadata.json") for n in ko
    )
    assert pending["qa"]["qa_ok"]


def test_gold_package_qa_stops_a_ko_file_with_names():
    _, _, view = _to_gold_package(FakeStorage(), leak_name=True)

    assert view["status"] == "failed"
    assert "QA del paquete gold" in view["error"]


def test_priorizacion_without_a_country_yaml_uses_the_single_base_donor():
    deps, *_ = make_deps()
    deps = dataclasses.replace(deps, priorizacion_base_config="peru_all.yaml")
    deps.priorizacion.configs = ["chile_andina.yaml", "peru_all.yaml"]  # no Mexico YAML
    app = _to_front_datamatch(deps)
    run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})

    view = cli_resume(app, "t1", {"approved": True})

    assert view["interrupt"]["defaults"]["base_config"] == "peru_all.yaml"


def test_priorizacion_rejects_unknown_config():
    app, _, _ = _to_prospects(FakeStorage())
    cli_resume(app, "t1", {"approved": True})

    view = cli_resume(app, "t1", {"run": True, "base_config": "otro.yaml"})

    assert _kind(view) == "ask_priorizacion"
    assert "unknown config" in view["interrupt"]["errors"][0]


def test_datamatch_result_in_the_dwh_is_downloaded_from_prospecting_data():
    blob = "silver/ko/ar/andina/20261110_data_match_process/20261110/final_output.csv"
    storage = FakeStorage(blobs=[blob])
    deps, *_ = make_deps(storage=storage)
    app = _to_front_datamatch(deps)

    view = run_resume(app, "t1", {"datamatch_file": blob})

    assert storage.downloads == [("prospecting-data", blob)]
    assert _kind(view) == "confirm_layer_upload"
    state = app.get_state({"configurable": {"thread_id": "t1"}}).values
    local = state["datamatch"]["datamatch_file"].replace("\\", "/")
    assert local == f"data/{blob}"
    assert state["datamatch"]["clients_file"] == CLIENTS_FILE


def test_datamatch_blob_that_does_not_exist_is_asked_again():
    deps, *_ = make_deps(storage=FakeStorage(blobs=[]))
    app = _to_front_datamatch(deps)

    view = run_resume(app, "t1", {"datamatch_file": "silver/ko/ar/x/final_output.csv"})

    assert _kind(view) == "front_datamatch"
    assert "no blob matches prospecting-data/silver" in " ".join(
        view["interrupt"]["errors"]
    )


def test_datamatch_loop_cleans_clients_per_step_until_the_person_says_done():
    deps, *_ = make_deps()
    app = _to_front_datamatch(deps)
    step = {"datamatch_file": DATAMATCH_FILE, "step_json": "data/front/paso1.json"}
    deps.datasets.files.add("data/front/paso1.json")

    first = cli_resume(app, "t1", step)
    assert _kind(first) == "confirm_layer_upload"
    prefix = first["interrupt"]["defaults"]["blob_prefix"]
    assert prefix.startswith("silver/ko/mx/femsa/data_match_process/qa_process/")
    assert prefix.endswith("/paso1")
    assert first["interrupt"]["qa"]["clientes_restantes"] == 90
    # The step's report goes to the date folder, the rest to the step folder
    extra = first["interrupt"]["extra_destinations"]
    assert extra[0]["destination"] == f"prospecting-data/{prefix.rsplit('/', 1)[0]}"
    assert [Path(f).name for f in extra[0]["files"]] == [
        "qa_process_report.xlsx",
        "qa_process_report.xlsx_metadata.json",
    ]

    loop = cli_resume(app, "t1", {"approved": True})
    assert _kind(loop) == "datamatch_loop"
    new_clients = loop["interrupt"]["new_clients_file"]
    assert new_clients == f"prospecting-data/{prefix}/clients_bottler_femsa_paso1.csv"

    # Another step: the reduced base is the default client file of the next Front step
    again = cli_resume(app, "t1", {"done": False})
    assert _kind(again) == "front_datamatch"
    assert again["interrupt"]["defaults"]["clients_file"] == new_clients

    deps.storage.blobs.append(new_clients.split("/", 1)[1])
    deps.datasets.files.add("data/front/paso2.json")
    second = cli_resume(
        app,
        "t1",
        {"datamatch_file": DATAMATCH_FILE, "step_json": "data/front/paso2.json"},
    )
    second_prefix = second["interrupt"]["defaults"]["blob_prefix"]
    # Same cycle folder (date of the first step) for every step
    assert second_prefix == prefix.rsplit("/", 1)[0] + "/paso2"
    assert second["interrupt"]["qa"]["clientes_inicio"] == 90
    cli_resume(app, "t1", {"approved": True})

    done = cli_resume(app, "t1", {"done": True})
    assert (
        _kind(done) == "confirm_layer_upload" and done["interrupt"]["layer"] == "gold"
    )
    assert len(deps.datamatch_steps.prospects[-1][1]) == 2  # matches of both steps
    state = app.get_state({"configurable": {"thread_id": "t1"}}).values
    assert [h["paso"] for h in state["datamatch_history"]] == ["paso1", "paso2"]


def test_skipping_datamatch_goes_to_priorizacion_on_the_cleaned_csv():
    storage = FakeStorage()
    deps, *_ = make_deps(storage=storage)
    deps.executive_report.with_csv = True
    app = _to_front_datamatch(deps)
    state = app.get_state({"configurable": {"thread_id": "t1"}}).values
    cleaned = Path(_cleaned_dataplor(state)).name  # silver CSV of the executive report

    asked = cli_resume(app, "t1", {"skip": True})

    assert _kind(asked) == "ask_priorizacion"
    steps = {s["step"]: s["status"] for s in asked["steps"]}
    assert steps["fetch_datamatch"] != "done" and steps["stage_prospects"] != "done"
    # No prospects: the input is the silver CSV of the executive report
    assert asked["interrupt"]["defaults"]["input_blob"].endswith(cleaned)
    assert "clientes" in asked["interrupt"]["notes"][0]

    cli_resume(app, "t1", {"run": True})  # priorización -> its sidecars wait
    done = cli_resume(app, "t1", {"approved": True})

    steps = {s["step"]: s["status"] for s in done["steps"]}
    assert steps["upload_priorizacion"] == steps["build_lineage"] == "done"
    # The gold package needs the Datamatch client base: it is not built
    assert steps["stage_gold_package"] != "done"
    assert not deps.gold_package.requests


def test_skip_after_a_datamatch_step_builds_the_prospects():
    deps, *_ = make_deps()
    app = _to_front_datamatch(deps)
    cli_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})
    cli_resume(app, "t1", {"approved": True})  # step 1 -> silver
    again = cli_resume(app, "t1", {"done": False})
    assert _kind(again) == "front_datamatch"

    view = cli_resume(app, "t1", {"skip": True})

    assert (
        _kind(view) == "confirm_layer_upload" and view["interrupt"]["layer"] == "gold"
    )
    assert Path(view["interrupt"]["files"][0]).name.startswith("prospects_")


def test_skip_must_be_true_to_skip_datamatch():
    app = _to_front_datamatch(make_deps()[0])

    view = cli_resume(app, "t1", {"skip": "no"})

    assert _kind(view) == "front_datamatch" and view["interrupt"]["errors"]
