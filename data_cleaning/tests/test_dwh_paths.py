"""Metadata names warehouse addresses, never a path on one person's disk."""

import json
from pathlib import Path

from cleaning_agent.adapters.dwh_paths import DwhPathResolver
from cleaning_agent.domain.dwh_paths import is_local_path, mirror_address


def test_local_paths_are_recognised() -> None:
    assert is_local_path("C:/Users/x/data/gold/a.csv")
    assert is_local_path("C:\\Users\\x\\a.csv")
    assert is_local_path("\\\\server\\share\\a.csv")
    assert is_local_path("/home/x/a.csv")
    assert not is_local_path("prospecting-data/gold/ko/ar/a.csv")
    assert not is_local_path("andina_ARG_20261110/json_config.json")


def test_mirror_maps_layers_and_mirrored_containers() -> None:
    assert (
        mirror_address("gold/ko/ar/andina/x.csv", "prospecting-data", ())
        == "prospecting-data/gold/ko/ar/andina/x.csv"
    )
    assert (
        mirror_address("front/r/x.csv", "prospecting-data", ("front",)) == "front/r/x.csv"
    )
    assert mirror_address("runs/t/x.csv", "prospecting-data", ("front",)) is None


def _resolver(root: Path) -> DwhPathResolver:
    return DwhPathResolver(root, root / "data", "prospecting-data", ("front",))


def test_every_local_path_becomes_portable(tmp_path: Path) -> None:
    r = _resolver(tmp_path)
    data = tmp_path / "data"
    raw = data / "raw" / "ar" / "part-0.parquet"
    raw.parent.mkdir(parents=True)
    raw.write_text("x", encoding="utf-8")
    (raw.parent / "part-0_metadata.json").write_text(
        json.dumps(
            {"stage": "fetch_raw", "inputs": [{"blob": "dataplorraw/ar/part-0.parquet"}]}
        ),
        encoding="utf-8",
    )
    meta = {
        "origen": str(data / "silver" / "ko" / "a.csv"),
        "insumos": [str(data / "front" / "r" / "b.csv"), str(raw)],
        "runs": str(tmp_path / "data" / "runs" / "t" / "p.csv"),
        "fuera": "C:/Users/someone/Downloads/paso1.json",
        "blob": "prospecting-data/gold/x.csv",
        "espejo_local": str(data / "silver" / "ko" / "a.csv"),
        "filas": 3,
    }
    out = r.portable(meta)
    assert out["origen"] == "prospecting-data/silver/ko/a.csv"
    assert out["insumos"] == ["front/r/b.csv", "dataplorraw/ar/part-0.parquet"]
    assert out["runs"] == "data/runs/t/p.csv"
    assert out["fuera"] == "paso1.json"
    assert out["blob"] == "prospecting-data/gold/x.csv"
    assert "espejo_local" not in out
    assert out["filas"] == 3
    assert not any(is_local_path(v) for v in json.dumps(out).split('"'))


def test_a_download_names_its_file_by_the_blob(tmp_path: Path) -> None:
    r = _resolver(tmp_path)
    local = str(tmp_path / "elsewhere" / "geo.geojson")
    known = {"geo.geojson": "insumos/ar/geo.geojson"}
    assert r.portable({"path": local}, known) == {"path": "insumos/ar/geo.geojson"}
