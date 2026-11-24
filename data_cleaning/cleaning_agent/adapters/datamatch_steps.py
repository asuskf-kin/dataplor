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
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment
from openpyxl.worksheet.worksheet import Worksheet

from cleaning_agent.adapters.brand import (
    KinBrand,
)
from cleaning_agent.adapters.datamatch_step_qa import step_qa_html
from cleaning_agent.adapters.datamatch_threshold_page import threshold_page
from cleaning_agent.adapters.excel_csv import (
    csv_separator,
    write_csv,
)
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.xlsx_brand import XlsxStyle, band, section, table
from cleaning_agent.domain.datamatch_steps import (
    LODGING_FILE_SUFFIX,
    LODGING_REASON,
    drop_known_points,
    lodging_rentals,
    lodging_term,
    match_causes,
    match_distance_m,
    match_quality,
    matched_rows,
    out_of_territory,
    remaining_clients,
    rows_in_base,
    score_bins,
    step_summary,
)
from cleaning_agent.domain.models import (
    DatamatchInputs,
    DatamatchStepResult,
    ProspectsResult,
)

logger = logging.getLogger(__name__)

# Rented flats removed from the prospects: written next to them for review
LODGING_COLUMNS = (
    "dataplor_id",
    "name",
    "address",
    "business_category",
    "sub_category",
    "city",
    "state",
    "latitude",
    "longitude",
)

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
    "match_por",
    "causa",
    "total_score",
    "name_score",
    "address_score",
    "phonetic_score",
    "distance_score",
    "distance",
)
# Client and Dataplor coordinates in the Front output: only used to measure the match
# distance, never written to a report
MATCH_COORDINATES = ("latitude.c", "longitude.c", "latitude.o", "longitude.o")
REPORT_NAME = "qa_process_report_{client}.xlsx"
STEP_COLUMN = "paso"
# Province column of the cleaned Dataplor (out-of-territory filter)
STATE_COL = "state"
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
        return pl.read_csv(path, infer_schema=False, separator=csv_separator(path))

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

    def _cycle_params(
        self, report_dir: Path, folder: str, current: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Front JSON of every step of the cycle (``<paso>/<paso>.json``), oldest first."""
        steps: dict[str, dict[str, Any]] = {}
        for path in sorted(report_dir.glob("*/*.json")):
            if path.stem == path.parent.name and path.parent.name != folder:
                steps[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        steps[folder] = current
        return steps

    def close_cycle_report(
        self,
        report_dir: Path,
        client_name: str,
        history: list[dict[str, Any]],
        lodging_removed: int,
        prospects_left: int,
    ) -> list[str]:
        """Rewrites the cycle Excel with the rented flats as its closing row.

        User, 2026-11-23 (on "Cuántos salieron en cada paso"): "no veo el airbnb acá,
        colócalo". The flats leave the prospects (Dataplor points), after the last
        step, so the row is written when the prospects are built. Returns the Excel
        path, or [] when the cycle has no step files to rebuild it from.
        """
        if not history:
            return []
        name = client_name.lower()
        folder = str(history[-1]["paso"])
        last = report_dir / folder / f"datamatch_matches_{name}_{folder}.csv"
        if not last.is_file():
            return []
        step_json = report_dir / folder / f"{folder}.json"
        params = (
            json.loads(step_json.read_text(encoding="utf-8")) if step_json.is_file() else {}
        )
        report = report_dir / REPORT_NAME.format(client=name)
        total = lodging_removed + prospects_left
        _write_report(
            report,
            self.brand,
            history[-1],
            history,
            self._cycle_params(report_dir, folder, params),
            _with_criteria(
                self._cycle_matches(report_dir, name, folder, self._read_csv(last)),
                history,
            ),
            [],
            closing=[
                "airbnb",
                f"{LODGING_REASON} (regex sobre el nombre)",
                lodging_removed,
                prospects_left,
                round(lodging_removed / total * 100, 2) if total else 0.0,
            ],
        )
        return [str(report)]

    def _taken_before(self, report_dir: Path, client: str, folder: str) -> pl.Series:
        """Dataplor ids matched in the earlier steps of this cycle (their step folders)."""
        column = self.columns["match_dataplor_id"]
        ids = [
            self._read_csv(path).get_column(column)
            for path in sorted(report_dir.glob(f"*/datamatch_matches_{client}_*.csv"))
            if path.parent.name != folder
            and column in self._read_csv(path).columns
        ]
        return pl.concat(ids) if ids else pl.Series(column, [], dtype=pl.Utf8)

    def build_prospects(
        self,
        cleaned_file: str,
        match_files: list[str],
        target: Path,
        excluded_states: list[str] | None = None,
        false_negatives: Mapping[str, str] | None = None,
    ) -> ProspectsResult:
        """Writes the cleaned Dataplor without the points matched in any loop step."""
        dataplor_id = self.columns["match_dataplor_id"]
        # Each matches file lives in its step folder (.../paso1/datamatch_matches_...)
        matched = pl.concat(
            [
                self._read_csv(resolve(self.project_root, f))
                .select(pl.col(dataplor_id).cast(pl.Utf8))
                .with_columns(pl.lit(Path(f).parent.name).alias("paso"))
                for f in match_files
            ]
        ).drop_nulls(dataplor_id)
        known = matched.get_column(dataplor_id).unique()
        first_step = matched.unique(dataplor_id, keep="first", maintain_order=True)
        cleaned = self._read_csv(resolve(self.project_root, cleaned_file))
        id_col = self.columns["dataplor_id"]
        if id_col not in cleaned.columns:
            raise DatamatchStepError(f"cleaned Dataplor has no column {id_col!r}")
        prospects = drop_known_points(cleaned, id_col, known)
        outside = prospects.head(0)
        if excluded_states:
            if STATE_COL not in prospects.columns:
                raise DatamatchStepError(f"cleaned Dataplor has no column {STATE_COL!r}")
            mask = out_of_territory(prospects.get_column(STATE_COL), excluded_states)
            outside, prospects = prospects.filter(mask), prospects.filter(~mask)
        # Clients the prospection QA found among the prospects (the person said remove)
        removed_fn: dict[str, str] = {}
        if false_negatives:
            fn_mask = pl.col(id_col).is_in(list(false_negatives))
            removed_fn = {
                str(i): str(false_negatives[str(i)])
                for i in prospects.filter(fn_mask).get_column(id_col).to_list()
            }
            prospects = prospects.filter(~fn_mask)
        # Extra step after the Datamatch: rented flats are not outlets (user, 2026-11-23)
        rental = lodging_rentals(prospects)
        rentals, prospects = prospects.filter(rental), prospects.filter(~rental)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Same format as every CSV (user, 2026-11-23: "el csv sigue viendose mal"): the
        # Dataplor JSON goes flat; priorización reads that flat text since that day
        write_csv(prospects, target)
        lodging_file = ""
        if rentals.height:
            # The removed points stay reviewable (user, 2026-11-23: "no veo en el repo los
            # que salieron por AIRBNB"): Dataplor points only, no client data
            out = target.with_name(f"{target.stem}{LODGING_FILE_SUFFIX}.csv")
            keep = [c for c in LODGING_COLUMNS if c in rentals.columns]
            write_csv(
                rentals.select(keep).with_columns(
                    pl.col("name")
                    .map_elements(lodging_term, return_dtype=pl.Utf8)
                    .alias("termino_regex")
                    if "name" in keep
                    else pl.lit("").alias("termino_regex")
                ),
                out,
            )
            lodging_file = str(out)
        return ProspectsResult(
            file=str(target),
            known_ids=known.len(),
            known_in_file=int(known.is_in(cleaned.get_column(id_col).implode()).sum()),
            rows_in=cleaned.height,
            rows_out=prospects.height,
            known_points=dict(
                zip(
                    first_step.get_column(dataplor_id).to_list(),
                    first_step.get_column("paso").to_list(),
                    strict=True,
                )
            ),
            out_of_territory=(
                dict(
                    zip(
                        outside.get_column(id_col).to_list(),
                        outside.get_column(STATE_COL).fill_null("").to_list(),
                        strict=True,
                    )
                )
                if excluded_states
                else {}
            ),
            lodging_file=lodging_file,
            false_negatives=removed_fn,
            lodging_rentals={
                str(i): lodging_term(n)
                for i, n in zip(
                    rentals.get_column(id_col).to_list(),
                    rentals.get_column("name").to_list()
                    if "name" in rentals.columns
                    else [None] * rentals.height,
                    strict=True,
                )
            },
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
        outside_base = 0
        if inputs.filtrar_a_base:
            datamatch, outside_base = rows_in_base(datamatch, match_id, clients, client_id)
            logger.warning(
                "Datamatch %s: %d clients of the Front result are not in the step base "
                "and were dropped (filtrar_a_base)",
                folder,
                outside_base,
            )

        max_distance = inputs.distancia_match_m
        all_distances = match_distance_m(datamatch, *MATCH_COORDINATES)
        if max_distance is not None and all_distances is None:
            raise DatamatchStepError(
                "distancia_match_m needs the client and Dataplor coordinates "
                f"{list(MATCH_COORDINATES)} in the Datamatch result"
            )
        matched = matched_rows(
            datamatch,
            score,
            threshold,
            all_distances,
            max_distance,
            self.columns["match_dataplor_id"],
            score_rule=not inputs.solo_distancia,
        )
        matched = match_causes(
            matched,
            score,
            threshold,
            match_distance_m(matched, *MATCH_COORDINATES),
            max_distance,
        )
        kept = remaining_clients(clients, client_id, matched.get_column(match_id))
        summary = step_summary(
            clients.height,
            matched,
            kept.height,
            score,
            threshold,
            max_distance,
            score_rule=not inputs.solo_distancia,
        )
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
        # Excel-safe (BOM, CRLF, no quoted field): people open both; the Front reads
        # the reduced base back as the client base of the next step
        write_csv(kept, clients_out)
        write_csv(matched, matches_out)
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
            "accion": step_action(summary),
            "enfoque": inputs.enfoque or step_focus(params),
        }
        quality = match_quality(
            matched,
            match_distance_m(matched, *MATCH_COORDINATES),
            match_id,
            self.columns["match_dataplor_id"],
            score,
            threshold,
            max_distance,
            self._taken_before(report_dir, name, folder),
        )
        if inputs.filtrar_a_base:
            # Visible in the step QA and the cycle log: the Front's own counts differ
            step["clientes_fuera_de_base"] = outside_base
            quality["alertas"].append(
                f"El Front corrió con otra base: {outside_base:,} clientes de su resultado "
                "no están en la base de este paso y se descartaron (filtrar_a_base)"
            )
        step["calidad"] = quality
        qa_out = out_dir / f"datamatch_{name}_{folder}_qa.html"
        qa_out.write_text(
            step_qa_html(
                self.brand,
                name,
                step,
                [*history, step],
                quality,
                score_bins(matched.get_column(score)),
                params,
                [Path(f).name for f in [*files, str(qa_out)]],
                PRIVATE_JSON_KEYS,
            ),
            encoding="utf-8",
        )
        files.append(str(qa_out))

        # Decision page: client names side by side, so it is written but never listed
        # among the files to upload (see datamatch_threshold_page)
        front_threshold = (params.get("parameters") or {}).get("threshold")
        threshold_out = out_dir / f"datamatch_{name}_{folder}_umbral.html"
        threshold_out.write_text(
            threshold_page(
                self.brand,
                name,
                folder,
                datamatch,
                score,
                threshold,
                float(front_threshold) if isinstance(front_threshold, int | float) else None,
                all_distances,
                "Elige el umbral y pídele al agente rehacer el paso con él: "
                f"redo --after fetch_datamatch --umbral <valor> (hoy {threshold}). "
                "El paso se vuelve a armar con ese umbral antes de pedir la subida.",
                max_distance,
                bool(inputs.solo_distancia),
            ),
            encoding="utf-8",
        )
        step["umbral_html"] = str(threshold_out)

        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / REPORT_NAME.format(client=name)
        cycle = [*history, step]
        all_matches = _with_criteria(
            self._cycle_matches(report_dir, name, folder, matched), cycle
        )
        _write_report(
            report,
            self.brand,
            step,
            cycle,
            self._cycle_params(report_dir, folder, params),
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
    closing: list[Any] | None = None,
) -> None:
    """The cycle at a glance: funnel, what each step took out and what is left.

    ``closing``: the rented flats removed from the prospects after the last step. They
    are Dataplor points, not clients, so they get their own table and their own figure
    (user, 2026-11-23: the row under the client table read as if 40.595 clients were
    left, "el excel estaba mal actualizado el quedan hoy, arréglalo").

    User, 2026-11-23: per-step counts up front and a funnel instead of the file list.
    """
    del files  # listed in the metadata; the summary is for decisions (user, 2026-11-23)
    ws.title = "Resumen"
    for letter, width in zip("ABCDEF", (2, 14, 52, 16, 16, 14), strict=True):
        ws.column_dimensions[letter].width = width
    original = int(history[0]["clientes_inicio"]) if history else 0
    found_total = sum(int(h["clientes_con_match"]) for h in history)
    left = int(step["clientes_restantes"])
    row = band(
        ws,
        style,
        "QA Datamatch · bitácora del ciclo",
        f"De {original:,} clientes, {found_total:,} ya tienen su punto Dataplor "
        f"y quedan {left:,} · {len(history)} paso(s)",
        6,
    )

    row = section(ws, style, row, "Resultado del ciclo")
    kpis: list[tuple[str, int, str]] = [
        ("Clientes en la base original", original, ""),
        (
            "Salieron con match (todos los pasos)",
            found_total,
            f"{round(found_total / original * 100, 2) if original else 0}% de la base",
        ),
        (
            "Clientes que siguen sin su punto Dataplor (base para el siguiente paso)",
            left,
            step["nuevo_client_bottler"],
        ),
    ]
    if closing:
        # Different unit: Dataplor points, the prospects that go to priorización
        kpis.append(
            (
                "Prospectos finales (puntos Dataplor sin clientes ni alojamiento)",
                int(closing[3]),
                "van a priorización y al paquete gold",
            )
        )
    for label, value, note in kpis:
        ws.cell(row, 2, label).font = style.body
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        number = ws.cell(row, 4, value)
        number.font = style.number
        number.number_format = "#,##0"
        number.alignment = Alignment(horizontal="right")
        ws.cell(row, 5, note).font = style.muted
        row += 1
    # The figure the person decides on: how many clients are still left
    ws.cell(row - (2 if closing else 1), 4).fill = style.accent
    row += 1

    row = section(ws, style, row, "Cuántos salieron en cada paso")
    first_table_row = row
    row = table(
        ws,
        style,
        row,
        ["Paso", "Acción tomada", "Salen", "Quedan", "% del paso"],
        [
            [
                h["paso"],
                h.get("accion") or step_action(h),
                int(h["clientes_con_match"]),
                int(h["clientes_restantes"]),
                h["pct_encontrado"],
            ]
            for h in history
        ],
        first_col=2,
    )
    for r in range(first_table_row + 1, row):
        for c in (4, 5):
            ws.cell(r, c).number_format = "#,##0"
    row += 1

    if closing:
        row = section(ws, style, row, "Después del ciclo: prospectos (puntos Dataplor, no clientes)")
        first_table_row = row
        row = table(
            ws,
            style,
            row,
            ["Paso", "Acción tomada", "Salen", "Quedan prospectos", "% de los puntos"],
            [closing],
            first_col=2,
        )
        for r in range(first_table_row + 1, row):
            for c in (4, 5):
                ws.cell(r, c).number_format = "#,##0"
        row += 1

    # Funnel: the base after each step, as a horizontal bar chart (native Excel chart)
    row = section(ws, style, row, "Embudo: clientes que siguen sin su punto Dataplor")
    data_row = row
    ws.cell(data_row, 2, "Etapa").font = style.muted
    ws.cell(data_row, 4, "Clientes").font = style.muted
    stages = [("Base original", original)] + [
        (f"Tras {h['paso']}", int(h["clientes_restantes"])) for h in history
    ]
    for i, (label, value) in enumerate(stages, start=1):
        ws.cell(data_row + i, 2, label).font = style.body
        cell = ws.cell(data_row + i, 4, value)
        cell.number_format = "#,##0"
        cell.font = style.number
    chart = BarChart()
    chart.type = "bar"
    chart.style = 10
    chart.title = None
    chart.legend = None
    chart.y_axis.majorGridlines = None
    chart.y_axis.numFmt = "#,##0"
    chart.x_axis.scaling.orientation = "maxMin"  # first stage on top: reads as a funnel
    chart.gapWidth = 40
    values = Reference(ws, min_col=4, min_row=data_row, max_row=data_row + len(stages))
    labels = Reference(ws, min_col=2, min_row=data_row + 1, max_row=data_row + len(stages))
    chart.add_data(values, titles_from_data=True)
    chart.set_categories(labels)
    series = chart.series[0]
    series.graphicalProperties.solidFill = style.accent.fgColor.rgb[-6:]
    series.graphicalProperties.line.solidFill = "000000"
    series.dLbls = DataLabelList()
    series.dLbls.showVal = True
    chart.height = 2 + 1.4 * len(stages)
    chart.width = 22
    ws.add_chart(chart, f"B{data_row + len(stages) + 2}")


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


WEIGHT_FOCUS = {
    "position_weight": "cercanía",
    "address_weight": "direcciones",
    "name_weight": "nombres",
    "phonetic_weight": "nombres (fonética)",
}


def step_action(step: dict[str, Any]) -> str:
    """What took clients out in a step, as the person decided it."""
    distance = step.get("distancia_match_m")
    score = f"total_score > {step['umbral_limpieza']}"
    if distance is None:
        return f"Match si {score}"
    if step.get("solo_distancia"):
        return f"Solo match a <= {distance:g} m (decisión del usuario; el score no cuenta)"
    return f"Match si {score} o candidato a <= {distance:g} m"


def step_focus(params: dict[str, Any]) -> str:
    """Focus of a step read from its Front JSON: heaviest weight and how candidates came."""
    weights = {
        k: float(v)
        for k, v in (params.get("parameters") or {}).items()
        if k in WEIGHT_FOCUS and isinstance(v, int | float)
    }
    if not weights:
        return "—"
    top = max(weights, key=lambda k: weights[k])
    by = params.get("create_options_by") or {}
    source = [n for n, k in (("coordenadas", "lat_long"), ("dirección", "address"))
              if str(by.get(k)).lower() == "true"]
    text = f"Enfoque en {WEIGHT_FOCUS[top]} ({top.removesuffix('_weight')} {weights[top]:g})"
    return f"{text}; candidatos por {' y '.join(source)}" if source else text


def _with_criteria(matches: pl.DataFrame, history: list[dict[str, Any]]) -> pl.DataFrame:
    """``criterio``: "match paso1 · total_score > 0.6", "match paso2 · <= 25 m", ...

    Steps written before ``causa`` existed get the rule of that step from its history.
    """
    rules = {
        str(h["paso"]): (
            f"<= {h['distancia_match_m']:g} m"
            if h.get("solo_distancia")
            else f"total_score > {h['umbral_limpieza']}"
        )
        for h in history
    }
    rule = pl.col(STEP_COLUMN).replace_strict(rules, default="", return_dtype=pl.Utf8)
    if "match_por" in matches.columns:
        distance = next(
            (h.get("distancia_match_m") for h in history if h.get("distancia_match_m")), None
        )
        rule = (
            pl.when(pl.col("match_por") == "distancia")
            .then(pl.lit(f"<= {distance:g} m" if distance else "por distancia"))
            .when(pl.col("match_por") == "score")
            .then(pl.format("total_score > {}", pl.col(STEP_COLUMN).replace_strict(
                {str(h["paso"]): str(h["umbral_limpieza"]) for h in history},
                default="?",
                return_dtype=pl.Utf8,
            )))
            .otherwise(rule)
        )
    framed = matches.with_columns(
        pl.format("match {} · {}", pl.col(STEP_COLUMN), rule).alias("criterio")
    )
    first = [STEP_COLUMN, "criterio"]
    rest = [c for c in framed.columns if c not in (*first, "match_por")]
    return framed.select([*first, *rest])


def _write_report(
    target: Path,
    brand: KinBrand,
    step: dict[str, Any],
    history: list[dict[str, Any]],
    params: dict[str, dict[str, Any]],
    matches: pl.DataFrame,
    files: list[str],
    closing: list[Any] | None = None,
) -> None:
    style = XlsxStyle(brand)
    wb = Workbook()
    summary = wb.active
    if summary is None:  # a new Workbook always has one sheet
        summary = wb.create_sheet()
    _summary_sheet(summary, style, step, history, files, closing)

    ws = wb.create_sheet("Historial")
    row = band(ws, style, "QA Datamatch", "Historial de pasos: qué se hizo y con qué enfoque", 10)
    headers = [
        "Paso",
        "Fecha",
        "Inicio",
        "Salen (match)",
        "Quedan",
        "% encontrado",
        "Umbral limpieza",
        "Umbral Front",
        "Acción tomada",
        "Enfoque",
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
                h.get("accion") or step_action(h),
                h.get("enfoque") or step_focus(params.get(str(h["paso"])) or {}),
            ]
            for h in history
        ],
        first_col=1,
    )
    if history:
        # Closing row: what the cycle took out and the base left by the person's decisions
        end = row + len(history) + 1
        original = int(history[0]["clientes_inicio"])
        found = sum(int(h["clientes_con_match"]) for h in history)
        ws.cell(end, 1, "Total ciclo").font = style.number
        ws.cell(end, 3, original).font = style.number
        ws.cell(end, 4, found).font = style.number
        left = ws.cell(end, 5, int(history[-1]["clientes_restantes"]))
        left.font = style.number
        left.fill = style.accent
        ws.cell(end, 6, round(found / original * 100, 2) if original else 0).font = style.number
        ws.cell(end, 9, "Quedan al final del ciclo (decisión del usuario)").font = style.muted
        for c in (3, 4, 5):
            ws.cell(end, c).number_format = "#,##0"
    for letter in "ABCDEFGH":
        ws.column_dimensions[letter].width = 16
    ws.column_dimensions["I"].width = 48
    ws.column_dimensions["J"].width = 56

    # Bitácora: the parameters of EVERY step side by side (user, 2026-11-23)
    ws = wb.create_sheet("Parametros Front")
    steps = list(params)
    row = band(
        ws, style, "QA Datamatch", "Parámetros del Front en cada paso", len(steps) + 1
    )
    values = {paso: dict(_flatten("", params[paso])) for paso in steps}
    keys = list(dict.fromkeys(k for paso in steps for k in values[paso]))
    table(
        ws,
        style,
        row,
        ["Parámetro", *steps],
        [[k, *(values[paso].get(k, "—") for paso in steps)] for k in keys],
        first_col=1,
    )
    ws.column_dimensions["A"].width = 40
    for i in range(len(steps)):
        ws.column_dimensions[chr(ord("B") + i)].width = 44

    ws = wb.create_sheet("Matches")
    row = band(
        ws,
        style,
        "QA Datamatch",
        "Clientes que tomamos como match en cada paso y por qué (solo identificadores)",
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
