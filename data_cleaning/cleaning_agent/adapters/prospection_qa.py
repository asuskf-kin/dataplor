"""ProspectionQaPort adapter: QA de la prospección después del ciclo de Datamatch.

Dos mitades, con la revisión de Claude Code en medio (interrupt):

``prepare``: arma match / no_match, lee la base de clientes (solo id, nombre,
coordenadas y categoría), busca falsos negativos y deja las categorías únicas de ambas
bases en un JSON para que Claude Code las cruce.

``build``: con la revisión (cruce de categorías, no bebidas, benchmark de mercado)
escribe los Excel de categorías, el no_match enriquecido, los dos mapas y el reporte.

Solo el reporte (conteos, tasas e ids, sin nombres ni coordenadas) se puede subir; todo
lo demás lleva nombres o coordenadas de clientes y se queda en el espejo local
(user, 2026-11-23).
"""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from openpyxl import Workbook

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand
from cleaning_agent.adapters.excel_csv import csv_separator, write_csv
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.prospection_map import MAP_PALETTE
from cleaning_agent.adapters.qa_html import QA_CSS, bars, esc, table
from cleaning_agent.adapters.qa_point_map import MapLayer, render_point_map
from cleaning_agent.adapters.xlsx_brand import XlsxStyle, band
from cleaning_agent.adapters.xlsx_brand import table as xlsx_table
from cleaning_agent.domain.datamatch_steps import (
    drop_known_points,
    lodging_rentals,
    out_of_territory,
)
from cleaning_agent.domain.models import (
    ProspectionQaPrepared,
    ProspectionQaResult,
    ProspectionQaReview,
)
from cleaning_agent.domain.prospection_qa import (
    CLIENT_CATEGORY_COLUMNS,
    DATAPLOR_CATEGORY_COLUMNS,
    GEO_RADIUS_M,
    MISTAKE_THRESHOLD,
    SUGGESTIONS,
    Confidence,
    MatchReason,
    Outlet,
    build_idf,
    category_shares,
    excluding_suggestion,
    find_mistakes,
    market_verdict,
    parse_reason,
    pick_column,
    reason_counts,
)

# Columnas del Dataplor que acompañan al no_match enriquecido (no las 60+ del archivo:
# el Excel sería inmanejable); el CSV de prospectos sigue teniendo todas
ENRICHED_COLUMNS = (
    "address",
    "business_category",
    "sub_category",
    "city",
    "state",
)
MISTAKE_COLUMNS = (
    "prospection_outlet_name",
    "prospection_outlet_id",
    "prospection_category",
    "client_base_outlet_name",
    "client_base_outlet_id",
    "client_base_category",
    "distance_meters",
    "name_similarity_pct",
    "tfidf_cosine",
    "geo_score",
    "name_score",
    "combined_score",
    "match_reason",
)
REASON_LABELS = {
    "both_strong": "Nombre y cercanía fuertes",
    "proximity_dominant": "Domina la cercanía",
    "name_dominant": "Domina el nombre",
}
VERDICT_LABELS = {
    "consistent": "Consistente con el mercado",
    "under_matched": "Posible sub-match: revisar el Datamatch",
    "insufficient": "Sin datos suficientes del mercado",
}
EXTRA_CSS = """
.page{max-width:72rem}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:1rem;margin:1.25rem 0}
.stat{background:var(--ka-color-bg-layout);border-radius:var(--ka-radius-box);padding:1rem}
.stat .label{font-size:var(--ka-size-caption);color:var(--ka-color-text-secondary)}
.stat .value{font-family:var(--ka-font-display);font-size:1.6rem;font-weight:var(--ka-weight-semibold)}
.card{margin:1.5rem 0}.card h2{font-family:var(--ka-font-display)}
table{border-collapse:collapse;width:100%;font-size:var(--ka-size-caption)}
th{background:var(--ka-color-key,#E5FF01);color:#141417;text-align:left;padding:.45rem .6rem}
td{border-bottom:1px solid var(--ka-color-bg-layout);padding:.4rem .6rem}
tr.amber td{background:#fff4d6}tr.red td{background:#ffe1e1}
.foot{display:flex;justify-content:space-between;align-items:center;margin-top:2rem;font-size:var(--ka-size-caption)}
"""


# Province column of the cleaned Dataplor (out-of-territory filter, as the prospects)
STATE_COL = "state"


class ProspectionQaError(ValueError):
    """The QA cannot run: missing column or unreadable file."""


def _floats(frame: pl.DataFrame, lat: str, lon: str) -> pl.DataFrame:
    return frame.with_columns(
        pl.col(lat).cast(pl.Float64, strict=False).alias("_lat"),
        pl.col(lon).cast(pl.Float64, strict=False).alias("_lon"),
    ).filter(
        pl.col("_lat").is_between(-90, 90)
        & pl.col("_lon").is_between(-180, 180)
        & ~((pl.col("_lat") == 0) & (pl.col("_lon") == 0))
    )


def _outlets(frame: pl.DataFrame) -> list[Outlet]:
    return [
        Outlet(str(i), str(n or ""), float(a), float(o), str(c or ""))
        for i, n, a, o, c in frame.select(
            "_id", "_name", "_lat", "_lon", "_cat"
        ).iter_rows()
    ]


def _slim(frame: pl.DataFrame, cols: Mapping[str, str], category: str) -> pl.DataFrame:
    """id, nombre, coordenadas y categoría con nombres internos fijos."""
    slim = _floats(frame, cols["latitude"], cols["longitude"]).select(
        pl.col(cols["id"]).cast(pl.Utf8).alias("_id"),
        pl.col(cols["name"]).cast(pl.Utf8).alias("_name"),
        "_lat",
        "_lon",
        (pl.col(category).cast(pl.Utf8) if category else pl.lit("")).alias("_cat"),
    )
    return slim


class FileProspectionQa:
    def __init__(self, project_root: Path, brand: KinBrand) -> None:
        self.project_root = project_root
        self.brand = brand

    def _read(self, path: str, columns: list[str] | None = None) -> pl.DataFrame:
        file = resolve(self.project_root, path)
        sep = csv_separator(file)
        if columns is None:
            return pl.read_csv(file, infer_schema=False, separator=sep)
        available = (
            pl.scan_csv(file, infer_schema=False, separator=sep)
            .collect_schema()
            .names()
        )
        missing = [c for c in columns if c not in available]
        if missing:
            raise ProspectionQaError(f"{Path(path).name} has no column(s) {missing}")
        return pl.read_csv(file, infer_schema=False, separator=sep, columns=columns)

    def prepare(
        self,
        cleaned_file: str,
        match_files: list[str],
        excluded_states: list[str],
        clients_file: str,
        client_cols: Mapping[str, str],
        dataplor_cols: Mapping[str, str],
        out_dir: Path,
    ) -> ProspectionQaPrepared:
        out_dir.mkdir(parents=True, exist_ok=True)
        dp_id = dataplor_cols["id"]
        matched_ids = (
            pl.concat(
                [
                    self._read(f).select(pl.col("id.o").cast(pl.Utf8))
                    for f in match_files
                ]
            )
            .drop_nulls()
            .get_column("id.o")
            .unique()
        )
        cleaned = self._read(cleaned_file)
        if dp_id not in cleaned.columns:
            raise ProspectionQaError(f"cleaned Dataplor has no column {dp_id!r}")
        dp_cat = pick_column(cleaned.columns, DATAPLOR_CATEGORY_COLUMNS)
        # Same population as the prospects: no client, in territory, not a rented flat
        no_match = drop_known_points(cleaned, dp_id, matched_ids)
        if excluded_states and STATE_COL in no_match.columns:
            no_match = no_match.filter(
                ~out_of_territory(no_match.get_column(STATE_COL), excluded_states)
            )
        no_match = no_match.filter(~lodging_rentals(no_match))
        match = cleaned.filter(pl.col(dp_id).is_in(matched_ids.implode()))

        header = (
            pl.scan_csv(
                resolve(self.project_root, clients_file),
                infer_schema=False,
                separator=csv_separator(resolve(self.project_root, clients_file)),
            )
            .collect_schema()
            .names()
        )
        cl_cat = pick_column(header, CLIENT_CATEGORY_COLUMNS)
        wanted = [client_cols[k] for k in ("id", "name", "latitude", "longitude")]
        clients = self._read(
            clients_file, list(dict.fromkeys([*wanted, *([cl_cat] if cl_cat else [])]))
        )

        nm = _slim(no_match, dataplor_cols, dp_cat)
        m = _slim(match, dataplor_cols, dp_cat)
        cl = _slim(clients, client_cols, cl_cat)
        idf = build_idf(
            [
                *nm.get_column("_name").to_list(),
                *m.get_column("_name").to_list(),
                *cl.get_column("_name").to_list(),
            ]
        )
        mistakes = find_mistakes(_outlets(nm), _outlets(cl), idf)

        # Local only: the enriched file and the maps read them back in ``build``
        no_match.write_parquet(out_dir / "_no_match.parquet")
        m.write_parquet(out_dir / "_match.parquet")
        cl.write_parquet(out_dir / "_clients.parquet")
        mistakes_file = out_dir / "mistakes_report.csv"
        write_csv(
            pl.DataFrame(
                [
                    [
                        x.prospect.name,
                        x.prospect.id,
                        x.prospect.category,
                        x.client.name,
                        x.client.id,
                        x.client.category,
                        round(x.distance_m, 1),
                        round(x.fuzzy_pct, 1),
                        round(x.tfidf, 4),
                        round(x.geo, 4),
                        round(x.name, 4),
                        round(x.combined, 4),
                        x.reason,
                    ]
                    for x in mistakes
                ],
                schema=list(MISTAKE_COLUMNS),
                orient="row",
            ),
            mistakes_file,
        )
        # Pair coordinates for the mistakes map (local only)
        pl.DataFrame(
            {
                "p_lat": [x.prospect.lat for x in mistakes],
                "p_lon": [x.prospect.lon for x in mistakes],
                "c_lat": [x.client.lat for x in mistakes],
                "c_lon": [x.client.lon for x in mistakes],
            },
            schema={k: pl.Float64 for k in ("p_lat", "p_lon", "c_lat", "c_lon")},
        ).write_parquet(out_dir / "_pairs.parquet")

        shares = category_shares(
            m.get_column("_cat").to_list(), nm.get_column("_cat").to_list()
        )
        client_counts = (
            cl.group_by("_cat").len().sort("len", descending=True).iter_rows()
            if cl_cat
            else iter([])
        )
        categories_file = out_dir / "categories_for_review.json"
        categories_file.write_text(
            json.dumps(
                {
                    "prospection_category_column": dp_cat,
                    "client_category_column": cl_cat,
                    "prospection": [
                        {
                            "category": s.category,
                            "total": s.total,
                            "match": s.match,
                            "no_match": s.no_match,
                        }
                        for s in shares
                    ],
                    "client": [
                        {"category": c or "(sin categoría)", "count": n}
                        for c, n in client_counts
                    ],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        return ProspectionQaPrepared(
            out_dir=str(out_dir),
            match=m.height,
            no_match=nm.height,
            clients=cl.height,
            mistakes=len(mistakes),
            by_reason=reason_counts(mistakes),
            prospection_category_col=dp_cat,
            client_category_col=cl_cat,
            categories_file=str(categories_file),
            mistakes_file=str(mistakes_file),
            mistake_ids={x.prospect.id: x.reason for x in mistakes},
        )

    def build(
        self,
        prepared: ProspectionQaPrepared,
        review: ProspectionQaReview,
        client: str,
        country: str,
        dataplor_cols: Mapping[str, str],
    ) -> ProspectionQaResult:
        out = Path(prepared.out_dir)
        no_match = pl.read_parquet(out / "_no_match.parquet")
        match = pl.read_parquet(out / "_match.parquet")
        clients = pl.read_parquet(out / "_clients.parquet")
        pairs = pl.read_parquet(out / "_pairs.parquet")
        mistakes = self._read(prepared.mistakes_file)
        nm = _slim(no_match, dataplor_cols, prepared.prospection_category_col)

        mapped: dict[str, tuple[str, Confidence]] = {
            m.prospection_category: (m.client_category, m.confidence)
            for m in review.category_mapping
        }
        non_beverage = {c.category for c in review.non_beverage}
        client_categories = set(clients.get_column("_cat").drop_nulls().to_list())
        reasons: dict[str, MatchReason] = {}
        for key, value in prepared.mistake_ids.items():
            reason = parse_reason(value)
            if reason is not None:
                reasons[key] = reason
        shares = category_shares(
            match.get_column("_cat").to_list(), nm.get_column("_cat").to_list()
        )
        enriched, suggestions = self._enriched_xlsx(
            no_match,
            dataplor_cols,
            prepared.prospection_category_col,
            reasons,
            mapped,
            client_categories,
            non_beverage,
            out / "no_match_enriched.xlsx",
        )
        files = [
            self._mapping_xlsx(review, out / "category_mapping.xlsx"),
            self._issues_xlsx(review, shares, out / "category_issues.xlsx"),
            enriched,
        ]
        files += self._maps(out, client, match, nm, clients, mistakes, pairs)
        total = prepared.match + prepared.no_match
        rate = round(100 * prepared.match / total, 2) if total else 0.0
        bench = review.benchmark
        verdict = market_verdict(rate, bench.penetration_pct if bench else None)
        summary: dict[str, Any] = {
            "clientes_base": prepared.clients,
            "match": prepared.match,
            "no_match": prepared.no_match,
            "tasa_match_pct": rate,
            "falsos_negativos": prepared.mistakes,
            "falsos_negativos_pct_no_match": round(
                100 * prepared.mistakes / prepared.no_match, 2
            )
            if prepared.no_match
            else 0.0,
            "por_motivo": prepared.by_reason,
            "categorias_prospeccion": len(shares),
            "categorias_no_bebida": len(non_beverage),
            "sugerencias_exclusion": suggestions,
            "mercado": bench.country if bench else country,
            "penetracion_pct": bench.penetration_pct if bench else None,
            "veredicto": verdict,
            "umbral": MISTAKE_THRESHOLD,
            "radio_m": GEO_RADIUS_M,
        }
        report = out / f"prospection_qa_report_{client}.html"
        report.write_text(
            self._report(client, country, prepared, review, shares, mistakes, summary),
            encoding="utf-8",
        )
        return ProspectionQaResult(
            report=str(report), local_files=[str(f) for f in files], summary=summary
        )

    # ---- outputs ---------------------------------------------------------------

    def _book(self, title: str, eyebrow: str) -> tuple[Workbook, XlsxStyle]:
        wb = Workbook()
        style = XlsxStyle(self.brand)
        ws = wb.active
        assert ws is not None  # a new workbook always has its first sheet
        band(ws, style, eyebrow, title, 6)
        return wb, style

    def _mapping_xlsx(self, review: ProspectionQaReview, path: Path) -> Path:
        wb, style = self._book(
            "Cruce de categorías Dataplor ↔ clientes", "QA de prospección"
        )
        ws = wb.active
        assert ws is not None
        rows = [
            [m.prospection_category, m.client_category, m.confidence, m.notes]
            for m in review.category_mapping
        ]
        xlsx_table(
            ws,
            style,
            4,
            ["prospection_category", "client_base_category", "confidence", "notes"],
            rows,
        )
        for col, width in zip("BCDE", (40, 40, 12, 60), strict=True):
            ws.column_dimensions[col].width = width
        wb.save(path)
        return path

    def _issues_xlsx(
        self, review: ProspectionQaReview, shares: list[Any], path: Path
    ) -> Path:
        wb, style = self._book("Categorías que no venden bebidas", "QA de prospección")
        ws = wb.active
        assert ws is not None
        by_cat = {s.category: s for s in shares}
        rows: list[list[Any]] = [
            [
                c.category,
                by_cat[c.category].total if c.category in by_cat else 0,
                by_cat[c.category].no_match if c.category in by_cat else 0,
                c.reason,
            ]
            for c in review.non_beverage
        ] or [["No non-beverage categories detected.", 0, 0, ""]]
        xlsx_table(
            ws, style, 4, ["category", "outlet_count", "no_match_count", "reason"], rows
        )
        for col, width in zip("BCDE", (40, 14, 16, 60), strict=True):
            ws.column_dimensions[col].width = width
        wb.save(path)
        return path

    def _enriched_xlsx(
        self,
        no_match: pl.DataFrame,
        cols: Mapping[str, str],
        category_col: str,
        reasons: Mapping[str, MatchReason],
        mapped: Mapping[str, tuple[str, Confidence]],
        client_categories: set[str],
        non_beverage: set[str],
        path: Path,
    ) -> tuple[Path, dict[str, int]]:
        keep = list(
            dict.fromkeys(
                [
                    cols["id"],
                    cols["name"],
                    *[c for c in ENRICHED_COLUMNS if c in no_match.columns],
                    cols["latitude"],
                    cols["longitude"],
                ]
            )
        )
        frame = no_match.select(keep)
        cats = (
            no_match.get_column(category_col).cast(pl.Utf8).to_list()
            if category_col
            else [""] * no_match.height
        )
        ids = no_match.get_column(cols["id"]).cast(pl.Utf8).to_list()
        suggestion = [
            excluding_suggestion(i, c, reasons, mapped, client_categories, non_beverage)
            for i, c in zip(ids, cats, strict=True)
        ]
        target = [mapped.get(c or "", ("", "")) for c in cats]
        frame = frame.with_columns(
            pl.Series("excluding_suggestion", suggestion),
            pl.Series("mapped_category", [t[0] for t in target]),
            pl.Series(
                "mapped_category_confidence", [t[1] if t[0] else "" for t in target]
            ),
        )
        order = {s: i for i, s in enumerate(SUGGESTIONS)}
        frame = (
            frame.with_columns(
                pl.col("excluding_suggestion")
                .replace_strict(order, default=len(order), return_dtype=pl.Int64)
                .alias("_o")
            )
            .sort(["_o", cols["name"]], nulls_last=True)
            .drop("_o")
        )
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("no_match")
        ws.append(frame.columns)
        for row in frame.iter_rows():
            ws.append(list(row))
        wb.save(path)
        return path, {s: suggestion.count(s) for s in SUGGESTIONS}

    def _maps(
        self,
        out: Path,
        client: str,
        match: pl.DataFrame,
        no_match: pl.DataFrame,
        clients: pl.DataFrame,
        mistakes: pl.DataFrame,
        pairs: pl.DataFrame,
    ) -> list[Path]:
        def layer(frame: pl.DataFrame, label: str, color: str, source: str) -> MapLayer:
            rows = frame.select("_id", "_name", "_lat", "_lon", "_cat").iter_rows()
            ly = MapLayer(label, color, 5)
            for i, n, a, o, c in rows:
                ly.points.append((a, o))
                ly.info.append(
                    [
                        ("Nombre", n or ""),
                        ("ID", i),
                        ("Categoría", c or ""),
                        ("Origen", source),
                    ]
                )
            return ly

        hexes = MAP_PALETTE["hex"]
        overview = out / f"prospection_qa_map_overview_{client}.html"
        overview.write_text(
            render_point_map(
                self.brand,
                "QA de prospección · vista general",
                f"{client} · clientes, match y no_match",
                [
                    layer(
                        clients,
                        "Clientes de la base",
                        str(MAP_PALETTE["high"]),
                        "base de clientes",
                    ),
                    layer(
                        match,
                        "Dataplor con match",
                        str(MAP_PALETTE["moderate"]),
                        "Dataplor · match",
                    ),
                    layer(
                        no_match,
                        "Dataplor sin match (prospectos)",
                        str(hexes[1]),
                        "Dataplor · no_match",
                    ),
                ],
            ),
            encoding="utf-8",
        )
        p_layer = MapLayer("Prospecto (no_match) que parece cliente", str(hexes[3]), 7)
        c_layer = MapLayer("Cliente de la base", str(hexes[0]), 7)
        for row, pair in zip(
            mistakes.iter_rows(named=True), pairs.iter_rows(), strict=True
        ):
            common = [
                ("Distancia (m)", str(row["distance_meters"])),
                ("Similitud nombre (%)", str(row["name_similarity_pct"])),
                ("Score combinado", str(row["combined_score"])),
                (
                    "Motivo",
                    REASON_LABELS.get(
                        str(row["match_reason"]), str(row["match_reason"])
                    ),
                ),
            ]
            p_layer.points.append((pair[0], pair[1]))
            p_layer.info.append(
                [
                    ("Nombre", str(row["prospection_outlet_name"])),
                    ("ID Dataplor", str(row["prospection_outlet_id"])),
                    ("Categoría", str(row["prospection_category"] or "")),
                    *common,
                ]
            )
            c_layer.points.append((pair[2], pair[3]))
            c_layer.info.append(
                [
                    ("Nombre", str(row["client_base_outlet_name"])),
                    ("ID cliente", str(row["client_base_outlet_id"])),
                    ("Categoría", str(row["client_base_category"] or "")),
                    *common,
                ]
            )
        errors = out / f"prospection_qa_map_mistakes_{client}.html"
        errors.write_text(
            render_point_map(
                self.brand,
                "QA de prospección · falsos negativos",
                f"{client} · {len(p_layer.points):,} pares".replace(",", "."),
                [c_layer, p_layer],
                [
                    (float(a), float(b), float(c), float(d))
                    for a, b, c, d in pairs.iter_rows()
                ],
            ),
            encoding="utf-8",
        )
        return [overview, errors]

    def _report(
        self,
        client: str,
        country: str,
        prepared: ProspectionQaPrepared,
        review: ProspectionQaReview,
        shares: list[Any],
        mistakes: pl.DataFrame,
        s: Mapping[str, Any],
    ) -> str:
        """Reporte agregado: conteos, tasas, categorías e ids; nunca nombres ni coordenadas."""

        def n(v: int) -> str:
            return f"{v:,}".replace(",", ".")

        stats = "".join(
            f'<div class="stat"><div class="label">{esc(k)}</div><div class="value">{esc(v)}</div></div>'
            for k, v in (
                ("Clientes en la base", n(prepared.clients)),
                ("Dataplor con match", n(prepared.match)),
                ("Prospectos (no_match)", n(prepared.no_match)),
                ("Tasa de match", f"{s['tasa_match_pct']}%".replace(".", ",")),
                ("Falsos negativos", n(prepared.mistakes)),
            )
        )
        total = prepared.match + prepared.no_match
        split = bars(
            [
                ("Con match", prepared.match),
                ("Sin match (prospectos)", prepared.no_match),
            ],
            total,
        )
        reasons = bars(
            [(REASON_LABELS[k], v) for k, v in prepared.by_reason.items()],
            max(prepared.mistakes, 1),
        )
        cat_rows = "".join(
            f'<tr class="{"red" if r.no_match_pct > 75 else "amber" if r.no_match_pct > 50 else ""}">'
            f"<td>{esc(r.category)}</td><td>{n(r.total)}</td><td>{n(r.match)}</td><td>{n(r.no_match)}</td>"
            f"<td>{str(r.no_match_pct).replace('.', ',')}%</td></tr>"
            for r in shares
        )
        categories = (
            "<table><thead><tr><th>Categoría</th><th>Total</th><th>Match</th><th>No match</th>"
            f"<th>% no match</th></tr></thead><tbody>{cat_rows}</tbody></table>"
        )
        non_bev = (
            table(
                [(c.category, c.reason) for c in review.non_beverage],
                ("Categoría", "Por qué no vende bebidas"),
            )
            if review.non_beverage
            else "<p>Ninguna categoría marcada como no bebida.</p>"
        )
        mapping = (
            table(
                [
                    (m.prospection_category, m.client_category or "—", m.confidence)
                    for m in review.category_mapping
                ],
                ("Categoría Dataplor", "Categoría en la base", "Confianza"),
            )
            if review.category_mapping
            else "<p>Sin cruce de categorías.</p>"
        )
        top = table(
            [
                (
                    r["prospection_outlet_id"],
                    r["client_base_outlet_id"],
                    r["distance_meters"],
                    r["name_similarity_pct"],
                    r["combined_score"],
                    REASON_LABELS.get(str(r["match_reason"]), ""),
                )
                for r in mistakes.head(10).iter_rows(named=True)
            ],
            (
                "ID Dataplor",
                "ID cliente",
                "Distancia (m)",
                "Similitud nombre %",
                "Score combinado",
                "Motivo",
            ),
        )
        suggestions = table(
            [(k, n(v)) for k, v in s["sugerencias_exclusion"].items()],
            ("Sugerencia", "Prospectos"),
        )
        bench = review.benchmark
        sources = (
            "<ul>"
            + "".join(
                f'<li><a href="{esc(x.url)}">{esc(x.title)}</a></li>'
                for x in bench.sources
            )
            + "</ul>"
            if bench and bench.sources
            else ""
        )
        market = (
            f"<p><b>Mercado:</b> {esc(bench.country)} · <b>Penetración encontrada:</b> "
            f"{esc(bench.penetration_text or 'sin cifra confiable')}</p><p>{esc(bench.paragraph)}</p>{sources}"
            if bench
            else f"<p>Mercado: {esc(country.upper())}. No se hizo el benchmark de mercado.</p>"
        )
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA de prospección {esc(client)}</title>
<style>{self.brand.head_css}{PAGE_CSS}{QA_CSS}{
            EXTRA_CSS
        }</style></head><body><div class="page">
<div class="top">{
            self.brand.logo(LOGO_FORMAL_LIGHT)
        }<span class="ka-site">kinanalytics.com</span></div>
<section class="band"><p class="eyebrow">QA de prospección · {esc(client)} · {
            esc(country.upper())
        }</p>
<h1>¿Quedaron clientes entre los prospectos?</h1>
<p class="sub">Falso negativo = prospecto a menos de {
            int(GEO_RADIUS_M)
        } m de un cliente con nombre
distintivo parecido (score combinado 0,4·cercanía + 0,6·nombre ≥ {
            str(MISTAKE_THRESHOLD).replace(".", ",")
        }).
Este reporte trae solo conteos e ids; los nombres y mapas quedan en el espejo local.</p></section>
<div class="stats">{stats}</div>
<section class="card"><h2>1 · Resumen</h2>{split}
<p>{n(prepared.mistakes)} prospectos ({
            str(s["falsos_negativos_pct_no_match"]).replace(".", ",")
        }% del no_match)
parecen clientes de la base. Veredicto de mercado: <b>{
            esc(VERDICT_LABELS[s["veredicto"]])
        }</b>.</p></section>
<section class="card"><h2>2 · Bases comparadas</h2>{
            table(
                [
                    ("Puntos", n(prepared.clients), n(total)),
                    (
                        "Columna de categoría",
                        prepared.client_category_col or "—",
                        prepared.prospection_category_col or "—",
                    ),
                    (
                        "Categorías únicas",
                        n(
                            len(
                                json.loads(
                                    Path(prepared.categories_file).read_text(
                                        encoding="utf-8"
                                    )
                                )["client"]
                            )
                        ),
                        n(len(shares)),
                    ),
                    ("Con match", n(prepared.match), n(prepared.match)),
                ],
                ("", "Base de clientes", "Dataplor"),
            )
        }</section>
<section class="card"><h2>3 · Categorías</h2><p>Ámbar: más de 50% sin match · rojo: más de 75%.</p>{
            categories
        }
<h3>No venden bebidas</h3>{non_bev}<h3>Cruce con la base de clientes</h3>{
            mapping
        }</section>
<section class="card"><h2>4 · Falsos negativos</h2>{
            reasons
        }<h3>Los 10 pares más fuertes</h3>{top}
<h3>Sugerencias sobre los prospectos</h3>{suggestions}</section>
<section class="card"><h2>5 · Contexto de mercado</h2>{market}
<p><b>Tasa de match observada:</b> {str(s["tasa_match_pct"]).replace(".", ",")}% ·
<b>Veredicto:</b> {esc(VERDICT_LABELS[s["veredicto"]])}</p></section>
<div class="foot">{self.brand.logo(LOGO_FORMAL_LIGHT)}<span>Generado {generated} · {
            esc(Path(prepared.categories_file).parent.name)
        }</span></div>
</div></body></html>
"""
