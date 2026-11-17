"""GoldPackagePort adapter: builds the gold delivery package of a prospecting run.

Modelled on the approved Golfo package (KO / BOTTLER results, opportunity Excel,
maps and deck). Inputs are local files of the DWH mirror:

- the priorización deliverable (scored prospects, 36 columns);
- the bottler's client base, read only for the columns the BOTTLER version needs
  (id, name, region, jefatura, city and coordinates): its rows never reach a log,
  the KO files or the Excel, which only carry counts;
- the Andina territory GeoJSON (territory of the maps, optional; when its features name
  their regions, each prospect gets the ``region`` column).

CSVs follow the approved Golfo files: UTF-8 with BOM, comma, CRLF, quotes only where a
field needs them, and no line break inside a field (Excel and naive readers would split
the row).
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import h3
import numpy as np
import polars as pl
from openpyxl import Workbook
from openpyxl.styles import Alignment
from shapely.geometry import Point, shape
from sklearn.neighbors import BallTree

from cleaning_agent.adapters.brand import KinBrand
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.prospecting_deck import render_deck
from cleaning_agent.adapters.prospection_map import render_map
from cleaning_agent.adapters.xlsx_brand import XlsxStyle, band, section, table
from cleaning_agent.domain.gold_package import (
    HEX_RESOLUTIONS,
    REGION,
    bottler_columns,
    coordinates_swapped,
    deck_figures,
    ko_columns,
    opportunity_by,
    opportunity_summary,
    with_poi_ref,
    with_priority,
)
from cleaning_agent.domain.models import GoldPackageRequest, GoldPackageResult

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_008.8
# Feature properties that name a region in the territory GeoJSON
REGION_KEYS = ("region", "Region", "REGION", "region_name", "nombre_region")


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
    def _prepare(
        self, request: GoldPackageRequest
    ) -> tuple[pl.DataFrame, pl.DataFrame, bool, pl.DataFrame]:
        """Scored prospects, clients, swapped flag and prospects with priority + hexes."""
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
        prospects = with_poi_ref(
            with_priority(
                self._hexes(
                    self._nearest_client(
                        scored, clients, request.client_columns.reference
                    )
                )
            )
        )
        regions = (
            _regions(resolve(self.project_root, request.territory_geojson), prospects)
            if request.territory_geojson
            else None
        )
        if regions is not None:
            prospects = prospects.with_columns(pl.Series(REGION, regions))
        return scored, clients, swapped, prospects

    def build(self, request: GoldPackageRequest) -> GoldPackageResult:
        scored, clients, swapped, prospects = self._prepare(request)
        ref_cols = [f"ref_{c}_cercano" for c in request.client_columns.reference]

        out = request.out_dir
        names = request.names()
        ko_dir, bottler_dir = out / "results_ko", out / "results_bottler"
        for folder in (out, ko_dir, bottler_dir):
            folder.mkdir(parents=True, exist_ok=True)

        bottler_csv = bottler_dir / names["bottler_csv"]
        ko_csv = ko_dir / names["ko_csv"]
        has_region = REGION in prospects.columns
        write_csv(
            prospects.select(bottler_columns(scored.columns, ref_cols, has_region)),
            bottler_csv,
        )
        write_csv(prospects.select(ko_columns(has_region)), ko_csv)

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

        ko_map, bottler_map = self._write_maps(request, prospects, clients)

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
            bottler_columns=len(
                bottler_columns(scored.columns, ref_cols, REGION in prospects.columns)
            ),
            prioritized=int(prospects.get_column("prioridad").is_not_null().sum()),
            client_coordinates_swapped=swapped,
            figures=figures,
        )

    def _write_maps(
        self,
        request: GoldPackageRequest,
        prospects: pl.DataFrame,
        clients: pl.DataFrame,
    ) -> tuple[Path, Path]:
        """KO map (no names) and BOTTLER map (names) under results_ko/ and results_bottler/."""
        names = request.names()
        ko_map = request.out_dir / "results_ko" / names["ko_map"]
        bottler_map = request.out_dir / "results_bottler" / names["bottler_map"]
        territory = (
            _territory(resolve(self.project_root, request.territory_geojson))
            if request.territory_geojson
            else []
        )
        title = (
            f"Prospección digital — {request.bottler_label} ({request.country_label})"
        )
        for target, audience in ((ko_map, "ko"), (bottler_map, "bottler")):
            target.parent.mkdir(parents=True, exist_ok=True)
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
        return ko_map, bottler_map

    def build_maps(self, request: GoldPackageRequest) -> list[str]:
        """Only the two maps of an existing package (after a map change).

        The CSVs, Excel and deck are not touched, so files already uploaded keep
        their size and MD5. The client base is read the same way as in build().
        """
        _, clients, _, prospects = self._prepare(request)
        ko_map, bottler_map = self._write_maps(request, prospects, clients)
        logger.info("Maps rebuilt for %s in %s", request.run_name, request.out_dir)
        return [str(ko_map), str(bottler_map)]


def flat_text(value: str | None) -> str | None:
    """One CSV field that never needs quotes: no comma, double quote or line break.

    Dataplor sends JSON inside some columns (historical_*_scores, place_attributes).
    Quoted and with doubled quotes it is valid CSV, but LibreOffice and Excel with a
    Spanish locale often split it at every comma and shift the rest of the row (the
    hours ended up under other headers). JSON becomes readable flat text; free text
    keeps its words with commas turned into " - " and double quotes into '.
    """
    if value is None:
        return None
    text = value.strip()
    if text[:1] in "{[":
        try:
            parsed: Any = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            if parsed and all(v is True for v in parsed.values()):
                # Attribute flags: only their names (environment_cozy | service_takeout)
                text = " | ".join(str(k) for k in parsed)
            else:
                text = " | ".join(f"{k}: {v}" for k, v in parsed.items())
        elif isinstance(parsed, list):
            text = " | ".join(str(v) for v in parsed)
    text = re.sub(r"[\r\n]+", " ", text).replace('"', "'")
    text = re.sub(r"\s*,\s*", " - ", text)
    # An empty text would be written as "" (quoted); an empty field reads the same
    return text or None


def write_csv(frame: pl.DataFrame, target: Path) -> None:
    """CSV as the approved Golfo files: UTF-8 BOM, comma, CRLF.

    Every text field goes through flat_text, so no field needs quotes and the file
    opens column-aligned in Excel and LibreOffice whatever their import settings.
    """
    text = [c for c, t in frame.schema.items() if t == pl.Utf8]
    clean = frame.with_columns(
        pl.col(c).map_elements(flat_text, return_dtype=pl.Utf8, skip_nulls=True)
        for c in text
    )
    clean.write_csv(
        target, include_bom=True, line_terminator="\r\n", quote_style="necessary"
    )


def _regions(path: Path, prospects: pl.DataFrame) -> list[str | None] | None:
    """Region of each prospect from the territory GeoJSON, or None without region names.

    Only a GeoJSON whose features carry a region name gives the column (user decision
    2026-11-17: "si no lo tienes no lo pongas"); a single unnamed polygon gives none.
    """
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    named = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        key = next((k for k in REGION_KEYS if props.get(k)), None)
        if key and feature.get("geometry"):
            named.append((str(props[key]).strip(), shape(feature["geometry"])))
    if not named:
        return None
    lat = prospects.get_column("latitude").cast(pl.Float64).to_list()
    lon = prospects.get_column("longitude").cast(pl.Float64).to_list()
    return [
        next((name for name, geom in named if geom.covers(Point(b, a))), None)
        for a, b in zip(lat, lon, strict=True)
    ]


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
