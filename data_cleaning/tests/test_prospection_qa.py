"""QA de la prospección: reglas puras, adaptador con archivos y paso en el grafo."""

import dataclasses
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from openpyxl import load_workbook

from cleaning_agent.adapters.brand import BUNDLED_ASSETS_DIR, KinBrand
from cleaning_agent.adapters.excel_csv import write_csv
from cleaning_agent.adapters.prospection_qa import FileProspectionQa
from cleaning_agent.domain.models import ProspectionQaReview
from cleaning_agent.domain.prospection_qa import (
    Outlet,
    build_idf,
    category_shares,
    excluding_suggestion,
    find_mistakes,
    market_verdict,
    match_reason,
    parse_reason,
    tfidf_cosine,
)
from cleaning_agent.entrypoints.cli import run_resume as cli_resume
from tests.fakes import DATAMATCH_FILE, FakeProspectionQa, FakeStorage, make_deps
from tests.test_delivery import _kind, _to_front_datamatch, run_resume

BRAND = KinBrand(BUNDLED_ASSETS_DIR)
FILLER = [f"{kind} {who}" for kind in ("bar", "kiosco", "almacen") for who in ("sol", "luna", "rio", "mar")]
# ~0.0009 degrees of latitude = ~100 m
NEAR = 0.0009

# ---- domain ------------------------------------------------------------------


def test_tfidf_weights_the_distinctive_word_over_the_generic_one():
    names = ["kiosco el sol", "kiosco la luna", "kiosco central", "kiosco norte", "almacen el sol"]
    idf = build_idf(names)
    # Same proper name, different generic word > same generic word, different name
    assert tfidf_cosine("kiosco el sol", "almacen el sol", idf) > tfidf_cosine(
        "kiosco el sol", "kiosco la luna", idf
    )


def test_a_close_client_with_the_same_name_is_a_false_negative():
    prospect = Outlet("dp1", "Bar Don Pepe", -34.6, -58.4, "bar")
    client = Outlet("c1", "DON PEPE BAR", -34.6 + NEAR / 3, -58.4, "BAR")
    other = Outlet("c2", "Panaderia Lucia", -34.6, -58.4 + NEAR / 3, "PANADERIA")
    # A realistic corpus: "bar" is common, "don pepe" is not
    idf = build_idf([prospect.name, client.name, other.name, *FILLER])

    found = find_mistakes([prospect], [other, client], idf)

    assert [(m.prospect.id, m.client.id) for m in found] == [("dp1", "c1")]
    assert found[0].reason == "both_strong" and found[0].distance_m < 50


def test_the_same_name_farther_than_300_m_is_not_a_mistake():
    prospect = Outlet("dp1", "Bar Don Pepe", -34.6, -58.4)
    client = Outlet("c1", "Bar Don Pepe", -34.6 + 4 * NEAR, -58.4)  # ~400 m
    assert find_mistakes([prospect], [client], build_idf([prospect.name])) == []


def test_a_neighbour_with_another_name_is_not_a_mistake():
    prospect = Outlet("dp1", "Kiosco El Sol", -34.6, -58.4)
    client = Outlet("c1", "Farmacia Central", -34.6 + NEAR / 5, -58.4)
    idf = build_idf([prospect.name, client.name])
    assert find_mistakes([prospect], [client], idf) == []


def test_match_reason_and_its_stored_text():
    assert match_reason(0.9, 0.7) == "both_strong"
    assert match_reason(0.9, 0.4) == "proximity_dominant"
    assert match_reason(0.3, 0.9) == "name_dominant"
    assert parse_reason("name_dominant") == "name_dominant" and parse_reason("x") is None


def test_suggestion_priority_false_negative_then_category_then_non_beverage():
    mapped = {"bar": ("BAR", "High"), "hardware": ("", "Low"), "cafe": ("CAFE", "Low")}
    args = (mapped, {"BAR", "CAFE"}, {"hardware", "bar"})
    assert excluding_suggestion("dp1", "bar", {"dp1": "proximity_dominant"}, *args) == (
        "false_negative_proximity"
    )
    # Mapped with Medium/High to a client category beats the non-beverage flag
    assert excluding_suggestion("dp2", "bar", {}, *args) == "false_negative_category"
    assert excluding_suggestion("dp3", "hardware", {}, *args) == "no_beverage_category"
    # Low confidence does not count as a category false negative
    assert excluding_suggestion("dp4", "cafe", {}, *args) == ""


def test_category_shares_sort_by_no_match_share():
    rows = category_shares(["bar", "bar", "cafe"], ["bar", "cafe", "cafe", None])
    assert [r.category for r in rows] == ["(sin categoría)", "cafe", "bar"]
    assert rows[1].no_match_pct == round(200 / 3, 2)


def test_market_verdict():
    assert market_verdict(10, 80) == "under_matched"
    assert market_verdict(35, 80) == "consistent"
    assert market_verdict(10, None) == "insufficient"


# ---- adapter -----------------------------------------------------------------


@pytest.fixture
def qa_files(tmp_path: Path) -> dict[str, Any]:
    lat, lon = -34.6, -58.4
    write_csv(
        pl.DataFrame(
            {
                "dataplor_id": ["dp1", "dp2", "dp3", "dp4", "dp5"],
                "name": ["Bar Don Pepe", "Kiosco Lucia", "Ferreteria Sur", "Cafe Norte", "Depto Airbnb Centro"],
                "address": ["a"] * 5,
                "business_category": ["bar", "kiosk", "hardware", "cafe", "lodging"],
                "sub_category": ["bar", "kiosk", "hardware", "cafe", "lodging"],
                "city": ["CABA"] * 5,
                "state": ["Buenos Aires"] * 5,
                "latitude": [str(lat), str(lat + 0.01), str(lat + 0.02), str(lat + 0.03), str(lat + 0.04)],
                "longitude": [str(lon)] * 5,
            }
        ),
        tmp_path / "cleaned.csv",
    )
    # dp4 was matched in a Datamatch step
    (tmp_path / "paso1").mkdir()
    write_csv(pl.DataFrame({"id.c": ["c9"], "id.o": ["dp4"], "total_score": ["0.9"]}), tmp_path / "paso1/m.csv")
    write_csv(
        pl.DataFrame(
            {
                "pos_id": ["c1", "c9", "c3"],
                "pos_name": ["DON PEPE BAR", "CAFE NORTE", "Panaderia Rosa"],
                "pos_latitude": [str(lat + NEAR / 3), str(lat + 0.03), str(lat + 0.05)],
                "pos_longitude": [str(lon)] * 3,
                "pos_subchannel": ["BAR", "CAFE", "PANADERIA"],
            }
        ),
        tmp_path / "clients.csv",
    )
    return {
        "cleaned": str(tmp_path / "cleaned.csv"),
        "matches": [str(tmp_path / "paso1/m.csv")],
        "clients": str(tmp_path / "clients.csv"),
        "out": tmp_path / "qa",
    }


CLIENT_COLS = {"id": "pos_id", "name": "pos_name", "latitude": "pos_latitude", "longitude": "pos_longitude"}
DP_COLS = {"id": "dataplor_id", "name": "name", "latitude": "latitude", "longitude": "longitude"}


def test_adapter_finds_the_false_negative_and_keeps_client_data_local(qa_files: dict[str, Any]):
    qa = FileProspectionQa(Path("."), BRAND)
    prepared = qa.prepare(
        qa_files["cleaned"], qa_files["matches"], [], qa_files["clients"], CLIENT_COLS, DP_COLS, qa_files["out"]
    )
    # dp4 matched, dp5 is a rented flat (not a prospect): 3 no_match, 1 of them a client
    assert (prepared.match, prepared.no_match, prepared.clients) == (1, 3, 3)
    assert prepared.mistake_ids == {"dp1": "both_strong"}
    assert prepared.client_category_col == "pos_subchannel"
    categories = json.loads(Path(prepared.categories_file).read_text(encoding="utf-8"))
    assert {c["category"] for c in categories["client"]} == {"BAR", "CAFE", "PANADERIA"}
    # Category names only: no client name reaches the file Claude Code reads
    assert "DON PEPE" not in Path(prepared.categories_file).read_text(encoding="utf-8")

    review = ProspectionQaReview.model_validate(
        {
            "category_mapping": [
                {"prospection_category": "bar", "client_category": "BAR", "confidence": "High"},
                {"prospection_category": "kiosk", "client_category": "", "confidence": "Low"},
            ],
            "non_beverage": [{"category": "hardware", "reason": "ferretería"}],
            "benchmark": {
                "country": "Argentina",
                "penetration_pct": 70,
                "paragraph": "Texto de prueba.",
                "sources": [{"title": "Fuente", "url": "https://example.org/x"}],
            },
        }
    )
    result = qa.build(prepared, review, "andina", "ar", DP_COLS)

    report = Path(result.report).read_text(encoding="utf-8")
    assert "dp1" in report and "c1" in report  # ids, for the Datamatch
    for private in ("DON PEPE", "Panaderia Rosa", str(-34.6 + NEAR / 3)):
        assert private not in report
    assert result.summary["veredicto"] == "consistent"  # 25 % match vs 70 %
    assert result.summary["sugerencias_exclusion"]["false_negative_both_strong"] == 1
    assert result.summary["sugerencias_exclusion"]["no_beverage_category"] == 1
    names = {Path(f).name for f in result.local_files}
    assert {"category_mapping.xlsx", "category_issues.xlsx", "no_match_enriched.xlsx"} <= names
    assert any(n.startswith("prospection_qa_map_mistakes_") for n in names)
    ws = load_workbook(Path(qa_files["out"]) / "no_match_enriched.xlsx")["no_match"]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    head = rows[0]
    first = dict(zip(head, rows[1], strict=True))
    # Non-blank suggestions first, highest priority on top
    assert first["dataplor_id"] == "dp1" and first["excluding_suggestion"] == "false_negative_both_strong"
    assert first["mapped_category"] == "BAR" and first["mapped_category_confidence"] == "High"


# ---- graph -------------------------------------------------------------------

REVIEW = {"category_mapping": [], "non_beverage": [], "benchmark": None}


def _to_review(storage: FakeStorage, qa: FakeProspectionQa) -> tuple[Any, Any, dict[str, Any]]:
    deps, *_ = make_deps(storage=storage)
    deps = dataclasses.replace(deps, prospection_qa=qa)
    app = _to_front_datamatch(deps)
    view = run_resume(app, "t1", {"datamatch_file": DATAMATCH_FILE})
    return app, deps, view


def test_qa_runs_after_the_loop_and_removes_false_negatives_on_the_persons_ok():
    qa = FakeProspectionQa()
    app, deps, view = _to_review(FakeStorage(), qa)
    assert _kind(view) == "prospection_qa_review"
    assert view["interrupt"]["categories_file"].endswith("categories_for_review.json")
    # The full client base (the first step's) is the one audited
    assert qa.prepared_with[0]["clients_file"] == deps.datamatch_defaults["clients_file"]

    asked = cli_resume(app, "t1", REVIEW)
    assert _kind(asked) == "confirm_false_negatives"
    assert asked["interrupt"]["by_reason"]["both_strong"] == 1

    staged = cli_resume(app, "t1", {"remove": True})
    pending = staged["interrupt"]
    # 100 - 10 clients - 1 rented flat - 2 false negatives
    assert pending["qa"]["qa_ok"] and pending["qa"]["filas_conservadas"] == 87
    assert deps.datamatch_steps.false_negatives == {"dp-fn1": "both_strong", "dp-fn2": "name_dominant"}
    # Only the aggregate report goes up, to the cycle's silver qa_process folder
    extra = [e for e in pending["extra_destinations"] if any("prospection_qa_report" in f for f in e["files"])]
    assert len(extra) == 1 and "/qa_process/" in extra[0]["destination"]
    assert not any("no_match_enriched" in f for e in pending["extra_destinations"] for f in e["files"])


def test_false_negatives_kept_when_the_person_says_no():
    app, deps, _ = _to_review(FakeStorage(), FakeProspectionQa())
    cli_resume(app, "t1", REVIEW)
    staged = cli_resume(app, "t1", {"remove": False})
    assert staged["interrupt"]["qa"]["filas_conservadas"] == 89
    assert deps.datamatch_steps.false_negatives == {}


def test_no_false_negatives_goes_straight_to_the_prospects():
    app, _, _ = _to_review(FakeStorage(), FakeProspectionQa(mistakes={}))
    staged = cli_resume(app, "t1", REVIEW)
    assert _kind(staged) == "confirm_layer_upload" and staged["interrupt"]["layer"] == "gold"


def test_a_failing_qa_only_warns_and_the_prospects_go_on():
    _app, _, view = _to_review(FakeStorage(), FakeProspectionQa(error=ValueError("sin columna")))
    assert _kind(view) == "confirm_layer_upload"
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert steps["stage_prospects"] == "done" or steps["stage_prospects"] == "waiting_for_human"


def test_an_invalid_review_is_asked_again():
    app, _, _ = _to_review(FakeStorage(), FakeProspectionQa())
    again = cli_resume(app, "t1", {"category_mapping": [{"prospection_category": "bar"}]})
    assert _kind(again) == "prospection_qa_review" and again["interrupt"]["errors"]


def test_a_long_review_comes_in_a_json_file(tmp_path: Path):
    qa = FakeProspectionQa(mistakes={})
    app, _, _ = _to_review(FakeStorage(), qa)
    review = tmp_path / "review.json"
    mapping = [{"prospection_category": f"cat_{i}", "client_category": "BAR", "confidence": "Medium"} for i in range(300)]
    review.write_text(json.dumps({"category_mapping": mapping}), encoding="utf-8")
    cli_resume(app, "t1", {"review_file": str(review)})
    assert len(qa.reviews[0].category_mapping) == 300
