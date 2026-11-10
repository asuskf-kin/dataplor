"""Pre-step: keep only the raw Dataplor points that fall inside a bottler's territory.

Runs BEFORE the numbered modules. It streams the raw Dataplor Parquet export (one
or several ``part-*.parquet`` files, ~10M rows for MX) in batches, keeps the
active + open points whose coordinates fall inside any polygon of the territory
GeoJSON, and writes them to the CSV the rest of the pipeline (and report.ipynb)
reads as ``paths.raw_data``.

Ported from ``Prospección/Filtrar Dataplor por Cercanía de Clientes/cruce_territorios.py``.
Design notes kept from the original:
- The Parquet is never fully loaded: batches are filtered and appended to disk.
- ``shapely.intersects_xy`` is vectorised and counts points on the exact border
  as inside.
- The original Dataplor schema is preserved; ``embotelladora`` plus the chosen
  GeoJSON properties (prefixed ``territorio_``) are appended.
"""

import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path
from typing import Self

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
import shapely

from cleaning_agent.observability import get_logger

GEOGRAPHIC_CRS = "EPSG:4326"
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
STATUS_COLUMNS = ("dataplor_status", "open_closed_status")
TERRITORY_PREFIX = "territorio_"
# Log progress every N batches instead of a progress bar (no extra dependency)
PROGRESS_EVERY = 10


@dataclass(frozen=True)
class TerritoryFilterConfig:
    """Options of the territory pre-step (``territory_filter`` in config.yaml)."""

    parquet_files: list[Path]
    geojson_path: Path
    output_csv: Path
    bottler: str
    territory_columns: list[str] = field(default_factory=list)
    lat_col: str = "latitude"
    lon_col: str = "longitude"
    only_active_open: bool = True
    batch_size: int = 200_000
    max_batches: int | None = None
    outside_output: Path | None = None

    def __post_init__(self) -> None:
        if not self.parquet_files:
            raise ValueError("territory_filter: no Parquet files to read")
        if self.batch_size <= 0:
            raise ValueError("territory_filter.batch_size must be > 0")
        if self.max_batches is not None and self.max_batches <= 0:
            raise ValueError("territory_filter.max_batches must be > 0 or null")
        if not self.bottler.strip():
            raise ValueError("territory_filter.bottler must not be empty")


def resolve_parquet_files(pattern: Path) -> list[Path]:
    """Expands a file path or glob (e.g. ``data/raw/mx/femsa/part-*.parquet``).

    Dataplor exports may be split in several ``part-*`` files, so a glob lets the
    user drop them all in the raw folder without listing each one.

    Raises:
        FileNotFoundError: If nothing matches.
    """
    files = sorted(Path(match) for match in glob(str(pattern)))
    files = [path for path in files if path.is_file()]
    if not files:
        raise FileNotFoundError(f"No Dataplor Parquet matches: {pattern}")
    return files


def _keep_polygons(geometry: shapely.Geometry) -> shapely.Geometry | None:
    """Keeps only the polygonal parts of a geometry (e.g. after make_valid)."""
    if geometry.geom_type in POLYGON_TYPES:
        return geometry
    parts = [
        part for part in shapely.get_parts(geometry) if part.geom_type in POLYGON_TYPES
    ]
    return shapely.union_all(parts) if parts else None


def load_territories(
    geojson_path: Path,
    territory_columns: list[str],
    logger: logging.LoggerAdapter[logging.Logger],
) -> gpd.GeoDataFrame:
    """Reads and validates the territory GeoJSON.

    Reprojects to EPSG:4326, repairs invalid geometries and drops non-polygonal
    ones. Geometries are prepared for fast repeated point queries.

    Raises:
        FileNotFoundError: If the GeoJSON does not exist.
        ValueError: If it is empty, lacks columns or no valid polygon remains.
    """
    if not geojson_path.exists():
        raise FileNotFoundError(f"Territory GeoJSON not found: {geojson_path}")

    territories = gpd.read_file(geojson_path)
    if territories.empty:
        raise ValueError(f"The GeoJSON has no features: {geojson_path}")

    missing = set(territory_columns) - set(territories.columns)
    if missing:
        raise ValueError(
            f"Columns {sorted(missing)} do not exist in the GeoJSON. "
            f"Available: {territories.columns.drop('geometry').tolist()}"
        )

    if territories.crs is None:
        logger.warning("GeoJSON without CRS; assuming %s", GEOGRAPHIC_CRS)
        territories = territories.set_crs(GEOGRAPHIC_CRS)
    elif territories.crs != GEOGRAPHIC_CRS:
        logger.info(
            "Reprojecting territories %s -> %s", territories.crs, GEOGRAPHIC_CRS
        )
        territories = territories.to_crs(GEOGRAPHIC_CRS)

    territories = territories[
        territories.geometry.notna() & ~territories.geometry.is_empty
    ].copy()

    invalid = ~territories.geometry.is_valid
    if invalid.any():
        logger.warning("Repairing %s invalid geometries with make_valid", invalid.sum())
        territories.loc[invalid, "geometry"] = territories.loc[
            invalid, "geometry"
        ].make_valid()

    territories["geometry"] = territories.geometry.apply(_keep_polygons)
    territories = territories[territories.geometry.notna()]
    if territories.empty:
        raise ValueError(f"No valid polygons left in {geojson_path}")

    territories = territories[[*territory_columns, "geometry"]].reset_index(drop=True)
    shapely.prepare(territories.geometry.values)
    logger.info("Territories loaded: %s polygons", len(territories))
    return territories


def validate_schema(schema: pa.Schema, required: list[str]) -> None:
    """Raises ValueError if any required column is missing from the Parquet."""
    missing = set(required) - set(schema.names)
    if missing:
        raise ValueError(
            f"Required columns {sorted(missing)} do not exist in the Parquet. "
            f"Available: {schema.names}"
        )


def extract_coordinates(
    batch: pa.RecordBatch, lat_col: str, lon_col: str
) -> tuple[np.ndarray, np.ndarray]:
    """Casts the lat/lon columns (strings in Dataplor) to float; garbage -> NaN."""
    lats = pd.to_numeric(batch.column(lat_col).to_pandas(), errors="coerce")
    lons = pd.to_numeric(batch.column(lon_col).to_pandas(), errors="coerce")
    return (
        lats.to_numpy(dtype="float64", na_value=np.nan),
        lons.to_numpy(dtype="float64", na_value=np.nan),
    )


def valid_coordinates_mask(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """True where the coordinate is finite and inside geographic ranges."""
    return (
        np.isfinite(lats)
        & np.isfinite(lons)
        & (np.abs(lats) <= 90)
        & (np.abs(lons) <= 180)
    )


def active_open_mask(batch: pa.RecordBatch) -> np.ndarray:
    """True where ``dataplor_status == 'active'`` and ``open_closed_status == 'open'``."""

    def equals(column: str, value: str) -> np.ndarray:
        # Nulls become None, which never equals the value -> "not active/open"
        values = np.asarray(batch.column(column).to_numpy(zero_copy_only=False))
        return np.asarray(values == value, dtype=bool)

    mask: np.ndarray = np.logical_and(
        equals("dataplor_status", "active"), equals("open_closed_status", "open")
    )
    return mask


def assign_territory(
    lats: np.ndarray,
    lons: np.ndarray,
    geometries: np.ndarray,
    candidates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assigns each candidate point to the first territory that contains it.

    A bounding-box pre-filter avoids the polygon test for far away points.

    Returns:
        ``(territory_index, n_matches)``: index is -1 outside every territory;
        ``n_matches > 1`` means overlapping polygons.
    """
    territory_index = np.full(len(lats), -1, dtype=np.int64)
    n_matches = np.zeros(len(lats), dtype=np.int64)

    for position, geometry in enumerate(geometries):
        min_lon, min_lat, max_lon, max_lat = geometry.bounds
        in_bbox = (
            candidates
            & (lons >= min_lon)
            & (lons <= max_lon)
            & (lats >= min_lat)
            & (lats <= max_lat)
        )
        if not in_bbox.any():
            continue
        inside = np.zeros(len(lats), dtype=bool)
        inside[in_bbox] = shapely.intersects_xy(geometry, lons[in_bbox], lats[in_bbox])
        n_matches += inside
        territory_index[inside & (territory_index == -1)] = position

    return territory_index, n_matches


def add_territory_columns(
    table: pa.Table,
    territory_index: np.ndarray,
    territories: gpd.GeoDataFrame,
    territory_columns: list[str],
    bottler: str,
) -> pa.Table:
    """Appends ``embotelladora`` and the territory properties to each point.

    Properties are prefixed with ``territorio_`` so they never clash with
    Dataplor columns such as ``state``.
    """
    table = table.append_column(
        "embotelladora", pa.array([bottler] * table.num_rows, type=pa.string())
    )
    indices = pa.array(territory_index)
    for column in territory_columns:
        values = pa.array(
            territories[column].astype("string"), type=pa.string(), from_pandas=True
        )
        table = table.append_column(f"{TERRITORY_PREFIX}{column}", values.take(indices))
    return table


class ChunkedWriter:
    """Appends Arrow tables to a CSV or Parquet file (format from the suffix).

    The file is created on the first non-empty table; a file left by a previous
    run is deleted up front so data from two runs is never mixed. Use it as a
    context manager so the file handle is always released.
    """

    def __init__(self, path: Path) -> None:
        if path.suffix not in {".csv", ".parquet"}:
            raise ValueError(f"Unsupported output format: {path}")
        self.path = path
        self.rows_written = 0
        self._writer: pq.ParquetWriter | pa_csv.CSVWriter | None = None
        self._schema: pa.Schema | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)

    def write(self, table: pa.Table) -> None:
        """Appends ``table``; empty tables are ignored."""
        if table.num_rows == 0:
            return
        if self._writer is None:
            self._schema = table.schema
            self._writer = (
                pq.ParquetWriter(self.path, table.schema, compression="snappy")
                if self.path.suffix == ".parquet"
                else pa_csv.CSVWriter(self.path, table.schema)
            )
        elif self._schema is None or not table.schema.equals(self._schema):
            # Happens when several part-*.parquet files have different columns
            raise ValueError(
                f"Schema changed while writing {self.path.name}; all Parquet "
                "parts must share the same columns"
            )
        self._writer.write_table(table)
        self.rows_written += table.num_rows

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def process_batch(
    batch: pa.RecordBatch,
    territories: gpd.GeoDataFrame,
    config: TerritoryFilterConfig,
) -> tuple[pa.Table, pa.Table, Counter[str]]:
    """Splits a batch into points inside and outside the territory.

    Returns:
        ``(inside, outside, counts)``. ``outside`` holds only valid, active/open
        points that missed every polygon.
    """
    lats, lons = extract_coordinates(batch, config.lat_col, config.lon_col)
    valid = valid_coordinates_mask(lats, lons)
    candidates = valid.copy()
    counts: Counter[str] = Counter()
    if config.only_active_open:
        active_open = active_open_mask(batch)
        counts["dropped_by_status"] = int((valid & ~active_open).sum())
        candidates &= active_open

    territory_index, n_matches = assign_territory(
        lats, lons, territories.geometry.values, candidates
    )
    inside = territory_index >= 0
    outside = candidates & ~inside

    counts["rows_read"] = batch.num_rows
    counts["invalid_coordinates"] = int((~valid).sum())
    counts["inside_territory"] = int(inside.sum())
    counts["outside_territory"] = int(outside.sum())
    counts["in_polygon_overlap"] = int((n_matches > 1).sum())

    table = pa.Table.from_batches([batch])
    inside_table = add_territory_columns(
        table.filter(pa.array(inside)),
        territory_index[inside],
        territories,
        config.territory_columns,
        config.bottler,
    )
    return inside_table, table.filter(pa.array(outside)), counts


def iter_parquet_batches(
    parquet_files: list[Path],
    required_columns: list[str],
    batch_size: int,
    max_batches: int | None,
    logger: logging.LoggerAdapter[logging.Logger],
) -> Iterator[pa.RecordBatch]:
    """Yields batches across every Parquet part, honouring ``max_batches``.

    Shared by every Dataplor pre-filter (territory, client proximity) so they read
    the raw export the same way.
    """
    remaining = max_batches
    if remaining is not None:
        logger.warning("Test mode: only %s batches will be read", remaining)

    for path in parquet_files:
        parquet = pq.ParquetFile(path)
        validate_schema(parquet.schema_arrow, required_columns)
        logger.info("Reading %s (%s rows)", path.name, f"{parquet.metadata.num_rows:,}")
        try:
            for batch in parquet.iter_batches(batch_size=batch_size):
                if remaining is not None:
                    if remaining == 0:
                        return
                    remaining -= 1
                yield batch
        finally:
            parquet.close()


def required_columns(lat_col: str, lon_col: str, only_active_open: bool) -> list[str]:
    """Columns a pre-filter needs from the raw Parquet."""
    columns = [lat_col, lon_col]
    if only_active_open:
        columns += list(STATUS_COLUMNS)
    return columns


def filter_dataplor_by_territory(
    config: TerritoryFilterConfig,
    logger: logging.LoggerAdapter[logging.Logger] | None = None,
) -> dict[str, int]:
    """Streams the raw Parquet and writes the in-territory points to ``output_csv``.

    Returns:
        Run counts. They always add up:
        ``rows_read = invalid_coordinates + dropped_by_status
        + inside_territory + outside_territory``.

    Raises:
        FileNotFoundError: If the GeoJSON or a Parquet file is missing.
        ValueError: On missing columns, no valid polygons or an empty result.
    """
    logger = logger or get_logger()
    territories = load_territories(
        config.geojson_path, config.territory_columns, logger
    )
    counts: Counter[str] = Counter()

    with ExitStack() as files:
        inside_writer = files.enter_context(ChunkedWriter(config.output_csv))
        outside_writer = (
            files.enter_context(ChunkedWriter(config.outside_output))
            if config.outside_output is not None
            else None
        )
        batches = iter_parquet_batches(
            config.parquet_files,
            required_columns(config.lat_col, config.lon_col, config.only_active_open),
            config.batch_size,
            config.max_batches,
            logger,
        )
        for n_batch, batch in enumerate(batches, start=1):
            inside, outside, batch_counts = process_batch(batch, territories, config)
            counts.update(batch_counts)
            inside_writer.write(inside)
            if outside_writer is not None:
                outside_writer.write(outside)
            if n_batch % PROGRESS_EVERY == 0:
                logger.info(
                    "Batch %s: %s read, %s inside so far",
                    n_batch,
                    f"{counts['rows_read']:,}",
                    f"{counts['inside_territory']:,}",
                )

    if counts["in_polygon_overlap"]:
        logger.warning(
            "%s points fall in more than one polygon; the first one was assigned",
            f"{counts['in_polygon_overlap']:,}",
        )
    if counts["inside_territory"] == 0:
        # An empty CSV would make every later module fail with a confusing error
        raise ValueError(
            "No Dataplor point fell inside the territory: check that the GeoJSON "
            "and the Parquet belong to the same country"
        )

    logger.info(
        "Territory filter: %s of %s rows inside -> %s",
        f"{counts['inside_territory']:,}",
        f"{counts['rows_read']:,}",
        config.output_csv,
    )
    if outside_writer is not None:
        logger.info(
            "Outside territory: %s rows -> %s",
            f"{outside_writer.rows_written:,}",
            config.outside_output,
        )
    return dict(counts)


def format_audit_report(counts: dict[str, int]) -> str:
    """Formats the counts for the .txt audit file."""
    rows_read = counts.get("rows_read", 0) or 1
    keys = (
        "rows_read",
        "invalid_coordinates",
        "dropped_by_status",
        "outside_territory",
        "inside_territory",
        "in_polygon_overlap",
    )
    return "\n".join(
        f"{key}: {counts.get(key, 0):,} ({counts.get(key, 0) / rows_read:.2%})"
        for key in keys
    )
