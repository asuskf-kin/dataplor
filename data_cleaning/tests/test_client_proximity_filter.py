"""Client-proximity pre-filter with synthetic data (no real client data)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cleaning_agent.adapters.streaming import client_proximity as cp
from cleaning_agent.adapters.streaming.territory import get_logger

# One client in Guadalajara; 0.005° of latitude is ~556 m
CLIENT_LAT, CLIENT_LON = 20.6700, -103.3500


@pytest.fixture
def clients_csv(tmp_path: Path) -> Path:
    path = tmp_path / "clientes.csv"
    path.write_text(
        "pos_id,Coord_Y,Coord_X,nombre\n"
        f"1,{CLIENT_LAT},{CLIENT_LON},CLIENTE UNO\n"
        "2,#N/A,#N/A,SIN COORDENADAS\n"
        "3,abc,-103.1,COORDENADA ROTA\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def parquet_file(tmp_path: Path) -> Path:
    path = tmp_path / "part-00000.parquet"
    pq.write_table(
        pa.table(
            {
                "dataplor_id": ["near", "far", "closed", "bad"],
                "latitude": [str(CLIENT_LAT + 0.005), "25.0", str(CLIENT_LAT), "x"],
                "longitude": [str(CLIENT_LON), "-100.0", str(CLIENT_LON), "-103.35"],
                "dataplor_status": ["active", "active", "active", "active"],
                "open_closed_status": ["open", "open", "closed", "open"],
            }
        ),
        path,
    )
    return path


def _config(tmp_path, parquet_file, clients_csv, **changes) -> cp.ClientProximityConfig:
    options = {
        "parquet_files": [parquet_file],
        "clients_csv": clients_csv,
        "output_csv": tmp_path / "out" / "dataplor_cleaned.csv",
        "radius_m": 900,
        "batch_size": 2,
    }
    options.update(changes)
    return cp.ClientProximityConfig(**options)


def test_load_client_coordinates_skips_invalid_rows(clients_csv):
    coords = cp.load_client_coordinates(clients_csv, "Coord_Y", "Coord_X")

    assert coords.shape == (1, 2)
    assert np.allclose(np.degrees(coords[0]), [CLIENT_LAT, CLIENT_LON])


def test_load_client_coordinates_reports_missing_columns(clients_csv):
    with pytest.raises(ValueError, match="do not exist in the client CSV"):
        cp.load_client_coordinates(clients_csv, "lat", "lon")


def test_load_client_coordinates_fails_without_valid_clients(tmp_path):
    path = tmp_path / "vacio.csv"
    path.write_text("Coord_Y,Coord_X\n#N/A,#N/A\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No client"):
        cp.load_client_coordinates(path, "Coord_Y", "Coord_X")


def test_full_run_keeps_only_active_open_points_within_radius(
    tmp_path, parquet_file, clients_csv
):
    config = _config(tmp_path, parquet_file, clients_csv)

    counts = cp.filter_dataplor_by_client_proximity(config, get_logger("test-cid"))

    kept = pd.read_csv(config.output_csv, dtype=str)
    assert kept["dataplor_id"].tolist() == ["near"]
    assert "nombre" not in kept.columns  # client data never reaches the output
    assert counts == {
        "rows_read": 4,
        "invalid_coordinates": 1,
        "dropped_by_status": 1,
        "near_client": 1,
        "far_from_client": 1,
    }


def test_smaller_radius_drops_the_point(tmp_path, parquet_file, clients_csv):
    config = _config(tmp_path, parquet_file, clients_csv, radius_m=500)

    with pytest.raises(ValueError, match="No Dataplor point is within 500 m"):
        cp.filter_dataplor_by_client_proximity(config, get_logger("test-cid"))


def test_without_status_filter_closed_points_count(tmp_path, parquet_file, clients_csv):
    config = _config(tmp_path, parquet_file, clients_csv, only_active_open=False)

    counts = cp.filter_dataplor_by_client_proximity(config, get_logger("test-cid"))

    assert counts["near_client"] == 2


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"radius_m": 0}, "radius_m"),
        ({"radius_m": 60_000}, "radius_m"),
        ({"parquet_files": []}, "no Parquet"),
        ({"batch_size": 0}, "batch_size"),
        ({"max_batches": 0}, "max_batches"),
    ],
)
def test_config_rejects_invalid_values(
    tmp_path, parquet_file, clients_csv, changes, message
):
    with pytest.raises(ValueError, match=message):
        _config(tmp_path, parquet_file, clients_csv, **changes)
