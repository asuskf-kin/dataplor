"""Rules added on 2026-11-23: Airbnb as cleaning module 7, paso 0, the territory of the
bottler in the client validation and the 16-field registro de prospección."""

import json
from pathlib import Path

import openpyxl
import pandas as pd
import polars as pl

from cleaning_agent.adapters.clients_bottler import (
    OUTSIDE_TERRITORY,
    TERRITORY_COL,
    ChannelRule,
    Territory,
    clean_client_file,
)
from cleaning_agent.adapters.executive_report_builder import (
    AIRBNB_PIPELINE_STEP,
    generate_executive_report,
)
from cleaning_agent.domain.cleaning.lodging_filter import remove_lodging_rentals
from cleaning_agent.domain.datamatch_steps import LODGING_REASON
from cleaning_agent.domain.registry import (
    REGISTRY_FIELDS,
    TO_COMPLETE,
    date_in_path,
    prospection_registry,
)
from cleaning_agent.domain.upstream import paso0_counts
from tests.test_brand import BRAND
from tests.test_clients_bottler import BRAND as BRAND_ASSETS
from tests.test_clients_bottler import _geojson, _square


def test_module_7_drops_rentals_only_inside_lodging() -> None:
    df = pl.DataFrame(
        {
            "dataplor_id": ["a", "b", "c", "d"],
            "name": ["Airbnb Centro", "Departamento de Geología", "Hotel Sol", "Depto 3B"],
            "sub_category": ["lodging", "university", "lodging", "lodging"],
        }
    )
    kept, _, _, dropped = remove_lodging_rentals(df, [])
    assert kept.get_column("dataplor_id").to_list() == ["b", "c"]
    assert dropped.get_column("dataplor_id").to_list() == ["a", "d"]
    assert set(dropped.get_column("drop_reason")) == {LODGING_REASON}
    assert dropped.get_column("drop_match").to_list() == ["airbnb", "depto"]
    none_kept, _, _, none = remove_lodging_rentals(df.filter(pl.col("dataplor_id") == "c"), [])
    assert none_kept.height == 1 and none.height == 0


def _report_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    raw = pd.DataFrame(
        {
            "dataplor_id": [f"p{i}" for i in range(6)],
            "name": ["Bar Uno", "Airbnb Playa", "Bar Dos", "Depto Sur", "Bar Tres", "Bar 4"],
            "business_category": ["bar", "lodging", "bar", "lodging", "bar", "bar"],
            "main_category": "x",
            "city": "C",
            "state": "S",
            "channel_cat": "On Premise",
        }
    )
    raw_csv, out_csv = tmp_path / "raw.csv", tmp_path / "out.csv"
    raw.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    raw[~raw["dataplor_id"].isin(["p1", "p3"])].to_csv(out_csv, index=False, encoding="utf-8-sig")
    dropped = tmp_path / "dropped"
    dropped.mkdir()
    pd.DataFrame(
        {
            "dataplor_id": ["p1", "p3"],
            "name": ["Airbnb Playa", "Depto Sur"],
            "drop_reason": LODGING_REASON,
            "drop_match": ["airbnb", "depto"],
        }
    ).to_csv(dropped / "07_airbnb_lodging_removed.csv", index=False, encoding="utf-8-sig")
    return raw_csv, out_csv, dropped


def test_report_has_paso_0_and_an_airbnb_sheet(tmp_path: Path) -> None:
    raw_csv, out_csv, dropped = _report_inputs(tmp_path)
    upstream = paso0_counts({"rows_read": 100, "inside_territory": 40}, 6)
    result = generate_executive_report(
        raw_csv,
        out_csv,
        dropped,
        tmp_path / "rep",
        country="ar",
        bottler="andina",
        run_date="20261123_000000",
        apply_manual_deletions=False,
        brand=BRAND,
        upstream=upstream,
    )
    s = result.summary
    assert s["drops_step_07"] == 2 and s["reconciliation_gap"] == 0
    assert s["paso0: Eliminados en el Front"] == 34
    html = next(f for f in result.files if f.suffix == ".html").read_text("utf-8")
    assert "Paso 0" in html and AIRBNB_PIPELINE_STEP in html
    assert AIRBNB_PIPELINE_STEP.startswith("8 · ")
    xlsx = next(f for f in result.files if f.suffix == ".xlsx")
    wb = openpyxl.load_workbook(xlsx)
    assert "Airbnb" in wb.sheetnames
    rows = list(wb["Airbnb"].iter_rows(values_only=True))
    assert rows[0][0] == "Palabra" and len(rows) == 3
    summary_labels = [r[0] for r in wb["Resumen"].iter_rows(values_only=True)]
    assert "Paso 0 · Dataplor raw (filas leídas)" in summary_labels


def test_paso0_counts_by_mode() -> None:
    assert paso0_counts({"rows_read": 100, "inside_territory": 40}, 30) == [
        ("Dataplor raw (filas leídas)", 100),
        ("Quitados antes del Front (estado, coordenadas, fuera del territorio)", 60),
        ("Enviados al Front (bronze)", 40),
        ("Eliminados en el Front", 10),
        ("Recibidos del Front (universo del pipeline)", 30),
    ]
    # clientes_bottler mode keeps near_client; no prefilter = raw goes as it is
    assert ("Enviados al Front (bronze)", 7) in paso0_counts({"rows_read": 9, "near_client": 7}, 5)
    assert paso0_counts(None, 5) == [("Recibidos del Front (universo del pipeline)", 5)]
    assert paso0_counts(None, None) == []


def test_registry_has_the_16_fields_in_order() -> None:
    reg = prospection_registry(
        run_date="20261123",
        iteration=4,
        total_prospects=40595,
        high_moderate=16613,
        categories=[("restaurant", 3212), ("hotel", 2118)],
        clients_master_date=date_in_path("drop_zone/ko/ar/andina/clients_bottler/20261020/x.csv"),
        responsible="",
        client_channel="todos",
        dataplor_clean="prospecting-data/silver/x.csv",
        datamatch=["prospecting-data/silver/run_4/final_output.csv"],
        dataplor_used="dataplorraw/x.parquet",
        raw_clients="prospecting-data/drop_zone/x.csv",
        azure_results="prospecting-data/gold/ko/ar/andina/prospecting-data/20261123",
        comments=[],
        registered_by="",
        registered_at="2026-11-23",
    )
    assert tuple(reg) == REGISTRY_FIELDS and len(reg) == 16
    assert reg["Fecha Maestra Clientes (Prosp.)"] == "20261020"
    assert reg["Top Categorías Negocio (Prosp.)"] == "restaurant (3.212), hotel (2.118)"
    assert reg["Responsable Prospección"] == TO_COMPLETE
    assert reg["Comentarios (Prosp.)"] == ""


def test_clients_are_crossed_with_the_bottler_territory(tmp_path: Path) -> None:
    country = _geojson(tmp_path / "adm0.geojson", _square(-40, -30, -65, -55, "País"))
    # The bottler works in the north half only; its GeoJSON has no name property
    territory = tmp_path / "Argentina_Test.geojson"
    feature = _square(-35, -30, -65, -55, "")
    feature["properties"] = {}
    _geojson(territory, feature)
    src = tmp_path / "clientes.csv"
    src.write_text(
        "pos_id,pos_name,pos_channel,pos_latitude,pos_longitude\n"
        "001,A,TRADICIONAL,-34.600,-58.400\n"
        "002,B,TRADICIONAL,-34.610,-58.410\n"
        "003,C,TRADICIONAL,-36.620,-58.420\n"
        "004,D,TRADICIONAL,-36.630,-58.430\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    summary = clean_client_file(
        src, out, "clientes_todos_validos",
        Territory(country=country, divisions={}),
        ChannelRule("pos_channel", "todos", None),
        "run-test", BRAND_ASSETS, "ar", "test", "Argentina",
        bottler_territory=territory,
    )
    clean = pl.read_csv(out / "clientes_todos_validos.csv", infer_schema_length=0)
    labels = clean.get_column(TERRITORY_COL).to_list()
    assert labels.count(OUTSIDE_TERRITORY) == 2 and labels.count("Dentro del territorio") == 2
    assert summary["fuera_del_territorio_bottler"] == 2
    meta = json.loads((out / "clientes_todos_validos_metadata.json").read_text("utf-8"))
    assert meta["territorio"]["bottler"]["archivo"] == "Argentina_Test.geojson"
    assert clean.height == 4  # marked, never removed


def test_the_8_cleaning_steps_are_on_by_default() -> None:
    from cleaning_agent.application.cleaning_catalog import build_module_plan
    from cleaning_agent.settings import AGENT_SETTINGS

    modules, notes = build_module_plan([int(m) for m in AGENT_SETTINGS["default_modules"]])
    assert modules == [1, 2, 3, 4, 5, 6, 7] and notes == []


def test_lineage_keeps_the_layer_sidecar_and_its_vtm(tmp_path: Path) -> None:
    from cleaning_agent.adapters.lineage import STAGE_KEY, FileLineage
    from cleaning_agent.domain.lineage import StageRecord

    out = tmp_path / "gold.csv"
    out.write_text("poi_ref\n1\n", encoding="utf-8")
    sidecar = tmp_path / "gold_metadata.json"
    sidecar.write_text(json.dumps({"capa": "gold", "vtm": {"Total Prospectar": 1}}), "utf-8")
    lineage = FileLineage(tmp_path)
    record = StageRecord(
        run_id="r", stage="stage_gold_package", name="Gold", started_at="a", finished_at="b",
        code_version="x", inputs=[], outputs=[lineage.describe(str(out))], metrics={},
    )
    lineage.write_sidecars(record)
    meta = json.loads(sidecar.read_text("utf-8"))
    assert meta["vtm"] == {"Total Prospectar": 1} and meta["capa"] == "gold"
    assert meta[STAGE_KEY]["stage"] == "stage_gold_package"
    # A file without a layer sidecar still gets the plain lineage one
    other = tmp_path / "other.csv"
    other.write_text("a\n", encoding="utf-8")
    lineage.write_sidecars(record.model_copy(update={"outputs": [lineage.describe(str(other))]}))
    assert json.loads((tmp_path / "other_metadata.json").read_text("utf-8"))["stage"] == "stage_gold_package"
