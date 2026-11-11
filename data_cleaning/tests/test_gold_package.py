"""Gold delivery package: real adapter on synthetic data (no production data)."""

import re
from pathlib import Path

import polars as pl
import pytest
from openpyxl import load_workbook
from pptx import Presentation

from cleaning_agent.adapters.brand import BUNDLED_ASSETS_DIR, KinBrand
from cleaning_agent.adapters.gold_package import FileGoldPackage, GoldPackageError
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
            "name": [f"Negocio Ficticio {i}" for i in range(n)],
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
    assert bottler.columns[:3] == ["dataplor_id", "prioridad", "prioridad_orden"]
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
    for page in (ko_map, bottler_map):
        assert not re.search(r"https?://", page), "the map must not call any URL / API"
        assert "<canvas" in page and "--ka-color-yellow" in page
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
