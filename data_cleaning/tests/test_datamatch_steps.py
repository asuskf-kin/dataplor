"""Datamatch loop step: drop matched clients, stage files and the on-brand Excel."""

import json
from pathlib import Path

import polars as pl
import pytest
from openpyxl import load_workbook

from cleaning_agent.adapters.brand import (
    BUNDLED_ASSETS_DIR,
    FONT_BODY_FAMILY,
    FONT_DISPLAY_FAMILY,
    KinBrand,
)
from cleaning_agent.adapters.datamatch_steps import (
    DatamatchStepError,
    FileDatamatchSteps,
)
from cleaning_agent.domain.datamatch_steps import (
    KNOWN_CLIENT_REASON,
    matched_rows,
    prospects_qa,
    remaining_clients,
    score_bins,
    step_folder,
    step_summary,
)
from cleaning_agent.domain.models import DatamatchInputs

BRAND = KinBrand(BUNDLED_ASSETS_DIR)
# Synthetic data only: fake ids and names
DATAMATCH = pl.DataFrame(
    {
        "id.c": ["c1", "c2", "c3", "c4"],
        "name.c": [
            "Tienda Ficticia 1",
            "Tienda Ficticia 2",
            "Tienda Ficticia 3",
            "Tienda Ficticia 4",
        ],
        "id.o": ["d1", None, "d3", "d4"],
        "total_score": ["0.71", None, "0.50", "0.56"],
    }
)
CLIENTS = pl.DataFrame(
    {
        "pos_id": ["c1", "c2", "c3", "c4"],
        "pos_name": [
            "Tienda Ficticia 1",
            "Tienda Ficticia 2",
            "Tienda Ficticia 3",
            "Tienda Ficticia 4",
        ],
        "pos_latitude": ["-31.1", "-31.2", "-31.3", "-31.4"],
    }
)


def test_only_scores_strictly_above_the_threshold_are_matches():
    matched = matched_rows(DATAMATCH, "total_score", 0.5)

    assert matched["id.c"].to_list() == ["c1", "c4"]  # 0.50 is not "mayor 0.5"
    kept = remaining_clients(CLIENTS, "pos_id", matched["id.c"])
    assert kept["pos_id"].to_list() == ["c2", "c3"]
    summary = step_summary(CLIENTS.height, matched, kept.height, "total_score", 0.5)
    assert summary["cuadra"] and summary["pct_encontrado"] == 50.0
    assert summary["score_min"] == 0.56 and summary["score_max"] == 0.71


def test_step_folder_comes_from_the_json_name():
    assert step_folder("C:\\Users\\x\\Downloads\\Paso 1.json", 1) == "paso_1"
    assert step_folder("silver/ko/ar/paso2.json", 2) == "paso2"
    assert step_folder("", 3) == "paso3"


def test_score_bins_group_matches_by_band():
    bins = score_bins(pl.Series(["0.51", "0.54", "0.71", None]))

    assert [(b["desde"], b["matches"]) for b in bins] == [(0.5, 2), (0.7, 1)]


@pytest.fixture
def step_inputs(tmp_path: Path) -> DatamatchInputs:
    DATAMATCH.write_csv(tmp_path / "final_output.csv")
    CLIENTS.write_csv(tmp_path / "clientes.csv")
    (tmp_path / "paso1.json").write_text(
        json.dumps(
            {
                "client": {"columns": {"id": "pos_id"}},
                "parameters": {"threshold": 0.54},
                "slack": {"person_in_charge": "Persona Ficticia"},
            }
        ),
        encoding="utf-8",
    )
    return DatamatchInputs(
        datamatch_file="final_output.csv",
        clients_file="clientes.csv",
        client_name="andina",
        step_json="paso1.json",
    )


def test_adapter_writes_reduced_base_matches_json_and_branded_excel(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    out = (
        tmp_path
        / "data/silver/ko/ar/andina/data_match_process/qa_process/20261109/paso1"
    )

    result = FileDatamatchSteps(tmp_path, BRAND).run(
        step_inputs, out, out.parent, "paso1", 0.5, [], "cid-1"
    )

    names = [Path(f).name for f in result.files]
    assert names == [
        "clients_bottler_andina_paso1.csv",
        "datamatch_matches_andina_paso1.csv",
        "paso1.json",
        "qa_process_report_andina.xlsx",
    ]
    kept = pl.read_csv(out / names[0], infer_schema=False)
    assert kept.columns == CLIENTS.columns and kept["pos_id"].to_list() == ["c2", "c3"]
    assert result.summary["umbral_front"] == 0.54

    assert Path(result.files[3]).parent == out.parent  # report in the date folder
    wb = load_workbook(out.parent / names[3])
    assert wb.sheetnames == [
        "Resumen",
        "Historial",
        "Distribucion score",
        "Parametros Front",
        "Matches",
    ]
    cells = [
        str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value
    ]
    # Identifiers only: no client names, coordinates or the person in charge
    assert not any("Ficticia" in c or "-31." in c for c in cells)
    fonts = {c.font.name for ws in wb for row in ws.iter_rows() for c in row if c.value}
    assert fonts <= {FONT_DISPLAY_FAMILY, FONT_BODY_FAMILY}
    yellow = BRAND.color("ka-color-yellow").lstrip("#")
    fills = {c.fill.fgColor.rgb for row in wb["Resumen"].iter_rows() for c in row}
    assert any(str(f).endswith(yellow) for f in fills)


def test_missing_client_id_column_stops_the_step(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    CLIENTS.rename({"pos_id": "ID"}).write_csv(tmp_path / "clientes.csv")

    with pytest.raises(DatamatchStepError, match="client base has no column"):
        FileDatamatchSteps(tmp_path, BRAND).run(
            step_inputs, tmp_path / "out", tmp_path, "paso1", 0.5, [], "cid-1"
        )


def test_second_step_rewrites_one_cycle_report_with_both_steps(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    root = tmp_path / "data/silver/ko/ar/andina/data_match_process/qa_process/20261109"
    steps = FileDatamatchSteps(tmp_path, BRAND)
    first = steps.run(step_inputs, root / "paso1", root, "paso1", 0.5, [], "cid-1")
    # Step 2 runs on the reduced base, with a Datamatch result that finds c3
    pl.DataFrame(
        {"id.c": ["c2", "c3"], "id.o": [None, "d9"], "total_score": [None, "0.8"]}
    ).write_csv(tmp_path / "final_output_2.csv")
    second_inputs = step_inputs.model_copy(
        update={
            "datamatch_file": "final_output_2.csv",
            "clients_file": first.clients_file,
            "step_json": "",
        }
    )

    second = steps.run(
        second_inputs, root / "paso2", root, "paso2", 0.5, [first.summary], "cid-1"
    )

    assert (
        Path(second.files[-1])
        == Path(first.files[-1])
        == root / "qa_process_report_andina.xlsx"
    )
    assert (
        second.summary["clientes_inicio"] == 2
        and second.summary["clientes_restantes"] == 1
    )
    wb = load_workbook(root / "qa_process_report_andina.xlsx")
    steps_in_history = [
        r[0] for r in wb["Historial"].iter_rows(min_row=6, values_only=True) if r[0]
    ]
    assert steps_in_history == ["paso1", "paso2"]
    matched_steps = [
        r[0] for r in wb["Matches"].iter_rows(min_row=6, values_only=True) if r[0]
    ]
    assert matched_steps == ["paso1", "paso1", "paso2"]


def test_prospects_drop_the_dataplor_points_already_matched(tmp_path: Path):
    cleaned = pl.DataFrame(
        {"dataplor_id": ["d1", "d2", "d3", "d4"], "name": ["a", "b", "c", "d"]}
    )
    cleaned.write_csv(tmp_path / "cleaned.csv")
    pl.DataFrame({"id.c": ["c1", "c4"], "id.o": ["d1", "d4"]}).write_csv(
        tmp_path / "m1.csv"
    )
    pl.DataFrame({"id.c": ["c3"], "id.o": ["d3"]}).write_csv(tmp_path / "m2.csv")

    result = FileDatamatchSteps(tmp_path, BRAND).build_prospects(
        "cleaned.csv", ["m1.csv", "m2.csv"], tmp_path / "gold/prospects.csv"
    )

    assert (
        result.rows_in,
        result.known_ids,
        result.known_in_file,
        result.rows_out,
    ) == (4, 3, 3, 1)
    prospects = pl.read_csv(tmp_path / "gold/prospects.csv", infer_schema=False)
    assert (
        prospects["dataplor_id"].to_list() == ["d2"]
        and prospects.columns == cleaned.columns
    )
    qa = prospects_qa(
        result.rows_in, result.known_ids, result.known_in_file, result.rows_out
    )
    assert qa["qa_ok"] and qa["eliminadas_por_motivo"] == {KNOWN_CLIENT_REASON: 3}


def test_prospects_qa_fails_when_a_matched_point_is_missing_from_the_file():
    qa = prospects_qa(rows_in=4, known_ids=3, known_in_file=2, rows_out=2)

    assert not qa["qa_ok"]
    assert [c["ok"] for c in qa["checks"]] == [True, False, True]
