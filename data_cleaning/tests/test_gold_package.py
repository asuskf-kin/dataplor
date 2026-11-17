"""Gold delivery package: real adapter on synthetic data (no production data)."""

import csv
import io
import json
import re
from pathlib import Path

import polars as pl
import pytest
from openpyxl import load_workbook
from pptx import Presentation

from cleaning_agent.adapters.brand import BUNDLED_ASSETS_DIR, KinBrand
from cleaning_agent.adapters.gold_package import (
    FileGoldPackage,
    GoldPackageError,
    flat_text,
)
from cleaning_agent.adapters.prospection_map import map_prospects
from cleaning_agent.domain.gold_package import (
    KO_COLUMNS,
    canonical_names,
    coordinates_swapped,
    package_qa,
    period_label,
    priority_label,
)
from cleaning_agent.domain.models import GoldPackageRequest

BRAND = KinBrand(BUNDLED_ASSETS_DIR)
TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "cleaning_agent/adapters/assets/prospecting_deck_template.pptx"
)
CATEGORIES = [
    "Restaurant",
    "Bar",
    "Cafe",
    "Pizza Restaurant",
    "Hotel",
    "Gym",
    "Bakery",
    "Pub",
    "Taco Place",
]


def _scored(n: int = 40) -> pl.DataFrame:
    # Synthetic prospects around a fake city centre; names are invented
    return pl.DataFrame(
        {
            "dataplor_id": [f"dp{i}" for i in range(n)],
            # One name with a comma, quotes and a line break: the CSV must survive it
            "name": [
                'Negocio Ficticio 1, "El Norte"\nSucursal'
                if i == 1
                else f"Negocio Ficticio {i}"
                for i in range(n)
            ],
            "business_category": [CATEGORIES[i % len(CATEGORIES)] for i in range(n)],
            "city": ["Ciudad A" if i % 3 else "Ciudad B" for i in range(n)],
            "state": ["Provincia X"] * n,
            "country": ["Argentina"] * n,
            "latitude": [str(-31.40 + i * 0.002) for i in range(n)],
            "longitude": [str(-64.18 - i * 0.002) for i in range(n)],
            "channel_cat": ["On Premise"] * n,
            "probability_existence_cat": [
                ("high", "moderate", "low")[i % 3] for i in range(n)
            ],
            "weighted_combined_score": [
                str(round(0.9 - i * 0.02, 3)) for i in range(n)
            ],
            "hex_id": ["x"] * n,
            "pop_density": ["high"] * n,
            "car_mobility": ["low"] * n,
            "walk_mobility": ["moderate"] * n,
            "dist_to_main_road": ["120"] * n,
            "dist_to_bus_stop": ["340"] * n,
            # "$$" broke the deck preview once (read as a math formula): keep it here
            "price_level": [("$", "$$", None)[i % 3] for i in range(n)],
            "number_of_reviews": ["10"] * n,
            "average_stars": ["4.1"] * n,
            "monday_hours": ["08:00-20:00"] * n,
            "friday_hours": ["08:00-23:00"] * n,
            "saturday_hours": ["10:00-23:00"] * n,
            # Dataplor sends JSON inside these columns; the CSV must flatten it
            "historical_popularity_scores": ['{"2024-11":0.9942,"2024-12":0.5}'] * n,
            "place_attributes": [
                '{"environment_cozy":true,"service_takeout":true}' if i % 2 else "{}"
                for i in range(n)
            ],
        }
    )


def _clients() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "pos_id": ["c1", "c2", "c3"],
            "pos_name": [
                "Cliente Ficticio 1",
                "Cliente Ficticio 2",
                "Cliente Ficticio 3",
            ],
            "pos_latitude": ["-31.4001", "-31.3500", "bad"],
            "pos_longitude": ["-64.1801", "-64.2500", "-64.0"],
            "pos_gerencia": ["Centro", "Centro", "Norte"],
            "pos_jefatura": ["J1", "J2", "J3"],
            "pos_city": ["Ciudad A", "Ciudad B", "Ciudad A"],
        }
    )


@pytest.fixture
def request_(tmp_path: Path) -> GoldPackageRequest:
    _scored().write_csv(tmp_path / "scored.csv")
    _clients().write_csv(tmp_path / "clients.csv")
    return GoldPackageRequest(
        scored_file="scored.csv",
        clients_file="clients.csv",
        out_dir=tmp_path / "gold",
        bottler="andina",
        bottler_label="Andina",
        client_label="Coca-Cola Andina",
        country="ar",
        country_name="argentina",
        country_label="Argentina",
        period="202611",
        period_label="Noviembre 2026",
        clients_total=3,
        dataplor_total=45,
        matched=5,
        run_name="t1",
        contacts=["equipo@example.com"],
    )


def test_priority_classes_and_period_label():
    assert priority_label("dentro", "high") == (1, "1. Dentro · High")
    assert priority_label("fuera", "low") == (6, "6. Fuera · Low")
    assert period_label("202611") == "Noviembre 2026"
    with pytest.raises(ValueError):
        period_label("202613")


def test_package_qa_catches_names_in_the_ko_file():
    assert package_qa(10, 10, 10, list(KO_COLUMNS), 10)["qa_ok"]
    broken = package_qa(10, 10, 9, [*KO_COLUMNS, "name", "ref_pos_name_cercano"], 8)
    assert [c["ok"] for c in broken["checks"]] == [False, False, False]


def test_package_has_ko_bottler_excel_maps_and_deck(
    tmp_path: Path, request_: GoldPackageRequest
):
    result = FileGoldPackage(tmp_path, BRAND, TEMPLATE).build(request_)

    out = request_.out_dir
    assert (
        result.rows == result.ko_rows == result.bottler_rows == 40
        and result.prioritized == 40
    )
    ko = pl.read_csv(
        out / "results_ko" / request_.names()["ko_csv"], infer_schema=False
    )
    assert tuple(ko.columns) == KO_COLUMNS
    bottler = pl.read_csv(
        out / "results_bottler" / request_.names()["bottler_csv"], infer_schema=False
    )
    assert bottler.columns[:4] == [
        "poi_ref",
        "dataplor_id",
        "prioridad",
        "prioridad_orden",
    ]
    assert "dataplor_id" not in ko.columns and "region" not in bottler.columns
    assert {
        "ref_pos_name_cercano",
        "ref_pos_jefatura_cercano",
        "dist_ref_m",
        "area",
        "hex_7",
        "hex_9",
    } <= set(bottler.columns)
    # The prospect on top of client c1 is inside the routes; the invalid client is ignored
    first = bottler.filter(pl.col("dataplor_id") == "dp0").row(0, named=True)
    assert first["area"] == "dentro" and first["ref_pos_id_cercano"] == "c1"
    assert first["prioridad"] == "1. Dentro · High"

    wb = load_workbook(out / request_.names()["xlsx"])
    assert wb.sheetnames == ["Resumen_Ejecutivo", "Por_Ciudad", "Por_Provincia"]

    ko_map = (out / "results_ko" / request_.names()["ko_map"]).read_text(
        encoding="utf-8"
    )
    bottler_map = (out / "results_bottler" / request_.names()["bottler_map"]).read_text(
        encoding="utf-8"
    )
    payloads = {}
    for name, page in (("ko", ko_map), ("bottler", bottler_map)):
        # The Esri basemap tiles are the only network use: no CDN, no other API
        tile_host = "https://server.arcgisonline.com/ArcGIS/rest/services/"
        urls = re.findall(r"https?://", page)
        assert urls and page.count(tile_host) == len(urls), "only the basemap tiles"
        assert "OpenStreetMap" in page and "Esri" in page  # attribution required
        assert "<canvas" in page and "--ka-color-yellow" in page
        # One H3 grid per zoom band: region, city, neighbourhood
        data = json.loads(
            page.split("<script>const D=", 1)[1]
            .split(";const P=", 1)[0]
            .replace(r"<\/", "</")
        )
        assert [g["r"] for g in data["res"]] == [7, 8, 9]
        assert all(len(g["hex"]) == 40 for g in data["res"])
        payloads[name] = data
    # KO is hexagons only: no coordinate of a prospect or a client, no client count
    ko, bottler = payloads["ko"], payloads["bottler"]
    assert ko["ko"] and not (ko["lat"] or ko["lon"] or ko["cLat"] or ko["cLon"])
    assert all(g["clients"] == [] for g in ko["res"])
    assert len(bottler["lat"]) == 40 and len(bottler["cLat"]) == 2
    assert all(len(g["clients"]) == 2 for g in bottler["res"])
    assert "Negocio Ficticio" not in ko_map and "Cliente Ficticio" not in ko_map
    assert "Negocio Ficticio" in bottler_map and "Cliente Ficticio 1" in bottler_map

    deck = Presentation(str(out / request_.names()["deck"]))
    text = " ".join(
        shape.text_frame.text
        for slide in deck.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "{{" not in text and "Coca-Cola Andina" in text and "Noviembre 2026" in text
    assert "Golfo" not in text and "FEMSA" not in text and "equipo@example.com" in text


def test_swapped_client_coordinates_are_detected_and_fixed(
    tmp_path: Path, request_: GoldPackageRequest
):
    clients = _clients()
    # Same base with latitude and longitude in each other's column (as in Andina)
    clients.with_columns(
        pl.col("pos_longitude").alias("pos_latitude"),
        pl.col("pos_latitude").alias("pos_longitude"),
    ).write_csv(tmp_path / "clients.csv")

    result = FileGoldPackage(tmp_path, BRAND, TEMPLATE).build(request_)

    assert result.client_coordinates_swapped
    bottler = pl.read_csv(
        request_.out_dir / "results_bottler" / request_.names()["bottler_csv"],
        infer_schema=False,
    )
    first = bottler.filter(pl.col("dataplor_id") == "dp0").row(0, named=True)
    assert first["area"] == "dentro" and first["ref_pos_id_cercano"] == "c1"


def test_province_spellings_are_grouped_for_the_map_selectors():
    values = (
        ["Córdoba"] * 5
        + ["Provincia de Córdoba", "Cordoba", "Santa Fe"] * 1
        + ["Santa Fe Province", "Santa Fé", "Mendoza, Mendoza Province", ""]
    )

    names = canonical_names(values)

    assert names["Provincia de Córdoba"] == names["Cordoba"] == "Córdoba"
    assert names["Santa Fe Province"] == names["Santa Fé"] == "Santa Fe"
    assert names["Mendoza, Mendoza Province"] == "Mendoza" and names[""] == ""


def test_coordinates_swapped_rule():
    lat_range, lon_range = (-32.0, -30.0), (-65.0, -63.0)
    assert coordinates_swapped([-64.1, -63.9], [-31.2, -30.8], lat_range, lon_range)
    assert not coordinates_swapped([-31.2, -30.8], [-64.1, -63.9], lat_range, lon_range)


def test_client_base_without_the_configured_columns_stops(
    tmp_path: Path, request_: GoldPackageRequest
):
    _clients().drop("pos_jefatura").write_csv(tmp_path / "clients.csv")

    with pytest.raises(GoldPackageError, match="pos_jefatura"):
        FileGoldPackage(tmp_path, BRAND, TEMPLATE).build(request_)


def test_map_leaves_out_prospects_without_place_or_score():
    frame = pl.DataFrame(
        {
            "city": ["Ciudad A", "", None, "Ciudad B", "Ciudad C"],
            "state": ["Provincia X", "Provincia X", "Provincia X", None, "Provincia X"],
            "weighted_combined_score": ["0.5", "0.5", "0.5", "0.5", "0"],
        }
    )
    kept = map_prospects(frame)
    # Only the first row has city, province and a score above 0
    assert kept.get_column("city").to_list() == ["Ciudad A"]


def test_build_maps_rewrites_only_the_maps(
    tmp_path: Path, request_: GoldPackageRequest
):
    package = FileGoldPackage(tmp_path, BRAND, TEMPLATE)
    package.build(request_)
    out, names = request_.out_dir, request_.names()
    untouched = [
        out / names["xlsx"],
        out / names["deck"],
        out / "results_ko" / names["ko_csv"],
        out / "results_bottler" / names["bottler_csv"],
    ]
    before = {p: p.read_bytes() for p in untouched}
    ko_map = out / "results_ko" / names["ko_map"]
    ko_map.write_text("old map", encoding="utf-8")

    maps = package.build_maps(request_)

    assert maps == [str(ko_map), str(out / "results_bottler" / names["bottler_map"])]
    assert "<canvas" in ko_map.read_text(encoding="utf-8")
    # Files already uploaded keep their bytes (size + MD5)
    assert all(p.read_bytes() == before[p] for p in untouched)


def _csv_rows(path: Path) -> tuple[bytes, list[list[str]]]:
    raw = path.read_bytes()
    return raw, list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def test_csvs_keep_the_golfo_format_and_poi_ref(
    tmp_path: Path, request_: GoldPackageRequest
):
    FileGoldPackage(tmp_path, BRAND, TEMPLATE).build(request_)
    out, names = request_.out_dir, request_.names()
    ko_path = out / "results_ko" / names["ko_csv"]
    bottler_path = out / "results_bottler" / names["bottler_csv"]
    for path in (ko_path, bottler_path):
        raw, rows = _csv_rows(path)
        # UTF-8 BOM, CRLF, one record per line, same width on every row
        assert raw.startswith(b"\xef\xbb\xbf")
        assert raw.count(b"\r\n") == raw.count(b"\n") == len(rows) == 41
        assert {len(r) for r in rows} == {len(rows[0])}
        # No field needs quotes: spreadsheets cannot split or shift a row
        assert b'"' not in raw and all("," not in f for r in rows for f in r)
    _, bottler = _csv_rows(bottler_path)
    head = bottler[0]
    by_ref = {r[head.index("poi_ref")]: r for r in bottler[1:]}
    # The awkward name survives quoted, its line break turned into a space
    assert "Negocio Ficticio 1 - 'El Norte' Sucursal" in {
        r[head.index("name")] for r in bottler[1:]
    }
    # poi_ref is 1..N in priority order and crosses KO and BOTTLER
    refs = [int(r[0]) for r in bottler[1:]]
    assert refs == list(range(1, 41))
    orders = [int(r[head.index("prioridad_orden")]) for r in bottler[1:]]
    assert orders == sorted(orders)
    _, ko = _csv_rows(ko_path)
    for row in ko[1:]:
        assert row[ko[0].index("prioridad")] == by_ref[row[0]][head.index("prioridad")]


def test_package_qa_stops_a_ko_file_with_the_dataplor_id():
    broken = package_qa(10, 10, 10, ["poi_ref", "dataplor_id"], 10)
    assert not broken["qa_ok"]


def test_region_only_when_the_territory_names_its_regions(
    tmp_path: Path, request_: GoldPackageRequest
):
    def square(lon0: float, lon1: float) -> dict[str, object]:
        ring = [
            [lon0, -32.0],
            [lon1, -32.0],
            [lon1, -31.0],
            [lon0, -31.0],
            [lon0, -32.0],
        ]
        return {"type": "Polygon", "coordinates": [ring]}

    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"region": "Este"},
                "geometry": square(-64.2, -64.0),
            },
            {
                "type": "Feature",
                "properties": {"region": "Oeste"},
                "geometry": square(-65.0, -64.2),
            },
        ],
    }
    (tmp_path / "territorio.geojson").write_text(json.dumps(geo), encoding="utf-8")
    named = request_.model_copy(update={"territory_geojson": "territorio.geojson"})
    FileGoldPackage(tmp_path, BRAND, TEMPLATE).build(named)
    names = named.names()
    bottler = pl.read_csv(
        named.out_dir / "results_bottler" / names["bottler_csv"], infer_schema=False
    )
    ko = pl.read_csv(named.out_dir / "results_ko" / names["ko_csv"], infer_schema=False)
    assert set(bottler.get_column("region").to_list()) == {"Este", "Oeste"}
    assert ko.columns[ko.columns.index("area") + 1] == "region"


def test_flat_text_turns_json_and_free_text_into_one_safe_field():
    assert (
        flat_text('{"2024-11":0.9942,"2024-12":0.5}')
        == "2024-11: 0.9942 | 2024-12: 0.5"
    )
    assert flat_text('{"environment_cozy":true,"service_takeout":true}') == (
        "environment_cozy | service_takeout"
    )
    assert flat_text("{}") is None  # written as an empty field
    assert flat_text('["08:00-12:00","16:00-20:00"]') == "08:00-12:00 | 16:00-20:00"
    assert flat_text('Bar "El Sol", Centro\nLocal 2') == "Bar 'El Sol' - Centro Local 2"
    assert flat_text("08:00-20:00") == "08:00-20:00"
    assert flat_text(None) is None
