"""Paso 1 bottler: validación de la base de clientes (mismas reglas que dw_validar)."""

import json
from argparse import Namespace
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from numpy.typing import NDArray

from cleaning_agent.adapters.clients_bottler import (
    ChannelRule,
    Territory,
    channel_rule,
    clean_client_file,
    output_name,
)
from cleaning_agent.domain.clients_bottler import (
    REASON_CHANNEL,
    REASON_COORD,
    REASON_DUPLICATE,
    REASON_ISOLATED,
    REASON_OUTSIDE,
    negate_text,
    normalize_label,
    validate_clients,
)

BRAND = Path(__file__).resolve().parent.parent / ".claude/skills/brand-guidelines-kin/assets"

# "País" de prueba: lat -40..-30, lon -65..-55 (todo el hemisferio sur-oeste)
LAT_RANGE, LON_RANGE = (-40.0, -30.0), (-65.0, -55.0)


def box(lon: NDArray[np.float64], lat: NDArray[np.float64]) -> NDArray[np.bool_]:
    return np.asarray(
        (lat > LAT_RANGE[0]) & (lat < LAT_RANGE[1]) & (lon > LON_RANGE[0]) & (lon < LON_RANGE[1]),
        dtype=bool,
    )


def test_valid_cluster_is_kept_untouched() -> None:
    v = validate_clients(
        ["-34.600", "-34.610", "-34.620"], ["-58.400", "-58.410", "-58.420"],
        ["1", "2", "3"], ["T"] * 3, box,
    )
    assert v.keep == [True, True, True]
    assert v.base_swapped is False
    assert v.lat == ["-34.600", "-34.610", "-34.620"]
    assert all(c == "" for c in v.correction)


def test_whole_base_swapped_is_oriented() -> None:
    # Andina: la columna de latitud trae longitudes y viceversa
    v = validate_clients(
        ["-58.400", "-58.410", "-58.420"], ["-34.600", "-34.610", "-34.620"],
        ["1", "2", "3"], ["T"] * 3, box,
    )
    assert v.base_swapped is True
    assert v.inside_as_is == 0 and v.inside_swapped == 3
    assert v.keep == [True, True, True]
    assert v.lat[0] == "-34.600" and v.lon[0] == "-58.400"
    assert all(c == "" for c in v.correction)  # orientar la base no es corregir filas


def test_single_row_with_missing_sign_is_corrected_in_text() -> None:
    v = validate_clients(
        ["-34.600", "-34.610", "34.620"], ["-58.400", "-58.410", "-58.420"],
        ["1", "2", "3"], ["T"] * 3, box,
    )
    assert v.keep == [True, True, True]
    assert v.correction[2] == "signo de la latitud"
    assert v.lat[2] == "-34.620"
    assert "coordenada corregida" in v.alerts[2]


def test_single_row_swapped_is_corrected() -> None:
    v = validate_clients(
        ["-34.600", "-34.610", "-58.420"], ["-58.400", "-58.410", "-34.620"],
        ["1", "2", "3"], ["T"] * 3, box,
    )
    assert v.correction[2] == "lat/lon invertidas"
    assert (v.lat[2], v.lon[2]) == ("-34.620", "-58.420")


def test_invalid_and_outside_rows_are_removed_with_first_reason() -> None:
    v = validate_clients(
        ["-34.600", "0", "", "95", "10.0", "-34.601"],
        ["-58.400", "0", "-58.4", "-58.4", "10.0", "-58.401"],
        [str(i) for i in range(6)], ["T"] * 6, box,
    )
    assert v.keep == [True, False, False, False, False, True]
    assert v.reason[1:5] == [REASON_COORD, REASON_COORD, REASON_COORD, REASON_OUTSIDE]
    assert v.removed[REASON_COORD] == 3
    assert v.removed[REASON_OUTSIDE] == 1
    assert v.kept + sum(v.removed.values()) == 6


def test_repeated_coordinate_keeps_the_first() -> None:
    v = validate_clients(
        ["-34.600", "-34.6000001", "-34.610"], ["-58.400", "-58.400", "-58.410"],
        ["a", "b", "c"], ["T"] * 3, box,
    )
    assert v.keep == [True, False, True]
    assert v.reason[1] == REASON_DUPLICATE


def test_isolated_point_is_removed() -> None:
    # dos clientes juntos en Buenos Aires y uno solo a más de 20 km de todos
    v = validate_clients(
        ["-34.600", "-34.610", "-38.000"], ["-58.400", "-58.410", "-62.000"],
        ["1", "2", "3"], ["T"] * 3, box,
    )
    assert v.keep == [True, True, False]
    assert v.reason[2] == REASON_ISOLATED


def test_isolation_counts_clients_of_any_channel() -> None:
    # el cliente tradicional no queda aislado porque tiene un moderno al lado
    v = validate_clients(
        ["-34.600", "-34.610"], ["-58.400", "-58.410"], ["1", "2"],
        ["TRADICIONAL", "SUPERMERCADOS"], box, frozenset({"TRADICIONAL"}),
    )
    assert v.keep == [True, False]
    assert v.reason[1] == REASON_CHANNEL


def test_channel_is_normalized() -> None:
    assert normalize_label(" comer & beber ") == "COMER BEBER"
    assert normalize_label("Tradicionál") == "TRADICIONAL"


def test_alerts_do_not_invalidate() -> None:
    v = validate_clients(
        ["-34.6", "-34.610", "-34.620"], ["-58.4", "-58.410", "-58.420"],
        ["1", "1", "2"], ["T"] * 3, box,
    )
    assert v.keep == [True, True, True]
    assert "pocos decimales" in v.alerts[0]
    assert "pos_id duplicado" in v.alerts[0] and "pos_id duplicado" in v.alerts[1]


def test_negate_text_keeps_digits() -> None:
    assert negate_text("34.620001") == "-34.620001"
    assert negate_text(" -58.10 ") == "58.10"


def test_empty_and_mismatched_bases_are_rejected() -> None:
    with pytest.raises(ValueError):
        validate_clients([], [], [], [], box)
    with pytest.raises(ValueError):
        validate_clients(["-34.6"], ["-58.4", "-58.4"], ["1"], ["T"], box)


def test_channel_rule_and_output_name() -> None:
    section = {"channels": {"andina": {"column": "pos_channel", "tradicional": ["TRADICIONAL"],
                                       "moderno": ["SUPERMERCADOS"]}}}
    assert channel_rule(section, "andina", "todos").values is None
    assert channel_rule(section, "andina", "ambos").values == ("TRADICIONAL", "SUPERMERCADOS")
    with pytest.raises(ValueError):
        channel_rule(section, "otro", "moderno")
    assert output_name(Path("Listado clientes Andina.csv"), "todos") == "listado_clientes_andina_todos_validos"


def _square(lat0: float, lat1: float, lon0: float, lon1: float, name: str) -> dict[str, object]:
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"type": "Feature", "properties": {"nam": name},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _geojson(path: Path, *features: dict[str, object]) -> Path:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": list(features)}), "utf-8")
    return path


def test_adapter_writes_validated_csv_metadata_and_brand_qa(tmp_path: Path) -> None:
    country = _geojson(tmp_path / "adm0.geojson", _square(-40, -30, -65, -55, "País"))
    (tmp_path / "adm0.json").write_text('{"institucion": "prueba"}', "utf-8")
    prov = _geojson(tmp_path / "adm1.geojson", _square(-40, -30, -65, -55, "Buenos Aires"))
    src = tmp_path / "Listado clientes.csv"
    # base invertida (como Andina), una fila con signo perdido, un 0,0, uno fuera,
    # una coordenada repetida y un canal que no va
    src.write_text(
        "pos_id,pos_name,pos_channel,pos_latitude,pos_longitude\n"
        "001,A,TRADICIONAL,-58.400,-34.600\n"
        "002,B,TRADICIONAL,-58.410,-34.610\n"
        "003,C,TRADICIONAL,-58.420,34.620\n"
        "004,D,TRADICIONAL,0,0\n"
        "005,E,TRADICIONAL,45.780,67.490\n"
        "006,F,TRADICIONAL,-58.400,-34.600\n"
        "007,G,MAYORISTA,-58.430,-34.630\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    summary = clean_client_file(
        src, out, "clientes_tradicional_validos",
        Territory(country=country, divisions={"provincia": prov}),
        ChannelRule("pos_channel", "tradicional", ("TRADICIONAL",)),
        "run-test", BRAND, "ar", "test", "Argentina",
    )
    assert summary["filas_validas"] == 3
    assert summary["lat_lon_intercambiadas_en_toda_la_base"] is True
    assert summary["coordenadas_corregidas_por_fila"] == 1

    clean = pl.read_csv(out / "clientes_tradicional_validos.csv", infer_schema_length=0)
    assert clean.get_column("pos_id").to_list() == ["001", "002", "003"]  # ceros conservados
    assert clean.get_column("pos_latitude").to_list() == ["-34.600", "-34.610", "-34.620"]
    assert clean.get_column("provincia").to_list() == ["Buenos Aires"] * 3

    meta = json.loads((out / "clientes_tradicional_validos_metadata.json").read_text("utf-8"))
    assert all(c["ok"] for c in meta["qa"])
    assert meta["coordenadas_corregidas"]["pos_id"] == ["003"]
    assert meta["por_que_se_quitaron"][REASON_DUPLICATE] == 1
    assert meta["territorio"]["pais"]["institucion"] == "prueba"
    qa = (out / "clientes_tradicional_validos_qa.html").read_text(encoding="utf-8")
    assert "data:image/svg+xml;base64," in qa and "kinanalytics.com" in qa
    assert "-34.620" not in qa  # el QA no muestra coordenadas de clientes
    # mapa embebido como PNG: se ve sin internet y sin teselas externas
    assert "data:image/png;base64," in qa
    assert "http://" not in qa and "<script" not in qa


def test_cli_parser_accepts_clean_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    from cleaning_agent.entrypoints import cli, clients_clean

    seen: dict[str, Namespace] = {}

    def fake(args: Namespace) -> dict[str, str]:
        seen["args"] = args
        return {"ok": "1"}

    monkeypatch.setattr(clients_clean, "clean_clients_command", fake)
    assert cli.main(["clean-clients", "--src", "x.csv", "--country", "ar",
                     "--bottler", "andina", "--canal", "moderno"]) == 0
    assert seen["args"].canal == "moderno" and seen["args"].fecha is None
