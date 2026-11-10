"""Tests for the territory pre-step with synthetic data (no client data)."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Polygon

from cleaning_agent.adapters.streaming import territory as tf

SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
OVERLAPPING_SQUARE = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])


@pytest.fixture
def logger() -> tf.CorrelationAdapter:
    return tf.get_logger("test-correlation-id")


@pytest.fixture
def geojson_path(tmp_path: Path) -> Path:
    territories = gpd.GeoDataFrame(
        {"id": ["A", "B"]},
        geometry=[SQUARE, OVERLAPPING_SQUARE],
        crs=tf.GEOGRAPHIC_CRS,
    )
    path = tmp_path / "territorio.geojson"
    territories.to_file(path, driver="GeoJSON")
    return path


def _dataplor_table(ids: list[str], lats: list[str], lons: list[str]) -> pa.Table:
    statuses = ["inactive" if pid == "p5" else "active" for pid in ids]
    return pa.table(
        {
            "dataplor_id": ids,
            "name": [f"TIENDA {pid}" for pid in ids],
            "latitude": lats,
            "longitude": lons,
            "dataplor_status": statuses,
            "open_closed_status": ["open"] * len(ids),
        }
    )


@pytest.fixture
def parquet_parts(tmp_path: Path) -> list[Path]:
    # Two parts, as Dataplor exports come split in part-*.parquet files
    raw = tmp_path / "raw"
    raw.mkdir()
    part_1 = raw / "part-00000.parquet"
    part_2 = raw / "part-00001.parquet"
    pq.write_table(
        _dataplor_table(
            ["p1", "p2", "p3", "p4"], ["2", "12", "20", "abc"], ["2", "12", "20", "5"]
        ),
        part_1,
    )
    pq.write_table(
        _dataplor_table(["p5", "p6", "p7"], ["5", "7", "0"], ["5", "7", "3"]),
        part_2,
    )
    return [part_1, part_2]


def _config(
    tmp_path: Path, parts: list[Path], geojson: Path, **changes
) -> tf.TerritoryFilterConfig:
    options = {
        "parquet_files": parts,
        "geojson_path": geojson,
        "output_csv": tmp_path / "out" / "dataplor_cleaned.csv",
        "bottler": "Sintetica",
        "territory_columns": ["id"],
        "batch_size": 2,
        "outside_output": tmp_path / "out" / "territory_outside.parquet",
    }
    options.update(changes)
    return tf.TerritoryFilterConfig(**options)


def test_valid_coordinates_mask_drops_nulls_and_out_of_range():
    lats = np.array([10.0, np.nan, 95.0, -45.0])
    lons = np.array([20.0, 20.0, 20.0, -181.0])

    assert tf.valid_coordinates_mask(lats, lons).tolist() == [True, False, False, False]


def test_assign_territory_includes_border_and_detects_overlap():
    lats = np.array([1.0, 7.0, 0.0, 50.0])
    lons = np.array([1.0, 7.0, 3.0, 50.0])

    index, matches = tf.assign_territory(
        lats, lons, np.array([SQUARE, OVERLAPPING_SQUARE]), np.ones(4, dtype=bool)
    )

    assert index.tolist() == [0, 0, 0, -1]
    assert matches.tolist() == [1, 2, 1, 0]


def test_assign_territory_ignores_non_candidates():
    index, _ = tf.assign_territory(
        np.array([1.0]), np.array([1.0]), np.array([SQUARE]), np.array([False])
    )

    assert index.tolist() == [-1]


def test_load_territories_fails_on_missing_column(geojson_path, logger):
    with pytest.raises(ValueError, match="do not exist in the GeoJSON"):
        tf.load_territories(geojson_path, ["missing_column"], logger)


def test_load_territories_fails_when_file_missing(tmp_path, logger):
    with pytest.raises(FileNotFoundError):
        tf.load_territories(tmp_path / "nope.geojson", [], logger)


def test_load_territories_repairs_invalid_geometry(tmp_path, logger):
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # self-intersecting
    path = tmp_path / "invalid.geojson"
    gpd.GeoDataFrame({"id": ["X"]}, geometry=[bowtie], crs=tf.GEOGRAPHIC_CRS).to_file(
        path, driver="GeoJSON"
    )

    territories = tf.load_territories(path, ["id"], logger)

    assert territories.geometry.is_valid.all()
    assert set(territories.geom_type) <= tf.POLYGON_TYPES


def test_validate_schema_fails_on_missing_column():
    with pytest.raises(ValueError, match="longitude"):
        tf.validate_schema(
            pa.schema([("latitude", pa.string())]), ["latitude", "longitude"]
        )


def test_resolve_parquet_files_expands_glob(parquet_parts):
    files = tf.resolve_parquet_files(parquet_parts[0].parent / "part-*.parquet")

    assert files == parquet_parts


def test_resolve_parquet_files_fails_when_nothing_matches(tmp_path):
    with pytest.raises(FileNotFoundError, match="No Dataplor Parquet"):
        tf.resolve_parquet_files(tmp_path / "part-*.parquet")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"parquet_files": []}, "no Parquet files"),
        ({"batch_size": 0}, "batch_size"),
        ({"max_batches": 0}, "max_batches"),
        ({"bottler": "  "}, "bottler"),
    ],
)
def test_config_rejects_invalid_values(
    tmp_path, parquet_parts, geojson_path, changes, message
):
    with pytest.raises(ValueError, match=message):
        _config(tmp_path, parquet_parts, geojson_path, **changes)


def test_full_run_writes_csv_readable_by_pipeline_and_counts_add_up(
    tmp_path, parquet_parts, geojson_path, logger
):
    config = _config(tmp_path, parquet_parts, geojson_path)

    counts = tf.filter_dataplor_by_territory(config, logger)

    # The modules read this file with pd.read_csv, exactly like main.py does
    inside = pd.read_csv(config.output_csv, dtype=str, encoding="utf-8")
    outside = pq.read_table(config.outside_output)
    assert sorted(inside["dataplor_id"]) == ["p1", "p2", "p6", "p7"]
    assert sorted(outside["dataplor_id"].to_pylist()) == ["p3"]
    assert set(inside["embotelladora"]) == {"Sintetica"}
    assert dict(zip(inside["dataplor_id"], inside["territorio_id"], strict=True)) == {
        "p1": "A",
        "p2": "B",
        "p6": "A",
        "p7": "A",
    }
    assert counts["in_polygon_overlap"] == 1
    assert counts["rows_read"] == 7
    assert counts["rows_read"] == (
        counts["invalid_coordinates"]
        + counts["dropped_by_status"]
        + counts["inside_territory"]
        + counts["outside_territory"]
    )


def test_run_without_status_filter_keeps_inactive_points(
    tmp_path, parquet_parts, geojson_path, logger
):
    config = _config(tmp_path, parquet_parts, geojson_path, only_active_open=False)

    tf.filter_dataplor_by_territory(config, logger)

    inside = pd.read_csv(config.output_csv, dtype=str)
    assert "p5" in set(inside["dataplor_id"])


def test_run_respects_max_batches_across_parts(
    tmp_path, parquet_parts, geojson_path, logger
):
    # batch_size=2 -> part 1 gives 2 batches; max_batches=3 must read 1 batch of part 2
    config = _config(tmp_path, parquet_parts, geojson_path, max_batches=3)

    counts = tf.filter_dataplor_by_territory(config, logger)

    assert counts["rows_read"] == 6


def test_run_overwrites_previous_output_and_skips_outside_when_disabled(
    tmp_path, parquet_parts, geojson_path, logger
):
    config = _config(tmp_path, parquet_parts, geojson_path, outside_output=None)
    config.output_csv.parent.mkdir(parents=True)
    config.output_csv.write_text("stale,data\n1,2\n", encoding="utf-8")

    tf.filter_dataplor_by_territory(config, logger)

    assert "stale" not in config.output_csv.read_text(encoding="utf-8")
    assert not (tmp_path / "out" / "territory_outside.parquet").exists()


def test_run_fails_when_no_point_is_inside(tmp_path, geojson_path, logger):
    part = tmp_path / "part-00000.parquet"
    pq.write_table(_dataplor_table(["p1"], ["50"], ["50"]), part)
    config = _config(tmp_path, [part], geojson_path)

    with pytest.raises(ValueError, match="No Dataplor point fell inside"):
        tf.filter_dataplor_by_territory(config, logger)


def test_chunked_writer_rejects_schema_change(tmp_path):
    with tf.ChunkedWriter(tmp_path / "out.csv") as writer:
        writer.write(pa.table({"a": ["1"]}))
        with pytest.raises(ValueError, match="Schema changed"):
            writer.write(pa.table({"b": ["1"]}))


def test_logger_prefixes_correlation_id(caplog, logger):
    with caplog.at_level("INFO", logger="cleaning_agent"):
        logger.info("hello")

    assert "[cid=test-correlation-id] hello" in caplog.text


def test_format_audit_report_lists_every_count():
    report = tf.format_audit_report({"rows_read": 4, "inside_territory": 1})

    assert "rows_read: 4 (100.00%)" in report
    assert "inside_territory: 1 (25.00%)" in report
    assert "outside_territory: 0 (0.00%)" in report
