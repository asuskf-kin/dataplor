"""GoldPackagePort adapter: builds the gold delivery package of a prospecting run.

Modelled on the approved Golfo package (KO / BOTTLER results, opportunity Excel,
maps and deck). Inputs are local files of the DWH mirror:

- the priorización deliverable (scored prospects, 36 columns);
- the bottler's client base, read only for the columns the BOTTLER version needs
  (id, name, region, jefatura, city and coordinates): its rows never reach a log,
  the KO files or the Excel, which only carry counts;
- the Andina territory GeoJSON (outline of the offline map, optional).
"""

import json
import logging
from pathlib import Path
from typing import Any

import h3
import numpy as np
import polars as pl
from openpyxl import Workbook
from openpyxl.styles import Alignment
from sklearn.neighbors import BallTree

from cleaning_agent.adapters.brand import KinBrand
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.prospecting_deck import render_deck
from cleaning_agent.adapters.prospection_map import render_map
from cleaning_agent.adapters.xlsx_brand import XlsxStyle, band, section, table
from cleaning_agent.domain.gold_package import (
    HEX_RESOLUTIONS,
    KO_COLUMNS,
    bottler_columns,
    coordinates_swapped,
    deck_figures,
    opportunity_by,
    opportunity_summary,
    with_priority,
)
from cleaning_agent.domain.models import GoldPackageRequest, GoldPackageResult

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_008.8


class GoldPackageError(ValueError):
    """The package cannot be built: missing column or unusable client coordinates."""


class FileGoldPackage:
    def __init__(
        self, project_root: Path, brand: KinBrand, deck_template: Path
    ) -> None:
        self.project_root = project_root
        self.brand = brand
        self.deck_template = deck_template

    # --- inputs --------------------------------------------------------------------
    def _clients(
        self, request: GoldPackageRequest, scored: pl.DataFrame
    ) -> tuple[pl.DataFrame, bool]:
        """Client coordinates (fixed when lat/lon come swapped) and whether they were."""
        cols = request.client_columns
        wanted = [cols.id, cols.latitude, cols.longitude, *cols.reference, cols.city]
        path = resolve(self.project_root, request.clients_file)
        available = pl.scan_csv(path, infer_schema=False).collect_schema().names()
        missing = [c for c in dict.fromkeys(wanted) if c not in available]
        if missing:
            raise GoldPackageError(f"client base has no column(s) {missing}")
        clients = pl.read_csv(
            path, infer_schema=False, columns=list(dict.fromkeys(wanted))
        )
        lat = pl.col(cols.latitude).cast(pl.Float64, strict=False)
        lon = pl.col(cols.longitude).cast(pl.Float64, strict=False)
        parsed = clients.with_columns(lat.alias("_lat"), lon.alias("_lon")).drop_nulls(
            ["_lat", "_lon"]
        )
        p_lat: list[float] = (
            scored.get_column("latitude")
            .cast(pl.Float64, strict=False)
            .drop_nulls()
            .to_list()
        )
        p_lon: list[float] = (
            scored.get_column("longitude")
            .cast(pl.Float64, strict=False)
            .drop_nulls()
            .to_list()
        )
        if not p_lat or not p_lon:
            raise GoldPackageError("scored prospects have no coordinates")
        swapped = coordinates_swapped(
            parsed.get_column("_lat").to_list(),
            parsed.get_column("_lon").to_list(),
            (min(p_lat), max(p_lat)),
            (min(p_lon), max(p_lon)),
        )
        if swapped:
            logger.warning(
                "Client base %s has latitude and longitude swapped: exchanged for the distances",
                Path(request.clients_file).name,
            )
            parsed = parsed.with_columns(
                pl.col("_lon").alias("_lat"), pl.col("_lat").alias("_lon")
            )
        valid = parsed.filter(
            pl.col("_lat").is_between(-90, 90)
            & pl.col("_lon").is_between(-180, 180)
            & ~((pl.col("_lat") == 0) & (pl.col("_lon") == 0))
        )
        if valid.is_empty():
            raise GoldPackageError("client base has no valid coordinates")
        return valid, swapped

    @staticmethod
    def _nearest_client(
        prospects: pl.DataFrame, clients: pl.DataFrame, reference: list[str]
    ) -> pl.DataFrame:
        """Nearest current client of each prospect (haversine) and its distance."""
        tree = BallTree(
            np.radians(clients.select("_lat", "_lon").to_numpy()), metric="haversine"
        )
        points = np.radians(
            prospects.select(
                pl.col("latitude").cast(pl.Float64),
                pl.col("longitude").cast(pl.Float64),
            ).to_numpy()
        )
        distance, index = tree.query(points, k=1)
        rows: list[int] = [int(i) for i in index[:, 0]]
        nearest: pl.DataFrame = clients.select(reference)[rows]
        nearest = nearest.rename({c: f"ref_{c}_cercano" for c in reference})
        combined: pl.DataFrame = pl.concat(
            [
                prospects,
                nearest,
                pl.DataFrame(
                    {"dist_ref_m": (distance[:, 0] * EARTH_RADIUS_M).round(1)}
                ),
            ],
            how="horizontal",
        )
        return combined

    @staticmethod
    def _hexes(prospects: pl.DataFrame) -> pl.DataFrame:
        lat = prospects.get_column("latitude").cast(pl.Float64).to_list()
        lon = prospects.get_column("longitude").cast(pl.Float64).to_list()
        return prospects.with_columns(
            pl.Series(
                f"hex_{r}",
                [h3.latlng_to_cell(a, b, r) for a, b in zip(lat, lon, strict=True)],
            )
            for r in HEX_RESOLUTIONS
        )

    # --- build ---------------------------------------------------------------------
    def build(self, request: GoldPackageRequest) -> GoldPackageResult:
        scored = pl.read_csv(
            resolve(self.project_root, request.scored_file), infer_schema=False
        )
        needed = [
            "dataplor_id",
            "latitude",
            "longitude",
            "probability_existence_cat",
            "city",
            "state",
            "business_category",
        ]
        missing = [c for c in needed if c not in scored.columns]
        if missing:
            raise GoldPackageError(f"scored prospects have no column(s) {missing}")
        clients, swapped = self._clients(request, scored)
        reference = request.client_columns.reference
        ref_cols = [f"ref_{c}_cercano" for c in reference]
        prospects = with_priority(
            self._hexes(self._nearest_client(scored, clients, reference))
        )

        out = request.out_dir
        names = request.names()
        ko_dir, bottler_dir = out / "results_ko", out / "results_bottler"
        for folder in (out, ko_dir, bottler_dir):
            folder.mkdir(parents=True, exist_ok=True)

        bottler_csv = bottler_dir / names["bottler_csv"]
        ko_csv = ko_dir / names["ko_csv"]
        prospects.select(bottler_columns(scored.columns, ref_cols)).write_csv(
            bottler_csv, include_bom=True
        )
        prospects.select(KO_COLUMNS).write_csv(ko_csv, include_bom=True)

        city = request.client_columns.city
        clients_by_city = {
            str(k).strip().lower(): int(v)
            for k, v in clients.group_by(city).len().iter_rows()
            if k is not None
        }
        summary = opportunity_summary(prospects, request.clients_total)
        by_city = opportunity_by(prospects, "city", clients_by_city)
        by_state = opportunity_by(prospects, "state")
        xlsx = out / names["xlsx"]
        _write_opportunity_xlsx(xlsx, self.brand, request, summary, by_city, by_state)

        territory = (
            _territory(resolve(self.project_root, request.territory_geojson))
            if request.territory_geojson
            else []
        )
        ko_map = ko_dir / names["ko_map"]
        bottler_map = bottler_dir / names["bottler_map"]
        title = (
            f"Prospección digital — {request.bottler_label} ({request.country_label})"
        )
        for target, audience in ((ko_map, "ko"), (bottler_map, "bottler")):
            target.write_text(
                render_map(
                    prospects,
                    clients,
                    territory,
                    self.brand,
                    title,
                    audience,
                    request.client_columns,
                ),
                encoding="utf-8",
            )

        figures = deck_figures(
            prospects, request.clients_total, request.dataplor_total, request.matched
        )
        deck = out / names["deck"]
        render_deck(self.deck_template, deck, figures, request, prospects, self.brand)

        logger.info(
            "Gold package %s: %s prospects, %s High/Moderate (%s inside the routes)",
            request.run_name,
            f"{prospects.height:,}",
            f"{figures['hm_total']:,}",
            f"{figures['hm_inside']:,}",
        )
        ko_written = pl.scan_csv(ko_csv, infer_schema=False)
        return GoldPackageResult(
            root=[str(xlsx), str(deck)],
            ko=[str(ko_csv), str(ko_map)],
            bottler=[str(bottler_csv), str(bottler_map)],
            rows=scored.height,
            ko_rows=int(ko_written.select(pl.len()).collect().item()),
            bottler_rows=int(
                pl.scan_csv(bottler_csv, infer_schema=False)
                .select(pl.len())
                .collect()
                .item()
            ),
            ko_column_names=ko_written.collect_schema().names(),
            bottler_columns=len(bottler_columns(scored.columns, ref_cols)),
            prioritized=int(prospects.get_column("prioridad").is_not_null().sum()),
            client_coordinates_swapped=swapped,
            figures=figures,
        )


def _territory(path: Path) -> list[list[list[float]]]:
    """Outer rings of the territory GeoJSON as [[lat, lon], ...] (rounded, light)."""
    if not path.is_file():
        return []
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    rings: list[list[list[float]]] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        polygons = geometry.get("coordinates", [])
        if geometry.get("type") == "Polygon":
            polygons = [polygons]
        for polygon in polygons:
            if polygon:
                ring = polygon[0]
                step = max(1, len(ring) // 2000)  # keep the outline light
                rings.append([[round(p[1], 5), round(p[0], 5)] for p in ring[::step]])
    return rings


def _write_opportunity_xlsx(
    target: Path,
    brand: KinBrand,
    request: GoldPackageRequest,
    summary: list[dict[str, Any]],
    by_city: list[dict[str, Any]],
    by_state: list[dict[str, Any]],
) -> None:
    """Golfo's 'Análisis de Oportunidad': Dataplor vs the bottler's client base."""
    style = XlsxStyle(brand)
    wb = Workbook()
    ws = wb.active
    if ws is None:  # a new Workbook always has one sheet
        ws = wb.create_sheet()
    ws.title = "Resumen_Ejecutivo"
    eyebrow = "On Premise · Dataplor vs Bottler"
    row = band(
        ws,
        style,
        eyebrow,
        f"Resumen ejecutivo · {request.bottler_label} {request.country_label}",
        6,
    )
    ws.cell(
        row,
        2,
        "Oportunidad = prospectos Dataplor que no son clientes del bottler. Universo = oportunidad + clientes actuales.",
    ).font = style.muted
    row = section(
        ws,
        style,
        row + 2,
        "Oportunidad total y por área (dentro = a 300 m o menos de un cliente)",
    )
    table(
        ws,
        style,
        row,
        ["Nivel", "Universo", "Clientes bottler", "Oportunidad", "% Oportunidad"],
        [
            [
                s["nivel"].replace("Total ", f"Total {request.bottler_label} ").strip(),
                s["universo"],
                s["bottler"],
                s["oportunidad"],
                s["pct"],
            ]
            for s in summary
        ],
    )
    for letter, width in zip("ABCDEF", (2, 34, 14, 16, 14, 14), strict=True):
        ws.column_dimensions[letter].width = width

    sheets = (
        (
            "Por_Ciudad",
            "Oportunidad por ciudad",
            [
                "Ciudad",
                "Universo",
                "Clientes bottler",
                "Oportunidad",
                "% Oportunidad",
                "Dentro",
                "Fuera",
                "% Acumulado",
            ],
            [
                [
                    r["city"],
                    r["universo"],
                    r["bottler"],
                    r["oportunidad"],
                    r["pct"],
                    r["dentro"],
                    r["fuera"],
                    r["pct_acumulado"],
                ]
                for r in by_city
            ],
        ),
        (
            "Por_Provincia",
            "Oportunidad por provincia",
            ["Provincia", "Oportunidad", "Dentro", "Fuera", "% Acumulado"],
            [
                [
                    r["state"],
                    r["oportunidad"],
                    r["dentro"],
                    r["fuera"],
                    r["pct_acumulado"],
                ]
                for r in by_state
            ],
        ),
    )
    for title, heading, headers, rows in sheets:
        sheet = wb.create_sheet(title)
        start = band(sheet, style, eyebrow, heading, len(headers))
        table(sheet, style, start, headers, rows, first_col=1)
        sheet.column_dimensions["A"].width = 32
        for i in range(1, len(headers)):
            sheet.column_dimensions[chr(ord("A") + i)].width = 15
        for line in sheet.iter_rows(min_row=start + 1, max_row=start + len(rows)):
            for cell in line[1:]:
                if isinstance(cell.value, int):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right")
    wb.save(target)
