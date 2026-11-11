"""DatamatchStepPort adapter: one step of the Front <-> agent Datamatch loop.

Reads the Datamatch result of the Front and the client base used in that step, drops
the clients that already found their Dataplor point (score above the threshold) and
writes, into the step folder of the silver mirror:

- ``clients_bottler_<cliente>_<paso>.csv``: the reduced client base for the next step;
- ``datamatch_matches_<cliente>_<paso>.csv``: the matched rows of this step;
- ``<paso>.json``: the Front parameters of this step (copied as received);
- ``qa_process_report_<cliente>.xlsx``: ONE on-brand Excel for the whole cycle, in the
  date folder (one level up). Each step rewrites it with the history and the matches
  of every step folder found next to it (user, 2026-11-11: "no es únicamente del paso 1").

Client data is personal/commercial: rows are copied file to file and only counts and
identifiers reach the Excel and the logs (never names, addresses or coordinates).
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.worksheet.worksheet import Worksheet

from cleaning_agent.adapters.brand import (
    KinBrand,
)
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.xlsx_brand import XlsxStyle, band, section, table
from cleaning_agent.domain.datamatch_steps import (
    drop_known_points,
    matched_rows,
    remaining_clients,
    score_bins,
    step_summary,
)
from cleaning_agent.domain.models import (
    DatamatchInputs,
    DatamatchStepResult,
    ProspectsResult,
)

logger = logging.getLogger(__name__)

# Front output (Datamatch): ".c" = client base (POS), ".o" = options (Dataplor)
DEFAULT_COLUMNS = {
    "match_client_id": "id.c",
    "match_dataplor_id": "id.o",
    "score": "total_score",
    "client_id": "pos_id",
    # Column of the cleaned Dataplor that id.o points to
    "dataplor_id": "dataplor_id",
}
# Only identifiers and scores go to the Excel: never names, addresses or coordinates
MATCH_REPORT_COLUMNS = (
    "id.c",
    "id.o",
    "total_score",
    "name_score",
    "address_score",
    "phonetic_score",
    "distance_score",
    "distance",
)
REPORT_NAME = "qa_process_report_{client}.xlsx"
STEP_COLUMN = "paso"
# Front JSON keys left out of the Excel: the person in charge is personal data
PRIVATE_JSON_KEYS = {"slack"}


class DatamatchStepError(ValueError):
    """A Datamatch step cannot run: missing column or unreadable file."""


class FileDatamatchSteps:
    def __init__(
        self,
        project_root: Path,
        brand: KinBrand,
        columns: dict[str, str] | None = None,
    ) -> None:
        self.project_root = project_root
        self.brand = brand
        self.columns = {**DEFAULT_COLUMNS, **(columns or {})}

    def _read_csv(self, path: Path) -> pl.DataFrame:
        # Strings only: the reduced base must keep every value exactly as received
        return pl.read_csv(path, infer_schema=False)

    def _front_params(self, step_json: str) -> dict[str, Any]:
        if not step_json:
            return {}
        params: dict[str, Any] = json.loads(
            resolve(self.project_root, step_json).read_text(encoding="utf-8")
        )
        return params

    def _cycle_matches(
        self, report_dir: Path, client: str, folder: str, current: pl.DataFrame
    ) -> pl.DataFrame:
        """Matches of every step of the cycle (identifiers and scores only)."""
        frames: list[pl.DataFrame] = []
        for path in sorted(report_dir.glob(f"*/datamatch_matches_{client}_*.csv")):
            if path.parent.name != folder:  # this step's rows come from memory
                frames.append(
                    self._read_csv(path).with_columns(
                        pl.lit(path.parent.name).alias(STEP_COLUMN)
                    )
                )
        frames.append(current.with_columns(pl.lit(folder).alias(STEP_COLUMN)))
        columns = [STEP_COLUMN, *MATCH_REPORT_COLUMNS]
        return pl.concat(
            [f.select([c for c in columns if c in f.columns]) for f in frames],
            how="diagonal",
        )

    def build_prospects(
        self, cleaned_file: str, match_files: list[str], target: Path
    ) -> ProspectsResult:
        """Writes the cleaned Dataplor without the points matched in any loop step."""
        dataplor_id = self.columns["match_dataplor_id"]
        known = (
            pl.concat(
                [
                    self._read_csv(resolve(self.project_root, f)).select(dataplor_id)
                    for f in match_files
                ]
            )
            .get_column(dataplor_id)
            .drop_nulls()
            .unique()
        )
        cleaned = self._read_csv(resolve(self.project_root, cleaned_file))
        id_col = self.columns["dataplor_id"]
        if id_col not in cleaned.columns:
            raise DatamatchStepError(f"cleaned Dataplor has no column {id_col!r}")
        prospects = drop_known_points(cleaned, id_col, known)
        target.parent.mkdir(parents=True, exist_ok=True)
        prospects.write_csv(target)
        return ProspectsResult(
            file=str(target),
            known_ids=known.len(),
            known_in_file=int(known.is_in(cleaned.get_column(id_col).implode()).sum()),
            rows_in=cleaned.height,
            rows_out=prospects.height,
        )

    def run(
        self,
        inputs: DatamatchInputs,
        out_dir: Path,
        report_dir: Path,
        folder: str,
        threshold: float,
        history: list[dict[str, Any]],
        correlation_id: str,
    ) -> DatamatchStepResult:
        params = self._front_params(inputs.step_json)
        client_id = str(
            ((params.get("client") or {}).get("columns") or {}).get("id")
            or self.columns["client_id"]
        )
        match_id, score = self.columns["match_client_id"], self.columns["score"]
        datamatch = self._read_csv(resolve(self.project_root, inputs.datamatch_file))
        clients = self._read_csv(resolve(self.project_root, inputs.clients_file))
        for frame, needed, name in (
            (datamatch, (match_id, score), "Datamatch result"),
            (clients, (client_id,), "client base"),
        ):
            missing = [c for c in needed if c not in frame.columns]
            if missing:
                raise DatamatchStepError(f"{name} has no column(s) {missing}")

        matched = matched_rows(datamatch, score, threshold)
        kept = remaining_clients(clients, client_id, matched.get_column(match_id))
        summary = step_summary(clients.height, matched, kept.height, score, threshold)
        if not summary["cuadra"]:
            # A matched id that is not in the base would make the counts lie
            raise DatamatchStepError(
                f"Counts do not add up: {summary['clientes_inicio']:,} != "
                f"{summary['clientes_con_match']:,} + {summary['clientes_restantes']:,}"
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        name = inputs.client_name.lower()
        clients_out = out_dir / f"clients_bottler_{name}_{folder}.csv"
        matches_out = out_dir / f"datamatch_matches_{name}_{folder}.csv"
        kept.write_csv(clients_out)
        matched.write_csv(matches_out)
        files = [str(clients_out), str(matches_out)]
        if inputs.step_json:
            json_out = out_dir / f"{folder}.json"
            shutil.copyfile(resolve(self.project_root, inputs.step_json), json_out)
            files.append(str(json_out))

        step = {
            "paso": folder,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            **summary,
            "umbral_front": (params.get("parameters") or {}).get("threshold"),
            "datamatch_file": inputs.datamatch_file,
            "clients_file": inputs.clients_file,
            "nuevo_client_bottler": clients_out.name,
        }
        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / REPORT_NAME.format(client=name)
        all_matches = self._cycle_matches(report_dir, name, folder, matched)
        _write_report(
            report,
            self.brand,
            step,
            [*history, step],
            score_bins(all_matches.get_column(score)),
            params,
            all_matches,
            [Path(f).name for f in [*files, str(report)]],
        )
        files.append(str(report))
        logger.info(
            "[cid=%s] Datamatch %s: %s clients -> %s matched (score > %s) -> %s left",
            correlation_id,
            folder,
            f"{summary['clientes_inicio']:,}",
            f"{summary['clientes_con_match']:,}",
            threshold,
            f"{summary['clientes_restantes']:,}",
        )
        return DatamatchStepResult(
            files=files, clients_file=str(clients_out), summary=step
        )


def _summary_sheet(
    ws: Worksheet,
    style: XlsxStyle,
    step: dict[str, Any],
    history: list[dict[str, Any]],
    files: list[str],
) -> None:
    ws.title = "Resumen"
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 60
    paso, threshold = step["paso"], step["umbral_limpieza"]
    row = band(
        ws,
        style,
        "QA Datamatch · ciclo Front",
        f"Reporte del ciclo · {len(history)} paso(s), último: {paso}",
        4,
    )

    row = section(ws, style, row, f"Qué hice en el último paso ({paso})")
    did = [
        "1. Leí el resultado de Datamatch del Front y la base de clientes de este paso.",
        f"2. Tomé como encontrados los clientes con total_score > {threshold}: ya tienen su punto Dataplor.",
        "3. Los quité de la base de clientes: el nuevo client bottler solo trae los que faltan.",
        "4. Guardé la base reducida, los matches y este reporte en silver (qa_process), con su metadata.",
    ]
    for text in did:
        ws.cell(row, 2, text).font = style.body
        row += 1
    row += 1

    original = int(history[0]["clientes_inicio"]) if history else 0
    found_total = sum(int(h["clientes_con_match"]) for h in history)
    row = section(ws, style, row, "Resultado")
    kpis: list[tuple[str, Any, str]] = [
        ("Clientes en la base al inicio del paso", step["clientes_inicio"], ""),
        (
            f"Clientes con match (score > {threshold})",
            step["clientes_con_match"],
            f"{step['pct_encontrado']}% de la base del paso",
        ),
        (
            "Clientes que quedan (nuevo client bottler)",
            step["clientes_restantes"],
            "Base para el siguiente paso en el Front",
        ),
        (
            "Encontrados acumulados (todos los pasos)",
            found_total,
            f"{round(found_total / original * 100, 2) if original else 0}% de la base original",
        ),
        ("Umbral de Datamatch en el Front", step.get("umbral_front") or "—", ""),
        (
            "Los conteos cuadran",
            "Sí" if step["cuadra"] else "No",
            "inicio = con match + quedan",
        ),
    ]
    for label, value, note in kpis:
        ws.cell(row, 2, label).font = style.body
        number = ws.cell(row, 3, value)
        number.font = style.number
        number.alignment = Alignment(horizontal="right")
        if isinstance(value, int):
            number.number_format = "#,##0"
        ws.cell(row, 4, note).font = style.muted
        row += 1
    # The figure that matters for the loop: how many clients go to the next step
    ws.cell(row - 4, 3).fill = style.accent
    row += 1

    row = section(ws, style, row, "Archivos")
    ws.cell(row, 2, "Resultado Datamatch (entrada)").font = style.body
    ws.cell(row, 4, str(step["datamatch_file"])).font = style.muted
    ws.cell(row + 1, 2, "Base de clientes (entrada)").font = style.body
    ws.cell(row + 1, 4, str(step["clients_file"])).font = style.muted
    row += 2
    for name in files:
        ws.cell(row, 2, "Generado").font = style.body
        ws.cell(row, 4, name).font = style.muted
        row += 1
    row += 1

    row = section(ws, style, row, "Siguiente paso")
    for text in (
        f"Sube al Front {step['nuevo_client_bottler']} (ya en silver) como base de clientes.",
        "Corre Datamatch con el JSON del siguiente paso y pásale al agente el resultado y el JSON.",
        "Cuando ya no haga falta otro paso, dile al agente que siga con la prospección.",
    ):
        ws.cell(row, 2, text).font = style.body
        row += 1


def _flatten(prefix: str, value: Any) -> list[list[Any]]:
    if isinstance(value, dict):
        rows: list[list[Any]] = []
        for key, item in value.items():
            if not prefix and key in PRIVATE_JSON_KEYS:
                continue
            rows += _flatten(f"{prefix}.{key}" if prefix else str(key), item)
        return rows
    if isinstance(value, list):
        return [[prefix, ", ".join(map(str, value)) or "—"]]
    return [[prefix, value if value not in ("", None) else "—"]]


def _write_report(
    target: Path,
    brand: KinBrand,
    step: dict[str, Any],
    history: list[dict[str, Any]],
    bins: list[dict[str, Any]],
    params: dict[str, Any],
    matches: pl.DataFrame,
    files: list[str],
) -> None:
    style = XlsxStyle(brand)
    wb = Workbook()
    summary = wb.active
    if summary is None:  # a new Workbook always has one sheet
        summary = wb.create_sheet()
    _summary_sheet(summary, style, step, history, files)

    ws = wb.create_sheet("Historial")
    row = band(ws, style, "QA Datamatch", "Historial de pasos", 8)
    headers = [
        "Paso",
        "Fecha",
        "Inicio",
        "Con match",
        "Quedan",
        "% encontrado",
        "Umbral limpieza",
        "Umbral Front",
    ]
    table(
        ws,
        style,
        row,
        headers,
        [
            [
                h["paso"],
                h["fecha"],
                h["clientes_inicio"],
                h["clientes_con_match"],
                h["clientes_restantes"],
                h["pct_encontrado"],
                h["umbral_limpieza"],
                h.get("umbral_front") or "—",
            ]
            for h in history
        ],
        first_col=1,
    )
    for letter in "ABCDEFGH":
        ws.column_dimensions[letter].width = 16

    ws = wb.create_sheet("Distribucion score")
    row = band(
        ws, style, "QA Datamatch", "Matches por banda de score (todos los pasos)", 4
    )
    table(
        ws,
        style,
        row,
        ["Score desde", "Score hasta", "Matches"],
        [[b["desde"], b["hasta"], b["matches"]] for b in bins],
        first_col=1,
    )
    for letter in "ABC":
        ws.column_dimensions[letter].width = 16

    ws = wb.create_sheet("Parametros Front")
    row = band(
        ws,
        style,
        "QA Datamatch",
        f"Parámetros del último paso en el Front ({step['paso']})",
        2,
    )
    table(ws, style, row, ["Parámetro", "Valor"], _flatten("", params), first_col=1)
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 50

    ws = wb.create_sheet("Matches")
    row = band(
        ws,
        style,
        "QA Datamatch",
        "Matches de todos los pasos (solo identificadores)",
        len(matches.columns) or 1,
    )
    table(
        ws,
        style,
        row,
        list(matches.columns),
        [list(r) for r in matches.iter_rows()],
        first_col=1,
    )
    for i in range(len(matches.columns)):
        ws.column_dimensions[chr(ord("A") + i)].width = 18
    wb.save(target)
