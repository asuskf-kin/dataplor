"""Bronze publishing after the pre-filter: mirror + QA + lineage, ask, upload."""

import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.adapters.brand import KinBrand
from cleaning_agent.adapters.layer_staging import FileLayerStaging
from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.domain.qa import prefilter_qa
from cleaning_agent.domain.warehouse import Layer, layer_prefix
from cleaning_agent.entrypoints.cli import run_resume
from cleaning_agent.settings import PROJECT_ROOT
from tests.fakes import FakeStorage, begin, make_deps

BRAND = KinBrand(PROJECT_ROOT / ".claude/skills/brand-guidelines-kin/assets")


def _to_bronze(
    mode: str, storage: FakeStorage | None = None
) -> tuple[Any, Any, dict[str, Any]]:
    deps, *_ = make_deps(storage=storage)
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", mode)
    run_resume(app, "t1", {})
    view = run_resume(app, "t1", {"approved": True})  # plan
    return app, deps, view


@pytest.mark.parametrize(
    ("mode", "method"),
    [("geojson", "distance"), ("clientes_bottler", "clients_bottler")],
)
def test_prefilter_output_is_staged_for_bronze_with_qa(mode, method):
    _, deps, view = _to_bronze(mode)

    pending = view["interrupt"]
    run_date = deps.staging.metadata[0]["fecha"]
    prefix = f"bronze/ko/mx/femsa/dataplor/{run_date}/{method}"
    name = f"dataplor_{method}_mx_femsa_{run_date}"
    assert pending["kind"] == "confirm_layer_upload" and pending["layer"] == "bronze"
    assert pending["defaults"] == {
        "container": "prospecting-data",
        "blob_prefix": prefix,
    }
    files = [f.replace("\\", "/") for f in pending["files"]]
    assert files == [
        f"data/{prefix}/{name}.parquet",
        f"data/{prefix}/{name}_metadata.json",
        f"data/{prefix}/{name}_qa.html",
    ]
    assert pending["qa"]["filas_eliminadas"] == 6 and pending["qa"]["qa_ok"]
    meta = deps.staging.metadata[0]
    assert (
        meta["analisis"] == method
        and meta["destinos"][0] == f"prospecting-data/{prefix}/{name}.parquet"
    )
    assert meta["origen"] == "data/raw/mx/femsa/part-*.parquet"
    assert [step["etapa"] for step in meta["linaje"]][-1] == "prefilter"


def test_approved_bronze_is_uploaded_then_the_person_goes_to_the_front():
    storage = FakeStorage()
    app, _, view = _to_bronze("geojson", storage)

    view = run_resume(app, "t1", {"approved": True})

    assert len(storage.uploads) == 1
    files, container, prefix = storage.uploads[0]
    assert container == "prospecting-data" and prefix.endswith("/distance")
    assert len(files) == 3
    assert view["interrupt"]["kind"] == "front_dataplor"
    assert view["interrupt"]["bronze_files"][0].startswith(
        "prospecting-data/bronze/ko/mx/femsa/"
    )
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert (
        steps["stage_bronze"]
        == steps["confirm_bronze"]
        == steps["upload_bronze"]
        == "done"
    )


def test_declined_bronze_stops_with_everything_in_the_local_mirror():
    storage = FakeStorage()
    app, _, _ = _to_bronze("geojson", storage)

    view = run_resume(app, "t1", {"approved": False, "note": "reviso el QA"})

    assert storage.uploads == []
    assert view["status"] == "kept_local"
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert (
        steps["confirm_bronze"] == "kept_local" and steps["front_dataplor"] == "not_run"
    )


def test_front_result_from_blob_is_mirrored_and_becomes_the_cleaning_input():
    result = "silver/ko/mx/femsa/20261109/distance/front_result.csv"
    meta = "silver/ko/mx/femsa/20261109/distance/front_result.json"
    storage = FakeStorage(blobs=[result, meta])
    app, deps, _ = _to_bronze("geojson", storage)
    run_resume(app, "t1", {"approved": True})
    deps.datasets.inputs[
        str(Path("data/silver/ko/mx/femsa/20261109/distance/front_result.csv"))
    ] = __import__("tests.fakes", fromlist=["sample_df"]).sample_df()

    view = run_resume(
        app,
        "t1",
        {
            "result_file": f"prospecting-data/{result}",
            "metadata_json": f"prospecting-data/{meta}",
        },
    )

    assert storage.downloads[-2:] == [
        ("prospecting-data", result),
        ("prospecting-data", meta),
    ]
    assert (
        view["interrupt"]["kind"] == "franchise_review"
    )  # modules ran on the Front result
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert steps["front_dataplor"] == steps["fetch_front"] == "done"


def test_front_reasks_when_the_result_is_missing():
    app, _, _ = _to_bronze("geojson", FakeStorage(blobs=[]))
    run_resume(app, "t1", {"approved": True})

    view = run_resume(
        app,
        "t1",
        {
            "result_file": "prospecting-data/silver/x.csv",
            "metadata_json": "prospecting-data/silver/x.json",
        },
    )

    assert view["interrupt"]["kind"] == "front_dataplor"
    assert (
        view["interrupt"]["errors"][0]
        == "result_file: no blob matches prospecting-data/silver/x.csv"
    )


def test_bronze_upload_needs_configured_azure():
    app, _, _ = _to_bronze("geojson", FakeStorage(configured=False))

    view = run_resume(app, "t1", {"approved": True})

    assert view["interrupt"]["kind"] == "confirm_layer_upload"
    assert "Azure is not configured" in view["interrupt"]["errors"][0]


def test_prefilter_qa_counts_and_checks():
    counts = {
        "rows_read": 10,
        "invalid_coordinates": 1,
        "dropped_by_status": 2,
        "outside_territory": 3,
        "inside_territory": 4,
    }

    qa = prefilter_qa(counts, rows_written=4)

    assert qa["filas_eliminadas"] == 6 and qa["pct_eliminado"] == 60.0
    assert qa["eliminadas_por_motivo"]["Fuera del territorio (GeoJSON)"] == 3
    assert qa["qa_ok"]
    assert not prefilter_qa(counts, rows_written=3)["qa_ok"]
    assert not prefilter_qa({**counts, "rows_read": 11}, rows_written=4)["qa_ok"]


def test_layer_prefix_follows_the_prod_layout():
    assert (
        layer_prefix(Layer.BRONZE, "AR", "Andina", "20261109")
        == "bronze/ko/ar/andina/dataplor/20261109"
    )
    with pytest.raises(ValueError):
        layer_prefix(Layer.BRONZE, "ar", "andina", "2026-11-09")
    with pytest.raises(ValueError):
        layer_prefix(Layer.BRONZE, "ar", "../x", "20261109")


def test_file_staging_mirrors_counts_and_writes_qa(tmp_path: Path):
    source = tmp_path / "out.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    staging = FileLayerStaging(BRAND)
    target = tmp_path / "data/bronze/ko/ar/andina/20261109/distance/x.csv"

    mirrored = staging.mirror(str(source), target)
    rows = staging.count_rows(mirrored)
    meta = {
        "archivo": "x.csv",
        "capa": "bronze",
        "origen": ["dataplorraw/a.parquet"],
        "qa": prefilter_qa({"rows_read": 2, "inside_territory": 2}, rows),
        "linaje": [],
    }
    json_path, html_path = staging.write_sidecars(
        meta, target.with_name("x_metadata.json"), target.with_name("x_qa.html")
    )

    assert rows == 2 and Path(mirrored).read_text() == source.read_text()
    assert json.loads(Path(json_path).read_text(encoding="utf-8"))["origen"] == [
        "dataplorraw/a.parquet"
    ]
    page = Path(html_path).read_text(encoding="utf-8")
    assert "dataplorraw/a.parquet" in page and "<script" not in page
    # On-brand: fonts embedded, tokens, logo from file; no CDN, no raw hex colors
    assert "font/woff2;base64" in page and "--ka-color-yellow" in page
    assert "data:image/svg+xml;base64" in page and "kinanalytics.com" in page
    assert "fonts.googleapis" not in page


def test_metadata_follows_the_guideline_keys():
    _, deps, _ = _to_bronze("geojson")

    meta = deps.staging.metadata[0]

    assert meta["#"] == {"total": 10, "utiles": 4}
    assert meta["% datos utiles"] == 40.0
    assert meta["por que se limpiaron"]["Fuera del territorio (GeoJSON)"] == 3
    assert meta["analisis"] == "distance" and meta["alertas"] == []
    assert "POR VERIFICAR" in meta


def test_failed_qa_stops_before_uploading():
    deps, *_ = make_deps()
    deps.staging.rows = 3  # file rows do not match the kept rows
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})

    view = run_resume(app, "t1", {"approved": True})  # plan -> prefilter -> stage

    assert view["status"] == "failed"
    assert "QA de bronze falló" in view["error"]


def test_existing_blob_is_only_replaced_with_explicit_permission():
    storage = FakeStorage()
    app, _, view = _to_bronze("geojson", storage)
    name = Path(view["interrupt"]["files"][0]).name
    storage.existing = [name]

    view = run_resume(app, "t1", {"approved": True})
    assert view["interrupt"]["kind"] == "confirm_layer_upload"
    assert "replace: true" in view["interrupt"]["errors"][0]
    assert storage.uploads == []

    view = run_resume(app, "t1", {"approved": True, "replace": True})

    assert len(storage.uploads) == 1
    assert view["interrupt"]["kind"] == "front_dataplor"


def test_csv_is_converted_to_parquet_in_the_mirror(tmp_path: Path):
    import polars as pl

    source = tmp_path / "out.csv"
    source.write_text(
        "dataplor_id,latitude" + chr(10) + "a,-34.6" + chr(10) + "b,-34.7" + chr(10),
        encoding="utf-8",
    )
    target = tmp_path / "bronze" / "x.parquet"

    FileLayerStaging(BRAND).mirror(str(source), target)

    table = pl.read_parquet(target)
    assert (
        table.height == 2 and table["latitude"].dtype == pl.String
    )  # text kept as text
    assert FileLayerStaging(BRAND).count_rows(str(target)) == 2


def test_a_copy_goes_inside_the_raw_folder_under_method_and_date():
    from cleaning_agent.application.graph.warehouse_nodes import _raw_copy_targets

    deps, *_ = make_deps()
    raw = "dataplorraw/dataplor_raw_parquet/2026-10-15_ar.csv.parquet/part-00000-x.snappy.parquet"

    targets = _raw_copy_targets(
        deps,
        {"intake": {"dataplor_raw": raw}, "mode": "geojson", "run_date": "20261109"},
    )

    assert targets == [
        {
            "container": "dataplorraw",
            "blob_prefix": "dataplor_raw_parquet/2026-10-15_ar.csv.parquet/distance/20261109",
        }
    ]
    assert (
        _raw_copy_targets(deps, {"intake": {"dataplor_raw": "data/raw/x.parquet"}})
        == []
    )


def test_front_paths_without_container_default_to_prospection_datacleaning():
    result = "andina_ARG_20261110/dataplor_cleaned/dataplor_cleaned_2.csv"
    meta = "andina_ARG_20261110/dataplor_cleaned/json_config.json"
    storage = FakeStorage(blobs=[result, meta])
    app, _, _ = _to_bronze("geojson", storage)
    view = run_resume(app, "t1", {"approved": True})
    assert view["interrupt"]["default_container"] == "prospection-datacleaning"

    run_resume(app, "t1", {"result_file": result, "metadata_json": meta})

    assert storage.downloads[-2:] == [
        ("prospection-datacleaning", result),
        ("prospection-datacleaning", meta),
    ]
