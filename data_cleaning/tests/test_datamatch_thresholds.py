"""Threshold decision page of a Datamatch step (Kin port of QA_datamatch's report)."""

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from cleaning_agent.adapters.brand import BUNDLED_ASSETS_DIR, KinBrand
from cleaning_agent.adapters.datamatch_steps import FileDatamatchSteps
from cleaning_agent.domain.datamatch_thresholds import (
    elbow,
    flat_components,
    kde,
    marginal_thresholds,
    matches_above,
    scenarios,
    score_grid,
    valleys,
)
from cleaning_agent.domain.models import DatamatchInputs

BRAND = KinBrand(BUNDLED_ASSETS_DIR)


def test_two_populations_leave_a_valley_between_them():
    rng = np.random.default_rng(7)
    scores = np.clip(
        np.concatenate([rng.normal(0.35, 0.04, 400), rng.normal(0.8, 0.04, 400)]), 0, 1
    )
    grid = score_grid(scores)
    cuts = valleys(grid, kde(scores, grid))
    assert len(cuts) == 1 and 0.5 < cuts[0] < 0.65


def test_matches_are_strictly_above_and_the_elbow_is_on_the_grid():
    scores = np.array([0.5, 0.6, 0.7, 0.9])
    grid = np.array([0.5, 0.6, 0.7])
    assert matches_above(scores, grid).tolist() == [3, 2, 1]
    assert elbow(grid, matches_above(scores, grid)) in grid.tolist()


def test_scenarios_compare_each_threshold_with_the_current_one():
    scores = np.array([0.3, 0.55, 0.6, 0.9])
    rows = scenarios(
        scores,
        10,
        [("Actual", 0.5, "config"), ("Alto", 0.7, "x"), ("Nada", None, "y")],
        0.5,
        np.array([10.0, 20.0, 30.0, 40.0]),
        np.array([True, True, False, False]),
    )
    assert [r["umbral"] for r in rows] == [0.7, 0.5]
    high = rows[0]
    assert high["matches"] == 1 and high["delta_vs_actual"] == -2
    assert high["pct_base"] == 10.0 and high["distancia_mediana_m"] == 40.0
    assert rows[1]["pct_solo_cercania"] == 33.3


def test_marginal_thresholds_stop_at_the_front_threshold():
    assert marginal_thresholds(0.24)[-1] == 0.25
    assert marginal_thresholds(None)[0] == 0.95 and marginal_thresholds(None)[-1] == 0.4


def test_a_flat_component_is_flagged():
    frame = pl.DataFrame({"address_score": ["0", "0"], "name_score": ["0.1", "0.9"]})
    assert flat_components(frame) == [
        "address_score siempre 0.00: no discrimina y el total_score queda acotado por su peso."
    ]


def test_step_writes_the_threshold_page_but_does_not_upload_it(tmp_path: Path):
    rng = np.random.default_rng(1)
    n = 60
    pl.DataFrame(
        {
            "id.c": [f"c{i}" for i in range(n)],
            "name.c": [f"Cliente Ficticio {i}" for i in range(n)],
            "id.o": [f"d{i}" for i in range(n)],
            "name.o": [f"Lugar Ficticio {i}" for i in range(n)],
            "latitude.c": ["-31.4"] * n,
            "longitude.c": ["-64.2"] * n,
            "latitude.o": ["-31.4003"] * n,
            "longitude.o": ["-64.2"] * n,
            "name_score": [f"{v:.3f}" for v in rng.uniform(0, 1, n)],
            "address_score": [f"{v:.3f}" for v in rng.uniform(0, 1, n)],
            "total_score": [f"{v:.3f}" for v in rng.uniform(0.25, 1, n)],
        }
    ).write_csv(tmp_path / "final_output.csv")
    pl.DataFrame({"pos_id": [f"c{i}" for i in range(n)]}).write_csv(tmp_path / "clientes.csv")
    (tmp_path / "paso1.json").write_text(
        json.dumps({"parameters": {"threshold": 0.24}}), encoding="utf-8"
    )
    inputs = DatamatchInputs(
        datamatch_file="final_output.csv",
        clients_file="clientes.csv",
        client_name="andina",
        step_json="paso1.json",
    )
    out = tmp_path / "paso1"
    result = FileDatamatchSteps(tmp_path, BRAND).run(
        inputs, out, tmp_path, "paso1", 0.5, [], "cid"
    )

    page_path = out / "datamatch_andina_paso1_umbral.html"
    assert result.summary["umbral_html"] == str(page_path)
    assert str(page_path) not in result.files  # client names: never uploaded
    page = page_path.read_text(encoding="utf-8")
    assert "Escenarios para elegir el umbral" in page and "Codo de la curva" in page
    assert "Umbral del Front" in page and page.count("data:image/png") == 3
    assert "Lugar Ficticio" in page  # the pairs are what the person judges
    assert "<script" not in page and "http://" not in page and "https://" not in page


def test_redo_with_another_threshold_sets_it_on_the_step(monkeypatch):
    from cleaning_agent.entrypoints.cli import run_redo
    from tests.fakes import CLIENTS_FILE, DATAMATCH_FILE
    from tests.test_clients_flow import (
        FakeClientValidation,
        _to_client_question,
        run_resume,
        validate_and_upload,
    )

    app, _, _ = _to_client_question(FakeClientValidation())
    validate_and_upload(app)
    run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE, "clients_file": CLIENTS_FILE})

    run_redo(app, "t1", "fetch_datamatch", 0.62)
    values = app.get_state({"configurable": {"thread_id": "t1"}}).values
    assert values["datamatch"]["umbral"] == 0.62
    assert values["datamatch_history"][-1]["umbral_limpieza"] == 0.62


def test_redo_can_switch_the_step_to_distance_only():
    from cleaning_agent.entrypoints.cli import run_redo
    from tests.fakes import CLIENTS_FILE, DATAMATCH_FILE
    from tests.test_clients_flow import (
        FakeClientValidation,
        _to_client_question,
        run_resume,
        validate_and_upload,
    )

    app, _, _ = _to_client_question(FakeClientValidation())
    validate_and_upload(app)
    run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE, "clients_file": CLIENTS_FILE})
    with pytest.raises(SystemExit):
        run_redo(app, "t1", "fetch_datamatch", None, {"solo_distancia": True})
    with pytest.raises(SystemExit):
        run_redo(app, "t1", "fetch_datamatch", None, {"clients_file": "otro.csv"})
    run_redo(
        app, "t1", "fetch_datamatch", None, {"distancia_match_m": 25, "solo_distancia": True}
    )
    values = app.get_state({"configurable": {"thread_id": "t1"}}).values
    assert values["datamatch"]["solo_distancia"] is True
