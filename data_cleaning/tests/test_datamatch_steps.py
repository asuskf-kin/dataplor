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
    LODGING_REASON,
    lodging_rentals,
    lodging_term,
    match_distance_m,
    match_quality,
    matched_rows,
    prospects_qa,
    remaining_clients,
    rows_in_base,
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
        "datamatch_andina_paso1_qa.html",
        "qa_process_report_andina.xlsx",
    ]
    kept = pl.read_csv(out / names[0], infer_schema=False)
    assert kept.columns == CLIENTS.columns and kept["pos_id"].to_list() == ["c2", "c3"]
    assert result.summary["umbral_front"] == 0.54

    assert Path(result.files[4]).parent == out.parent  # report in the date folder
    wb = load_workbook(out.parent / names[4])
    assert wb.sheetnames == [
        "Resumen",
        "Historial",
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


def test_rows_in_base_drops_clients_of_an_older_base():
    base = CLIENTS.filter(pl.col("pos_id") != "c4")

    kept, outside = rows_in_base(DATAMATCH, "id.c", base, "pos_id")

    assert kept["id.c"].to_list() == ["c1", "c2", "c3"] and outside == 1
    kept, outside = rows_in_base(DATAMATCH, "id.c", CLIENTS, "pos_id")
    assert kept.height == DATAMATCH.height and outside == 0


def test_front_run_with_an_older_base_stops_the_step_unless_filtered(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    # The Front matched c4, a client already found in an earlier step
    CLIENTS.filter(pl.col("pos_id") != "c4").write_csv(tmp_path / "clientes.csv")
    steps = FileDatamatchSteps(tmp_path, BRAND)

    with pytest.raises(DatamatchStepError, match="Counts do not add up"):
        steps.run(step_inputs, tmp_path / "a", tmp_path / "ra", "paso1", 0.5, [], "c")

    filtered = step_inputs.model_copy(update={"filtrar_a_base": True})
    result = steps.run(filtered, tmp_path / "b", tmp_path / "rb", "paso1", 0.5, [], "c")

    assert result.summary["cuadra"] and result.summary["clientes_con_match"] == 1
    assert result.summary["clientes_fuera_de_base"] == 1
    assert any("otra base" in a for a in result.summary["calidad"]["alertas"])


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
    assert steps_in_history == ["paso1", "paso2", "Total ciclo"]
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


def test_step_csvs_open_aligned_in_excel(tmp_path: Path, step_inputs: DatamatchInputs):
    """BOM, CRLF and no quoted field: list columns of the Front carry line breaks."""
    DATAMATCH.with_columns(
        pl.Series("res_10_neighbors", ["['a'\n 'b']", "x", "y, z", '"q"'])
    ).write_csv(tmp_path / "final_output.csv")
    out = tmp_path / "paso1"
    result = FileDatamatchSteps(tmp_path, BRAND).run(
        step_inputs, out, tmp_path, "paso1", 0.5, [], "cid-1"
    )
    # Clients and matches: comma, so Sheets and LibreOffice split them right
    for path, sep in zip(result.files[:2], (",", ","), strict=True):
        raw = Path(path).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b'"' not in raw
        lines = raw.decode("utf-8-sig").split("\r\n")
        assert len({line.count(sep) for line in lines if line}) == 1


def test_step_qa_html_has_quality_and_no_client_data(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    DATAMATCH.with_columns(
        pl.Series("latitude.c", ["-31.40000", "-31.4", "-31.4", "-31.40000"]),
        pl.Series("longitude.c", ["-64.2", "-64.2", "-64.2", "-64.2"]),
        pl.Series("latitude.o", ["-31.40018", "-31.4", "-31.4", "-31.40500"]),
        pl.Series("longitude.o", ["-64.2", "-64.2", "-64.2", "-64.2"]),
        pl.Series("name_score", ["0.9", "0", "0", "0.1"]),
        pl.Series("address_score", ["0.2", "0", "0", "0.3"]),
    ).write_csv(tmp_path / "final_output.csv")
    out = tmp_path / "paso1"
    result = FileDatamatchSteps(tmp_path, BRAND).run(
        step_inputs, out, tmp_path, "paso1", 0.5, [], "cid-1"
    )
    page = (out / "datamatch_andina_paso1_qa.html").read_text(encoding="utf-8")
    assert "QA" in page and "OK" in page and "paso1" in page
    assert "Ficticia" not in page and "-31.4" not in page  # names, coords, person
    assert "<script" not in page and "http://" not in page
    quality = result.summary["calidad"]
    assert quality["qa_ok"] and quality["distancia_mediana_m"] is not None
    assert {b["banda"]: b["matches"] for b in quality["por_distancia"]}["≤ 25 m"] == 1
    assert any("250 m" in a for a in quality["alertas"])  # c4 is ~556 m away


def test_match_quality_flags_a_dataplor_point_given_to_two_clients():
    matched = pl.DataFrame(
        {
            "id.c": ["c1", "c2"],
            "id.o": ["d1", "d1"],
            "total_score": ["0.7", "0.9"],
            "latitude.c": ["0", "0"],
            "longitude.c": ["0", "0"],
            "latitude.o": ["0", "0.001"],
            "longitude.o": ["0", "0"],
        }
    )
    distance = match_distance_m(
        matched, "latitude.c", "longitude.c", "latitude.o", "longitude.o"
    )
    assert distance is not None and round(distance[1]) == 111
    quality = match_quality(matched, distance, "id.c", "id.o", "total_score", 0.5)
    assert quality["dataplor_repetidos"] == 1 and not quality["qa_ok"]
    assert match_distance_m(matched.drop("latitude.o"), "a", "b", "c", "d") is None


def _near_far_frame() -> pl.DataFrame:
    """c1 scores high far away; c2 scores low but sits 11 m away; c3 neither."""
    return pl.DataFrame(
        {
            "id.c": ["c1", "c2", "c3"],
            "id.o": ["d1", "d2", "d3"],
            "total_score": ["0.70", "0.30", "0.30"],
            "latitude.c": ["0", "0", "0"],
            "longitude.c": ["0", "0", "0"],
            "latitude.o": ["0.001", "0.0001", "0.001"],
            "longitude.o": ["0", "0", "0"],
            "name_score": ["0.9", "0.1", "0.1"],
            "address_score": ["0.9", "0.1", "0.1"],
        }
    )


def test_distance_rule_adds_close_clients_and_says_why():
    frame = _near_far_frame()
    distance = match_distance_m(frame, "latitude.c", "longitude.c", "latitude.o", "longitude.o")
    matched = matched_rows(frame, "total_score", 0.6, distance, 25, "id.o")

    assert matched["id.c"].to_list() == ["c1", "c2"]
    assert matched["match_por"].to_list() == ["score", "distancia"]
    summary = step_summary(3, matched, 1, "total_score", 0.6, 25)
    assert summary["con_match_por_score"] == 1 and summary["con_match_por_distancia"] == 1
    assert summary["score_min"] == 0.7  # the distance rule does not lower the score range

    quality = match_quality(
        matched,
        match_distance_m(matched, "latitude.c", "longitude.c", "latitude.o", "longitude.o"),
        "id.c",
        "id.o",
        "total_score",
        0.6,
        25,
        pl.Series(["d2"]),
    )
    checks = {c["check"]: c["ok"] for c in quality["checks"]}
    assert checks["Los matches por score están entre el umbral (0.6) y 1"]
    assert checks["Los matches por distancia están a 25 m o menos"]
    assert not checks["Ningún punto Dataplor ya tomado en un paso anterior"]
    assert quality["por_regla"] == {"score": 1, "distancia": 1}


def test_without_the_rule_only_the_score_decides():
    matched = matched_rows(_near_far_frame(), "total_score", 0.6)
    assert matched["id.c"].to_list() == ["c1"] and "match_por" not in matched.columns


def test_step_with_distance_rule_shows_it_in_the_reports(tmp_path: Path):
    _near_far_frame().write_csv(tmp_path / "final_output.csv")
    pl.DataFrame({"pos_id": ["c1", "c2", "c3"]}).write_csv(tmp_path / "clientes.csv")
    inputs = DatamatchInputs(
        datamatch_file="final_output.csv",
        clients_file="clientes.csv",
        client_name="andina",
        distancia_match_m=25,
    )
    out = tmp_path / "paso2"
    result = FileDatamatchSteps(tmp_path, BRAND).run(
        inputs, out, tmp_path, "paso2", 0.6, [], "cid"
    )
    assert result.summary["clientes_restantes"] == 1
    assert result.summary["con_match_por_distancia"] == 1
    qa = (out / "datamatch_andina_paso2_qa.html").read_text(encoding="utf-8")
    assert "regla de distancia" in qa and "¿Por qué regla salió cada cliente?" in qa
    page = (out / "datamatch_andina_paso2_umbral.html").read_text(encoding="utf-8")
    assert "Regla de distancia activa" in page
    cells = [
        str(c.value)
        for ws in load_workbook(tmp_path / "qa_process_report_andina.xlsx")
        for row in ws.iter_rows()
        for c in row
        if c.value
    ]
    assert any("<= 25 m" in c for c in cells)
    matches = pl.read_csv(out / "datamatch_matches_andina_paso2.csv", infer_schema=False, separator=",")
    assert matches["match_por"].to_list() == ["score", "distancia"]


def test_distance_rule_needs_coordinates(tmp_path: Path, step_inputs: DatamatchInputs):
    inputs = step_inputs.model_copy(update={"distancia_match_m": 25})
    with pytest.raises(DatamatchStepError, match="coordinates"):
        FileDatamatchSteps(tmp_path, BRAND).run(inputs, tmp_path / "p", tmp_path, "p", 0.5, [], "c")


def test_distance_only_step_ignores_the_score_and_says_why(tmp_path: Path):
    _near_far_frame().write_csv(tmp_path / "final_output.csv")
    pl.DataFrame({"pos_id": ["c1", "c2", "c3"]}).write_csv(tmp_path / "clientes.csv")
    inputs = DatamatchInputs(
        datamatch_file="final_output.csv",
        clients_file="clientes.csv",
        client_name="andina",
        distancia_match_m=25,
        solo_distancia=True,
    )
    out = tmp_path / "paso2"
    result = FileDatamatchSteps(tmp_path, BRAND).run(
        inputs, out, tmp_path, "paso2", 0.6, [], "cid"
    )
    assert result.summary["clientes_con_match"] == 1  # c1 scores 0.70 but is far
    assert result.summary["solo_distancia"] is True
    matches = pl.read_csv(out / "datamatch_matches_andina_paso2.csv", infer_schema=False, separator=",")
    assert matches["id.c"].to_list() == ["c2"]
    assert matches["causa"].to_list() == ["candidato a 11 m (<= 25 m)"]
    qa = (out / "datamatch_andina_paso2_qa.html").read_text(encoding="utf-8")
    assert "el total_score no decide" in qa


def test_score_matches_carry_their_cause(tmp_path: Path, step_inputs: DatamatchInputs):
    out = tmp_path / "paso1"
    FileDatamatchSteps(tmp_path, BRAND).run(step_inputs, out, tmp_path, "paso1", 0.5, [], "c")
    matches = pl.read_csv(out / "datamatch_matches_andina_paso1.csv", infer_schema=False, separator=",")
    assert matches["causa"].to_list() == ["total_score 0.71 > 0.5", "total_score 0.56 > 0.5"]
    cells = {
        str(c.value)
        for row in load_workbook(tmp_path / "qa_process_report_andina.xlsx")["Matches"].iter_rows()
        for c in row
    }
    assert "causa" in cells and "total_score 0.71 > 0.5" in cells


def test_distance_only_needs_a_distance():
    with pytest.raises(ValueError, match="solo_distancia"):
        DatamatchInputs(
            datamatch_file="a.csv", clients_file="b.csv", client_name="x", solo_distancia=True
        )


def test_cycle_excel_is_the_log_of_every_step(tmp_path: Path, step_inputs: DatamatchInputs):
    """Parameters of all steps side by side; matches say which step and rule took them."""
    adapter = FileDatamatchSteps(tmp_path, BRAND)
    first = adapter.run(step_inputs, tmp_path / "paso1", tmp_path, "paso1", 0.5, [], "c")
    _near_far_frame().write_csv(tmp_path / "final_output_2.csv")
    (tmp_path / "paso2.json").write_text(
        json.dumps({"parameters": {"threshold": 0.3}}), encoding="utf-8"
    )
    pl.DataFrame({"pos_id": ["c1", "c2", "c3"]}).write_csv(tmp_path / "clientes2.csv")
    second = step_inputs.model_copy(
        update={
            "datamatch_file": "final_output_2.csv",
            "clients_file": "clientes2.csv",
            "step_json": "paso2.json",
            "distancia_match_m": 25,
            "solo_distancia": True,
        }
    )
    adapter.run(second, tmp_path / "paso2", tmp_path, "paso2", 0.6, [first.summary], "c")

    wb = load_workbook(tmp_path / "qa_process_report_andina.xlsx")
    assert "Distribucion score" not in wb.sheetnames
    params = [[c.value for c in r] for r in wb["Parametros Front"].iter_rows()]
    assert any(r[:3] == ["Parámetro", "paso1", "paso2"] for r in params)
    assert any(r[:3] == ["parameters.threshold", 0.54, 0.3] for r in params)
    cells = {str(c.value) for r in wb["Matches"].iter_rows() for c in r}
    assert "match paso1 · total_score > 0.5" in cells
    assert "match paso2 · <= 25 m" in cells
    assert "match_por" not in cells


def test_history_says_what_was_done_and_the_focus():
    from cleaning_agent.adapters.datamatch_steps import step_action, step_focus

    assert step_action({"umbral_limpieza": 0.6}) == "Match si total_score > 0.6"
    assert step_action(
        {"umbral_limpieza": 0.6, "distancia_match_m": 25, "solo_distancia": True}
    ).startswith("Solo match a <= 25 m")
    focus = step_focus(
        {
            "parameters": {"position_weight": 0.4, "address_weight": 0.35, "name_weight": 0.1},
            "create_options_by": {"lat_long": "false", "address": "true"},
        }
    )
    assert focus == "Enfoque en cercanía (position 0.4); candidatos por dirección"
    assert step_focus({}) == "—"


def test_summary_has_counts_per_step_and_a_funnel(tmp_path: Path, step_inputs: DatamatchInputs):
    FileDatamatchSteps(tmp_path, BRAND).run(step_inputs, tmp_path / "paso1", tmp_path, "paso1", 0.5, [], "c")
    ws = load_workbook(tmp_path / "qa_process_report_andina.xlsx")["Resumen"]
    cells = {str(v) for r in ws.iter_rows(values_only=True) for v in r if v is not None}
    assert "Cuántos salieron en cada paso" in cells and "Tras paso1" in cells
    assert "Archivos" not in cells and "Siguiente paso" not in cells
    assert len(ws._charts) == 1


def test_lineage_document_carries_the_decisions() -> None:
    from cleaning_agent.domain.lineage import build_lineage_document

    decision = {"etapa": "datamatch_paso2", "decision": "solo distancia", "por_que": "pedido"}
    doc = build_lineage_document([], {"run_id": "r"}, [], [decision])
    assert doc["decisiones"] == [decision]
    assert build_lineage_document([], {"run_id": "r"}, [])["decisiones"] == []


def test_lineage_reads_the_run_decision_log(tmp_path: Path) -> None:
    from cleaning_agent.adapters.lineage import FileLineage

    lineage = FileLineage.__new__(FileLineage)
    assert lineage.read_decisions(tmp_path / "decisiones.json") == []
    (tmp_path / "decisiones.json").write_text('[{"decision": "x"}]', encoding="utf-8")
    assert lineage.read_decisions(tmp_path / "decisiones.json") == [{"decision": "x"}]


def test_prospects_keep_the_step_that_found_each_known_point(tmp_path: Path):
    pl.DataFrame({"dataplor_id": ["d1", "d2", "d3"]}).write_csv(tmp_path / "cleaned.csv")
    for paso, ids in (("paso1", ["d1"]), ("paso2", ["d1", "d3"])):
        (tmp_path / paso).mkdir()
        pl.DataFrame({"id.c": ["c"] * len(ids), "id.o": ids}).write_csv(
            tmp_path / paso / "m.csv"
        )

    result = FileDatamatchSteps(tmp_path, BRAND).build_prospects(
        "cleaned.csv", ["paso1/m.csv", "paso2/m.csv"], tmp_path / "p.csv"
    )

    # A point taken again later keeps the first step that matched it
    assert result.known_points == {"d1": "paso1", "d3": "paso2"}


def test_state_key_reads_every_way_dataplor_writes_a_province():
    from cleaning_agent.domain.datamatch_steps import state_key

    for raw in ("Buenos Aires", "Buenos Aires Province", "buenos aires", "Provincia de Buenos Aires"):
        assert state_key(raw) == "buenos aires"
    assert state_key("Mendoza, Mendoza Province") == "mendoza"
    assert state_key("Córdoba") == state_key("Cordoba") == "cordoba"
    assert state_key(None) == ""


def test_prospects_drop_the_provinces_out_of_territory(tmp_path: Path):
    pl.DataFrame(
        {
            "dataplor_id": ["d1", "d2", "d3", "d4"],
            "state": ["Buenos Aires", "Córdoba", "Buenos Aires Province", None],
        }
    ).write_csv(tmp_path / "cleaned.csv")
    (tmp_path / "paso1").mkdir()
    # d1 is a client and also in Buenos Aires: it counts once, as a client
    pl.DataFrame({"id.c": ["c1"], "id.o": ["d1"]}).write_csv(tmp_path / "paso1/m.csv")

    result = FileDatamatchSteps(tmp_path, BRAND).build_prospects(
        "cleaned.csv", ["paso1/m.csv"], tmp_path / "p.csv", ["Buenos Aires"]
    )

    assert result.out_of_territory == {"d3": "Buenos Aires Province"}
    assert pl.read_csv(tmp_path / "p.csv")["dataplor_id"].to_list() == ["d2", "d4"]
    qa = prospects_qa(
        result.rows_in,
        result.known_ids,
        result.known_in_file,
        result.rows_out,
        len(result.out_of_territory),
        "Buenos Aires",
    )
    assert qa["qa_ok"]
    assert qa["eliminadas_por_motivo"] == {
        KNOWN_CLIENT_REASON: 1,
        "Fuera de territorio (Buenos Aires)": 1,
    }


def test_lodging_rentals_catch_airbnb_and_apartment_variants_in_lodging_only():
    names = [
        "Air BnB Centro",
        "Apartamentos del Sol",
        "Depto Lourdes",
        "Dpto 3",
        "Aparthotel Rosario",
        "Aparts Mendoza",
        "Monoambiente Norte",
        "Departamento de Geologia",  # a university: not lodging
        "Hotel Plaza",  # a hotel stays
        "Apto celiacos",  # "apto" = suitable for
    ]
    frame = pl.DataFrame(
        {
            "name": names,
            "sub_category": ["lodging"] * 7 + ["educational", "lodging", "lodging"],
        }
    )

    assert lodging_rentals(frame).to_list() == [True] * 7 + [False] * 3
    assert lodging_term("Depto Lourdes") == "depto"
    assert lodging_term("Hotel Plaza") == ""


def test_prospects_drop_rentals_after_the_known_clients(tmp_path: Path):
    pl.DataFrame(
        {
            "dataplor_id": ["d1", "d2", "d3"],
            "name": ["Departamento Centro", "Bar Uno", "Apart Sur"],
            "sub_category": ["lodging", "diner", "lodging"],
        }
    ).write_csv(tmp_path / "cleaned.csv")
    pl.DataFrame({"id.c": ["c1"], "id.o": ["d1"]}).write_csv(tmp_path / "m1.csv")

    result = FileDatamatchSteps(tmp_path, BRAND).build_prospects(
        "cleaned.csv", ["m1.csv"], tmp_path / "gold/prospects.csv"
    )

    # d1 is a client first: counted once, as a client
    assert result.lodging_rentals == {"d3": "apart"}
    # The removed rentals are written next to the prospects, Excel-safe
    removed = Path(result.lodging_file)
    assert removed.name == "prospects_eliminados_alojamiento_airbnb.csv"
    raw = removed.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    rows = pl.read_csv(removed, infer_schema=False)
    assert rows["dataplor_id"].to_list() == ["d3"]
    assert rows["termino_regex"].to_list() == ["apart"]
    assert result.rows_out == 1
    qa = prospects_qa(
        result.rows_in,
        result.known_ids,
        result.known_in_file,
        result.rows_out,
        lodging=len(result.lodging_rentals),
    )
    assert qa["qa_ok"]
    assert qa["eliminadas_por_motivo"] == {KNOWN_CLIENT_REASON: 1, LODGING_REASON: 1}


def test_cycle_excel_closes_with_the_rented_flats(
    tmp_path: Path, step_inputs: DatamatchInputs
):
    out = tmp_path / "qa/paso1"
    steps = FileDatamatchSteps(tmp_path, BRAND)
    step = steps.run(step_inputs, out, out.parent, "paso1", 0.5, [], "cid-1")

    files = steps.close_cycle_report(out.parent, "andina", [step.summary], 3, 40)

    ws = load_workbook(files[0])["Resumen"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    closing = next(r for r in rows if "airbnb" in r)
    # Paso, acción, salen, quedan (prospects), % (table starts at column B)
    assert closing[1] == "airbnb" and "Airbnb" in str(closing[2])
    assert closing[3:6] == [3, 40, round(3 / 43 * 100, 2)]
    # The step rows are still there, before the closing row
    assert rows.index(next(r for r in rows if "paso1" in r)) < rows.index(closing)
    # Prospects are Dataplor points, not clients: their own table and their own figure
    heading = next(r for r in rows if any("Después del ciclo" in str(v) for v in r))
    assert rows.index(heading) < rows.index(closing)
    final = next(r for r in rows if any("Prospectos finales" in str(v) for v in r))
    assert 40 in final
    assert any("siguen sin su punto Dataplor" in str(v) for r in rows for v in r)


def test_cycle_excel_is_not_rebuilt_without_steps(tmp_path: Path):
    assert FileDatamatchSteps(tmp_path, BRAND).close_cycle_report(tmp_path, "x", [], 1, 1) == []
