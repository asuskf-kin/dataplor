"""Silver: the cleaned result (franchise review applied) is validated before upload."""

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.domain.qa import FRANCHISE_REASON, pipeline_qa
from cleaning_agent.domain.warehouse import pdv_label
from cleaning_agent.entrypoints.cli import run_resume
from tests.fakes import RAW, begin, make_deps, sample_df


def _to_silver(
    flagged: list[dict[str, str]], remove: bool
) -> tuple[Any, Any, dict[str, Any]]:
    deps, datasets, *_ = make_deps()
    datasets.inputs[RAW] = sample_df()
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True, "modules": [2]})
    run_resume(
        app,
        "t1",
        {
            "result_file": "data/front/dataplor_front_result.csv",
            "metadata_json": "data/front/dataplor_front_result.json",
        },
    )
    view = run_resume(app, "t1", {"flagged": flagged})
    if flagged:
        view = run_resume(app, "t1", {"remove": remove})
    return app, deps, view


def test_silver_path_has_no_method_folder_and_shows_the_qa():
    _, deps, view = _to_silver([], remove=False)

    pending = view["interrupt"]
    run_date = deps.staging.metadata[-1]["fecha"]
    assert pending["kind"] == "confirm_layer_upload" and pending["layer"] == "silver"
    assert (
        pending["defaults"]["blob_prefix"] == f"silver/ko/mx/femsa/dataplor/{run_date}"
    )
    assert [f.replace("\\", "/").rsplit("/", 1)[-1] for f in pending["files"]] == [
        f"pdv_trad_on_mx_femsa_{run_date}.parquet",
        f"pdv_trad_on_mx_femsa_{run_date}_metadata.json",
        f"pdv_trad_on_mx_femsa_{run_date}_qa.html",
    ]
    assert pending["destinations"] == [
        f"prospecting-data/silver/ko/mx/femsa/dataplor/{run_date}"
    ]
    assert pending["qa"]["qa_ok"]


def test_removed_franchises_are_counted_in_the_silver_metadata():
    _, deps, view = _to_silver([{"name": "OXXO", "marca": "OXXO"}], remove=True)

    meta = deps.staging.metadata[-1]
    assert meta["franquicias"] == {
        "marcadas": 1,
        "eliminadas": 1,
        "por_marca": {"OXXO": 1},
    }
    assert meta["por que se limpiaron"][FRANCHISE_REASON] == 1
    assert meta["origen"] == "data/front/dataplor_front_result.csv"
    assert meta["insumos"] == ["data/front/dataplor_front_result.json"]
    assert view["interrupt"]["qa"]["filas_conservadas"] == meta["#"]["utiles"]


def test_silver_qa_fails_when_the_file_rows_do_not_match():
    qa = pipeline_qa(
        10, [{"module": "M2", "dropped": 3}], franchises_removed=2, rows_written=4
    )

    assert qa["filas_conservadas"] == 5 and not qa["qa_ok"]
    assert pipeline_qa(10, [{"module": "M2", "dropped": 3}], 2, rows_written=5)["qa_ok"]


def test_pdv_label_names_the_kept_channel_and_premise():
    assert pdv_label("tradicional", "on_premise") == "pdv_trad_on"
    assert pdv_label("moderno", "ambos") == "pdv_mod_on_off"
    assert pdv_label(None, "off_premise") == "pdv_off"


def test_report_files_go_to_silver_and_the_excel_is_copied_to_gold():
    deps, datasets, *_ = make_deps()
    datasets.inputs[RAW] = sample_df()
    deps.executive_report.with_xlsx = True
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True, "modules": [2]})
    run_resume(
        app,
        "t1",
        {
            "result_file": "data/front/dataplor_front_result.csv",
            "metadata_json": "data/front/dataplor_front_result.json",
        },
    )
    silver = run_resume(app, "t1", {"flagged": []})["interrupt"]
    run_date = deps.staging.metadata[-1]["fecha"]
    silver_dir = Path(f"data/silver/ko/mx/femsa/dataplor/{run_date}")
    assert all(Path(f).parent == silver_dir for f in silver["report_files"])
    deps.staging.on_disk["silver"] = [
        str(silver_dir / "reporte_mx_Femsa_metadata.json")
    ]

    gold = run_resume(app, "t1", {"approved": True})["interrupt"]

    gold_dir = Path(f"data/gold/ko/mx/femsa/dataplor/{run_date}")
    assert gold["kind"] == "confirm_layer_upload" and gold["layer"] == "gold"
    assert [Path(f) for f in gold["files"]] == [
        gold_dir / "reporte_mx_Femsa.xlsx",
        gold_dir / "reporte_mx_Femsa_metadata.json",
    ]
    assert gold["destinations"] == [
        f"prospecting-data/gold/ko/mx/femsa/dataplor/{run_date}"
    ]
