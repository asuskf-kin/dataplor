"""Pre-filter: keep only the raw Dataplor points within a radius of a bottler client.

Ported from ``Prospección/Filtrar Dataplor por Cercanía de Clientes/Read Dataplor con
latitud y longitud - con clientes turbo.py``. Differences with the original:
- Uses scikit-learn's ``BallTree`` with the haversine metric (scikit-learn is already
  a project dependency; scipy is not declared).
- Streams through the same helpers as the territory pre-filter, so both read the raw
  export identically (active/open status, coordinate validation, chunked writing).
- Writes only the CSV the pipeline reads; client rows are never copied to the output,
  only used to build the tree.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
from sklearn.neighbors import BallTree

from cleaning_agent.adapters.streaming.territory import (
    ChunkedWriter,
    active_open_mask,
    extract_coordinates,
    iter_parquet_batches,
    required_columns,
    valid_coordinates_mask,
)
from cleaning_agent.observability import get_logger

EARTH_RADIUS_M = 6_371_000.0
CLIENT_NULL_VALUES = ["#N/A", "NA", "NaN", "nan", "N/A", ""]
MAX_RADIUS_M = 50_000.0


@dataclass(frozen=True)
class ClientProximityConfig:
    """Options of the client-proximity pre-filter (``client_filter`` in config.yaml)."""

    parquet_files: list[Path]
    clients_csv: Path
    output_csv: Path
    radius_m: float
    client_lat_col: str = "Coord_Y"
    client_lon_col: str = "Coord_X"
    lat_col: str = "latitude"
    lon_col: str = "longitude"
    only_active_open: bool = True
    batch_size: int = 200_000
    max_batches: int | None = None

    def __post_init__(self) -> None:
        if not self.parquet_files:
            raise ValueError("client_filter: no Parquet files to read")
        if not 0 < self.radius_m <= MAX_RADIUS_M:
            raise ValueError(
                f"client_filter.radius_m must be in (0, {MAX_RADIUS_M:,.0f}]"
            )
        if self.batch_size <= 0:
            raise ValueError("client_filter.batch_size must be > 0")
        if self.max_batches is not None and self.max_batches <= 0:
            raise ValueError("client_filter.max_batches must be > 0 or null")


def load_client_coordinates(
    clients_csv: Path, lat_col: str, lon_col: str
) -> np.ndarray:
    """Reads the client CSV and returns valid ``[lat, lon]`` pairs in radians.

    Only the two coordinate columns are read: the rest of the client file (names,
    contact data) never enters memory.

    Raises:
        FileNotFoundError: If the CSV does not exist.
        ValueError: If a column is missing or no client has valid coordinates.
    """
    if not clients_csv.exists():
        raise FileNotFoundError(f"Client CSV not found: {clients_csv}")
    header = pl.read_csv(clients_csv, n_rows=0).columns
    missing = {lat_col, lon_col} - set(header)
    if missing:
        raise ValueError(
            f"Columns {sorted(missing)} do not exist in the client CSV. Available: {header}"
        )

    clients = pl.read_csv(
        clients_csv,
        columns=[lat_col, lon_col],
        null_values=CLIENT_NULL_VALUES,
        schema_overrides={lat_col: pl.String, lon_col: pl.String},
    ).select(
        pl.col(lat_col).str.strip_chars().cast(pl.Float64, strict=False),
        pl.col(lon_col).str.strip_chars().cast(pl.Float64, strict=False),
    )
    lats = clients[lat_col].to_numpy()
    lons = clients[lon_col].to_numpy()
    valid = valid_coordinates_mask(lats, lons)
    if not valid.any():
        raise ValueError(f"No client in {clients_csv.name} has valid coordinates")
    return np.radians(np.column_stack((lats[valid], lons[valid])))


def near_client_mask(
    tree: BallTree,
    lats: np.ndarray,
    lons: np.ndarray,
    candidates: np.ndarray,
    radius_m: float,
) -> np.ndarray:
    """True where a candidate point has at least one client within ``radius_m``."""
    near = np.zeros(len(lats), dtype=bool)
    if not candidates.any():
        return near
    points = np.radians(np.column_stack((lats[candidates], lons[candidates])))
    distances, _ = tree.query(points, k=1)
    near[candidates] = distances[:, 0] * EARTH_RADIUS_M <= radius_m
    return near


def filter_dataplor_by_client_proximity(
    config: ClientProximityConfig,
    logger: logging.LoggerAdapter[logging.Logger] | None = None,
) -> dict[str, int]:
    """Streams the raw Parquet and writes the points near a client to ``output_csv``.

    Returns:
        Run counts. They always add up:
        ``rows_read = invalid_coordinates + dropped_by_status
        + near_client + far_from_client``.

    Raises:
        FileNotFoundError: If the client CSV or a Parquet file is missing.
        ValueError: On missing columns or when no point is near a client.
    """
    logger = logger or get_logger()
    client_coords = load_client_coordinates(
        config.clients_csv, config.client_lat_col, config.client_lon_col
    )
    tree = BallTree(client_coords, metric="haversine")
    logger.info("Client tree built with %s clients", f"{len(client_coords):,}")
    counts: Counter[str] = Counter()

    with ChunkedWriter(config.output_csv) as writer:
        batches = iter_parquet_batches(
            config.parquet_files,
            required_columns(config.lat_col, config.lon_col, config.only_active_open),
            config.batch_size,
            config.max_batches,
            logger,
        )
        for batch in batches:
            lats, lons = extract_coordinates(batch, config.lat_col, config.lon_col)
            valid = valid_coordinates_mask(lats, lons)
            candidates = valid.copy()
            if config.only_active_open:
                active_open = active_open_mask(batch)
                counts["dropped_by_status"] += int((valid & ~active_open).sum())
                candidates &= active_open

            near = near_client_mask(tree, lats, lons, candidates, config.radius_m)
            counts["rows_read"] += batch.num_rows
            counts["invalid_coordinates"] += int((~valid).sum())
            counts["near_client"] += int(near.sum())
            counts["far_from_client"] += int((candidates & ~near).sum())
            writer.write(pa.Table.from_batches([batch]).filter(pa.array(near)))

    if counts["near_client"] == 0:
        raise ValueError(
            f"No Dataplor point is within {config.radius_m:,.0f} m of a client: check "
            "the client coordinate columns and that both files are the same country"
        )
    logger.info(
        "Client proximity filter (%s m): %s of %s rows kept -> %s",
        f"{config.radius_m:,.0f}",
        f"{counts['near_client']:,}",
        f"{counts['rows_read']:,}",
        config.output_csv,
    )
    return dict(counts)
