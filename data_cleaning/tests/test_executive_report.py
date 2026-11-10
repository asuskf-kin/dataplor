"""Tests for the executive report with synthetic data (never real client data)."""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from openpyxl import load_workbook

from cleaning_agent.adapters.executive_report_builder import (
    ExecutiveReportResult,
    generate_executive_report,
)

RUN_DATE = "20260101_000000"
OUTPUT_NAME = "dataplor_final_pipeline_output_mx.csv"

# 20 input records: p01-p04 are dropped by the pipeline, p05-p08 are Off Premise.
IDS = [f"p{i:02d}" for i in range(1, 21)]
CHAIN_DROPS = ["p01", "p02"]
GEO_DROPS = ["p03", "p04"]
OFF_PREMISE = {"p05", "p06", "p07", "p08"}
# p05 is flagged but Off Premise, so it only counts when there is no channel filter.
FRANCHISES = {"p05": "Marca Fuera", "p09": "Marca Uno", "p10": None}
SECRET_NAME_PREFIX = "Negocio Ficticio"


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dataplor_id": IDS,
            "name": [f"{SECRET_NAME_PREFIX} {i}" for i in range(1, 21)],
            "business_category": (["Bar", "Restaurante", "Tienda", None] * 5),
            "main_category": "Comida",
            "city": "Ciudad X",
            "state": (["Estado A", "Estado B"] * 10),
            "channel_cat": [
                "Off Premise" if i in OFF_PREMISE else "On Premise" for i in IDS
            ],
            "latitude": 1.0,
        }
    )


def _write_drop(path: Path, ids: list[str], reason: str, **extra: object) -> None:
    pd.DataFrame(
        {
            "name": [f"{SECRET_NAME_PREFIX} {i}" for i in ids],
            "dataplor_id": ids,
            "drop_reason": reason,
            "drop_match": [f"match-{i}" for i in ids],
            **extra,  # overrides drop_match when the test needs a specific one
        }
    ).to_csv(path, index=False, encoding="utf-8-sig")


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    raw_dir = tmp_path / "raw"
    processed = tmp_path / "processed"
    dropped = tmp_path / "dropped"
    for d in (raw_dir, processed, dropped):
        d.mkdir()
    raw = _raw()
    raw.to_csv(raw_dir / "dataplor_cleaned.csv", index=False, encoding="utf-8-sig")

    _write_drop(
        dropped / "02_chains_filtered.csv",
        CHAIN_DROPS,
        "2_Cadena",
        drop_match=["OXXO", "OXXO"],
        drop_pattern=[r"\boxxo\b", r"\boxxo\b"],
    )
    _write_drop(
        dropped / "03_geo_balltree_deduped.csv",
        GEO_DROPS,
        "3_Duplicado_geo",
        drop_match=["grupo-1", "grupo-1"],
        drop_group_size=[3, 3],
        drop_detail=["d", "d"],
    )
    # Leftovers that must be ignored: a step of another run and a non-step file.
    _write_drop(dropped / "05_external_regex_excluded.csv", ["zz1", "zz2"], "5_Regex")
    _write_drop(dropped / "notes.csv", ["p20"], "x")

    survivors = raw[~raw["dataplor_id"].isin(CHAIN_DROPS + GEO_DROPS)]
    survivors.to_csv(processed / OUTPUT_NAME, index=False, encoding="utf-8-sig")
    v2 = survivors.assign(
        es_franquicia=survivors["dataplor_id"].map(
            lambda i: "Sí" if i in FRANCHISES else "No"
        ),
        franquicia_marca=survivors["dataplor_id"].map(FRANCHISES),
    )
    v2.to_csv(
        processed / "dataplor_final_pipeline_output_mx_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return {
        "raw": raw_dir / "dataplor_cleaned.csv",
        "output": processed / OUTPUT_NAME,
        "dropped": dropped,
        "out": tmp_path / "reports",
    }


def _run(paths: dict[str, Path], **kwargs: Any) -> ExecutiveReportResult:
    return generate_executive_report(
        paths["raw"],
        paths["output"],
        paths["dropped"],
        paths["out"],
        country="mx",
        bottler="centro_pacifico",
        run_date=RUN_DATE,
        **kwargs,
    )


def _names(result: ExecutiveReportResult) -> set[str]:
    return {f.name for f in result.files}


def test_happy_path_writes_every_file_with_the_right_numbers(
    paths: dict[str, Path],
) -> None:
    result = _run(paths)

    base = f"reporte_ejecutivo_mx_on_premise_centro_pacifico_{RUN_DATE}"
    assert _names(result) == {
        "dataplor_final_pipeline_output_mx_on_premise_sin_franquicias.csv",
        f"{base}.xlsx",
        f"{base}.html",
        f"{base}.pdf",
    }
    for f in result.files:
        assert f.is_file() and f.stat().st_size > 0
        assert f.parent == paths["out"]

    s = result.summary
    assert s["initial_rows"] == 20
    assert s["pipeline_steps"] == 2
    assert s["pipeline_drops"] == 4
    assert s["drops_step_02"] == 2
    assert s["drops_step_03"] == 2
    assert s["drops_step_05"] == 0  # its CSV belongs to another run
    assert s["full_dataset_rows"] == 16
    assert s["out_of_channel_rows"] == 4
    assert s["channel_rows"] == 12
    assert s["manual_deletions"] == 2  # p09 and p10; p05 is Off Premise
    assert s["final_rows"] == 10
    assert s["total_drops"] == 10
    assert s["retention_pct"] == pytest.approx(50.0)
    assert s["reconciliation_gap"] == 0
    assert s["warnings"] == 0
    assert s["channel"] == "On Premise"


def test_happy_path_file_contents(paths: dict[str, Path]) -> None:
    result = _run(paths)
    by_suffix = {f.suffix: f for f in result.files}

    channel_csv = pd.read_csv(by_suffix[".csv"], encoding="utf-8-sig")
    assert len(channel_csv) == 10
    assert set(channel_csv["channel_cat"]) == {"On Premise"}
    assert not set(channel_csv["dataplor_id"]) & {"p09", "p10"}

    html = by_suffix[".html"].read_text(encoding="utf-8")
    assert "50,0%" in html
    assert "Embudo del pipeline" in html
    assert "Borrados a mano: franquicias" in html
    assert "data:image/png;base64," in html

    assert by_suffix[".pdf"].read_bytes().startswith(b"%PDF")

    wb = load_workbook(by_suffix[".xlsx"])
    assert wb.sheetnames == [
        "Resumen",
        "Categorias",
        "Categorias x motivo",
        "Borrados a mano",
    ]
    assert wb["Borrados a mano"].max_row == 3  # header + 2 franchises
    # Every input category (4 incl. the missing one) is listed.
    assert wb["Categorias"].max_row == 4 + 2  # header + 4 + TOTAL


def test_channel_csv_is_not_overwritten_by_default(paths: dict[str, Path]) -> None:
    first = _run(paths)
    channel_csv = next(f for f in first.files if f.suffix == ".csv")
    channel_csv.write_text("editado a mano", encoding="utf-8")

    _run(paths)
    assert channel_csv.read_text(encoding="utf-8") == "editado a mano"

    _run(paths, overwrite_channel_csv=True)
    assert channel_csv.read_text(encoding="utf-8") != "editado a mano"


def test_no_channel_reports_the_whole_dataset(paths: dict[str, Path]) -> None:
    result = _run(paths, channel=None)

    assert _names(result) == {
        f"reporte_ejecutivo_mx_todos_los_canales_centro_pacifico_{RUN_DATE}{ext}"
        for ext in (".xlsx", ".html", ".pdf")
    }
    s = result.summary
    assert s["out_of_channel_rows"] == 0
    assert s["channel_rows"] == 16
    assert s["manual_deletions"] == 3  # all flagged rows count without a channel filter
    assert s["final_rows"] == 13
    assert s["reconciliation_gap"] == 0
    assert s["channel"] == ""


def test_missing_franchise_file_skips_manual_step(paths: dict[str, Path]) -> None:
    (paths["output"].with_name("dataplor_final_pipeline_output_mx_v2.csv")).unlink()

    result = _run(paths)

    s = result.summary
    assert s["manual_deletions"] == 0
    assert s["final_rows"] == 12
    assert s["warnings"] == 1  # "no está el archivo de borrados a mano"
    assert "dataplor_final_pipeline_output_mx_on_premise.csv" in _names(result)
    xlsx = next(f for f in result.files if f.suffix == ".xlsx")
    assert "Borrados a mano" not in load_workbook(xlsx).sheetnames


def test_manual_deletions_can_be_disabled(paths: dict[str, Path]) -> None:
    result = _run(paths, apply_manual_deletions=False)
    assert result.summary["manual_deletions"] == 0
    assert result.summary["warnings"] == 0


def test_missing_drop_csvs_flags_the_reconciliation_gap(paths: dict[str, Path]) -> None:
    for f in paths["dropped"].glob("*.csv"):
        f.unlink()
    paths["dropped"].rmdir()

    result = _run(paths)

    s = result.summary
    assert s["pipeline_steps"] == 0
    assert s["pipeline_drops"] == 0
    assert s["final_rows"] == 10
    assert s["reconciliation_gap"] == 4  # the 4 pipeline drops are unaccounted for
    assert s["warnings"] == 1
    assert all(f.is_file() for f in result.files)


def test_empty_drops_keep_everything(tmp_path: Path) -> None:
    raw = _raw()
    raw_csv, output_csv = tmp_path / "raw.csv", tmp_path / "out.csv"
    raw.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    raw.to_csv(output_csv, index=False, encoding="utf-8-sig")
    dropped = tmp_path / "dropped"
    dropped.mkdir()
    # A step that dropped nothing: header only.
    pd.DataFrame(columns=["dataplor_id", "name", "drop_reason"]).to_csv(
        dropped / "02_chains_filtered.csv", index=False
    )

    result = generate_executive_report(
        raw_csv,
        output_csv,
        dropped,
        tmp_path / "reports",
        country="mx",
        bottler="",
        channel=None,
        run_date=RUN_DATE,
    )

    s = result.summary
    assert s["initial_rows"] == s["final_rows"] == 20
    assert s["total_drops"] == 0
    assert s["retention_pct"] == pytest.approx(100.0)
    assert s["reconciliation_gap"] == 0
    # Empty bottler collapses the '__' it would leave in the name.
    assert _names(result) == {
        f"reporte_ejecutivo_mx_todos_los_canales_{RUN_DATE}{ext}"
        for ext in (".xlsx", ".html", ".pdf")
    }


def test_channel_requested_without_channel_column(paths: dict[str, Path]) -> None:
    out = pd.read_csv(paths["output"], encoding="utf-8-sig").drop(columns="channel_cat")
    out.to_csv(paths["output"], index=False, encoding="utf-8-sig")

    result = _run(paths, apply_manual_deletions=False)

    assert result.summary["channel"] == ""
    assert result.summary["final_rows"] == 16
    assert result.summary["warnings"] == 1
    assert not any(f.suffix == ".csv" for f in result.files)


def test_unknown_placeholder_falls_back_to_default_name(paths: dict[str, Path]) -> None:
    result = _run(paths, name_template="informe_{cliente}")
    assert f"reporte_ejecutivo_mx_on_premise_centro_pacifico_{RUN_DATE}.html" in _names(
        result
    )
    assert result.summary["warnings"] == 1


def test_template_cannot_escape_out_dir(paths: dict[str, Path]) -> None:
    result = _run(paths, name_template="../../fuera_{pais}")
    assert all(f.parent == paths["out"] for f in result.files)


def test_missing_output_raises(paths: dict[str, Path]) -> None:
    paths["output"].unlink()
    with pytest.raises(FileNotFoundError):
        _run(paths)


def test_logs_carry_no_row_contents(
    paths: dict[str, Path], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(
        logging.DEBUG, logger="cleaning_agent.adapters.executive_report_builder"
    ):
        _run(paths, correlation_id="cid-test")
    assert caplog.records
    assert all("[cid=cid-test]" in r.getMessage() for r in caplog.records)
    assert SECRET_NAME_PREFIX not in caplog.text
    assert "Marca Uno" not in caplog.text
