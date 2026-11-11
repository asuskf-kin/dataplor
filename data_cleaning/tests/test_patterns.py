"""Country patterns: created when missing, refreshed after 6 months, always with an OK."""

from datetime import date
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.adapters.patterns_files import FilePatterns
from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.domain.patterns_policy import PatternsStatus, needs_update
from cleaning_agent.entrypoints.cli import run_resume
from tests.fakes import FRONT_JSON, FRONT_RESULT, FakePatterns, begin, make_deps


def _to_patterns(patterns: FakePatterns) -> Any:
    deps, *_ = make_deps()
    deps = deps.__class__(**{**deps.__dict__, "patterns": patterns})
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "geojson")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True})  # plan
    run_resume(app, "t1", {"approved": True})  # bronze
    view = run_resume(
        app, "t1", {"result_file": FRONT_RESULT, "metadata_json": FRONT_JSON}
    )
    return app, view


def test_fresh_patterns_go_straight_to_the_cleaning():
    _, view = _to_patterns(FakePatterns(updated="2099-01-01"))

    assert view["interrupt"]["kind"] == "franchise_review"
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert steps["check_patterns"] == "done" and steps["update_patterns"] == "pending"


def test_missing_patterns_are_created_with_an_ok_then_the_cleaning_runs():
    patterns = FakePatterns(exists=False, updated=None)
    app, view = _to_patterns(patterns)
    assert view["interrupt"]["kind"] == "update_patterns"
    assert "hay que crearlos" in view["interrupt"]["question"]
    assert 'PATTERNS_UPDATED = "' in view["interrupt"]["instructions"]

    # Claude Code writes the file, shows the diff, the person approves
    patterns.exists, patterns.updated = True, date.today().isoformat()
    view = run_resume(app, "t1", {"approved": True})

    assert patterns.reloads == 1
    assert view["interrupt"]["kind"] == "franchise_review"


def test_stale_patterns_ask_for_an_update_and_a_declined_update_keeps_the_old_ones():
    app, view = _to_patterns(FakePatterns(updated="2020-01-01"))
    assert "más de 6 meses" in view["interrupt"]["question"]

    view = run_resume(app, "t1", {"approved": False})

    assert view["interrupt"]["kind"] == "franchise_review"


def test_approved_but_still_missing_patterns_are_reasked():
    app, _ = _to_patterns(FakePatterns(exists=False, updated=None))

    view = run_resume(app, "t1", {"approved": True})  # file was not written

    assert view["interrupt"]["kind"] == "update_patterns"
    assert "still not usable" in view["interrupt"]["errors"][0]


def test_declining_missing_patterns_fails_the_run():
    app, _ = _to_patterns(FakePatterns(exists=False, updated=None))

    view = run_resume(app, "t1", {"approved": False})

    assert view["status"] == "failed" and "No hay patrones" in view["error"]


def test_needs_update_rule():
    today = date(2026, 11, 9)
    fresh = PatternsStatus(country="ar", path="p", exists=True, updated="2026-08-17")
    assert needs_update(fresh, today)[0] is False
    old = fresh.model_copy(update={"updated": "2026-04-01"})
    assert needs_update(old, today)[0] is True
    assert needs_update(fresh.model_copy(update={"exists": False}), today)[0] is True
    assert needs_update(fresh.model_copy(update={"updated": None}), today)[0] is True


def test_file_patterns_reads_the_declared_date_and_reloads(tmp_path: Path):
    folder = tmp_path / "cleaning_agent" / "domain" / "patterns"
    folder.mkdir(parents=True)
    adapter = FilePatterns(tmp_path, folder)
    assert adapter.status("zz").exists is False

    (folder / "patterns_zz.py").write_text(
        'PATTERNS_UPDATED = "2026-11-09"\nCHAIN_REGEX = [r"\boxxo\b"]\n',
        encoding="utf-8",
    )
    status = adapter.status("zz")

    assert status.exists and status.updated == "2026-11-09"
    assert status.source == "PATTERNS_UPDATED"
    assert adapter.path("do").name == "patterns_rd.py"
