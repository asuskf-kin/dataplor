"""Franchise review (Claude Code at an interrupt) and the person's removal decision."""

from typing import Any

import polars as pl
from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.domain.franchises import mark_franchises
from cleaning_agent.entrypoints.cli import run_resume
from tests.fakes import PATHS, RAW, FakeDatasets, begin, make_deps, sample_df

V2 = PATHS["output_csv"].replace(".csv", "_v2.csv")
WITHOUT = PATHS["output_csv"].replace(".csv", "_sin_franquicias.csv")


def _to_review() -> tuple[Any, FakeDatasets, dict[str, Any]]:
    deps, datasets, *_ = make_deps()
    datasets.inputs[RAW] = sample_df()
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    view = run_resume(app, "t1", {"approved": True, "modules": [2]})  # plan -> Front
    view = run_resume(
        app,
        "t1",
        {
            "result_file": "data/front/dataplor_front_result.csv",
            "metadata_json": "data/front/dataplor_front_result.json",
        },
    )
    return app, datasets, view


def test_review_gets_the_distinct_names_with_counts():
    _, datasets, view = _to_review()

    assert view["interrupt"]["kind"] == "franchise_review"
    candidates = datasets.published[view["interrupt"]["candidates_file"]]
    assert set(candidates.columns) == {"name", "registros"}
    assert "OXXO" in view["interrupt"]["question"]


def test_no_franchise_left_goes_to_the_output_approval():
    app, datasets, _ = _to_review()

    view = run_resume(app, "t1", {"flagged": []})
    assert view["interrupt"]["kind"] == "confirm_layer_upload"
    run_resume(app, "t1", {"approved": True})

    assert V2 not in datasets.published and WITHOUT not in datasets.published


def test_marked_franchises_are_kept_with_marks_when_not_removed():
    app, datasets, _ = _to_review()

    view = run_resume(app, "t1", {"flagged": [{"name": "OXXO", "marca": "OXXO"}]})
    assert view["interrupt"]["kind"] == "confirm_franchises"
    assert view["interrupt"]["by_brand"] == {"OXXO": 1}
    run_resume(app, "t1", {"remove": False})
    run_resume(app, "t1", {"approved": True})

    out = datasets.published[PATHS["output_csv"]]
    assert out.filter(pl.col("es_franquicia") == "Sí")[
        "franquicia_marca"
    ].to_list() == ["OXXO"]
    assert V2 in datasets.published and WITHOUT not in datasets.published


def test_removed_franchises_produce_the_sin_franquicias_deliverable():
    app, datasets, _ = _to_review()
    run_resume(app, "t1", {"flagged": [{"name": "OXXO", "marca": "OXXO"}]})
    run_resume(app, "t1", {"remove": True})

    view = run_resume(app, "t1", {"approved": True})

    assert (
        datasets.published[WITHOUT].height
        == datasets.published[PATHS["output_csv"]].height - 1
    )
    assert "07_franchise_review" in datasets.drops
    assert view["interrupt"]["kind"] == "front_datamatch"


def test_mark_franchises_never_deletes():
    df = pl.DataFrame({"name": ["OXXO", "TIENDA"]})

    marked = mark_franchises(df, {"OXXO": "OXXO"})

    assert marked.height == 2
    assert marked["es_franquicia"].to_list() == ["Sí", "No"]
    assert marked["franquicia_marca"].to_list() == ["OXXO", ""]
