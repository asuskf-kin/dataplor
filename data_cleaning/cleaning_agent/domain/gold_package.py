"""Gold delivery package of a prospecting run (modelled on the approved Golfo package).

One package per bottler and period, in the gold folder of the prospects:

- KO version: anonymous (no name, coordinates, Dataplor id or client data), hexagons
  instead; rows are referenced by ``poi_ref``;
- BOTTLER version: every column plus the nearest current client, with the same
  ``poi_ref`` so both versions can be crossed (as in the approved Golfo package);
- opportunity Excel, one map per audience and the results deck.

Pure rules only: priority classes, column contracts and the figures of the Excel and
the deck. Files, maps and slides are written by the adapters.
"""

import re
from typing import Any

import numpy as np
import polars as pl
from unidecode import unidecode

# A prospect within this distance of a current client is "dentro" (inside the routes)
AREA_RADIUS_M = 300.0
INSIDE, OUTSIDE = "dentro", "fuera"
EXISTENCE = ("high", "moderate", "low")
HIGH_MODERATE = ("high", "moderate")
OTHERS = "Otros"

# KO: what Coca-Cola sees. No name, address, coordinates, Dataplor id (it leads back
# to the place) or client data; poi_ref is the shared key with the BOTTLER version.
KO_COLUMNS = (
    "poi_ref",
    "prioridad",
    "prioridad_orden",
    "area",
    "probability_existence_cat",
    "business_category",
    "channel_cat",
    "city",
    "state",
    "country",
    "pop_density",
    "car_mobility",
    "walk_mobility",
    "dist_to_main_road",
    "dist_to_bus_stop",
    "weighted_combined_score",
    "hex_7",
    "hex_8",
    "hex_9",
)
HEX_RESOLUTIONS = (7, 8, 9)
# Sub-territory of the bottler (e.g. Golfo / Centro Pacífico); only when the territory
# GeoJSON names its regions, otherwise the column is not written
REGION = "region"
# Never in the KO version
KO_FORBIDDEN = ("name", "latitude", "longitude", "address", "dataplor_id")
MONTHS = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)  # fmt: skip


def coordinates_swapped(
    client_lat: list[float],
    client_lon: list[float],
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    margin: float = 0.5,
) -> bool:
    """True when the client base has latitude and longitude in each other's column.

    Seen in the Andina base (pos_latitude ~ -64, pos_longitude ~ -31): the clients
    fall in the prospects' area only once the two columns are exchanged.
    """

    def inside(lats: list[float], lons: list[float]) -> int:
        return sum(
            lat_range[0] - margin <= a <= lat_range[1] + margin
            and lon_range[0] - margin <= b <= lon_range[1] + margin
            for a, b in zip(lats, lons, strict=True)
        )

    return inside(client_lon, client_lat) > inside(client_lat, client_lon)


_REGION_AFFIXES = re.compile(
    r"^(provincia\s+de\s+|province\s+of\s+)|(\s+province|\s+provincia)$", re.IGNORECASE
)


def _region_key(name: str) -> str:
    # "Mendoza, Mendoza Province" -> "mendoza"; accents and affixes do not count
    text = name.split(",")[-1].strip()
    text = _REGION_AFFIXES.sub("", text).strip()
    return unidecode(text).lower()


def canonical_names(values: list[str]) -> dict[str, str]:
    """Each spelling -> the most frequent spelling of its group (Dataplor mixes
    "Córdoba", "Provincia de Córdoba", "Cordoba"; "Santa Fe Province", "Santa Fé")."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best: dict[str, str] = {}
    # Most frequent first: the first spelling seen for a key is the canonical one
    for value, _count in sorted(counts.items(), key=lambda item: -item[1]):
        key = _region_key(value) if value else ""
        clean = _REGION_AFFIXES.sub("", value.split(",")[-1].strip()).strip()
        best.setdefault(key, clean or value)
    return {value: best[_region_key(value) if value else ""] for value in counts}


def _blank(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Utf8).str.strip_chars().fill_null("") == ""


def fill_place_from_nearest(prospects: pl.DataFrame, column: str) -> pl.DataFrame:
    """Give a point without ``column`` (city, state) the value of its nearest named point.

    User, 2026-11-23: "si no tiene ciudad búscala por su lat long y agrégala; si no
    encuentras, dale el punto a la ciudad más cercana". Without a geocoding service
    (coordinates never leave the machine), the nearest prospect that does carry the
    name answers both: a point inside a city has a named neighbour metres away, and an
    isolated one goes to the closest city. Rows without valid coordinates keep the gap.
    """
    if column not in prospects.columns:
        return prospects
    lat = pl.col("latitude").cast(pl.Float64, strict=False)
    lon = pl.col("longitude").cast(pl.Float64, strict=False)
    indexed = prospects.with_row_index("_row").with_columns(
        _lat=lat, _lon=lon, _blank=_blank(column)
    )
    valid = pl.col("_lat").is_between(-90, 90) & pl.col("_lon").is_between(-180, 180)
    named = indexed.filter(~pl.col("_blank") & valid)
    missing = indexed.filter(pl.col("_blank") & valid)
    if named.is_empty() or missing.is_empty():
        return prospects
    ref_lat = np.radians(named["_lat"].to_numpy())
    ref_lon = np.radians(named["_lon"].to_numpy())
    names = named[column].cast(pl.Utf8).to_list()
    filled: dict[int, str] = {}
    for row, a, b in zip(
        missing["_row"].to_list(),
        np.radians(missing["_lat"].to_numpy()),
        np.radians(missing["_lon"].to_numpy()),
        strict=True,
    ):
        # Haversine without the constant factor: only the argmin matters
        h = np.sin((ref_lat - a) / 2) ** 2 + np.cos(a) * np.cos(ref_lat) * np.sin((ref_lon - b) / 2) ** 2
        filled[int(row)] = names[int(np.argmin(h))]
    patch = pl.DataFrame(
        {"_row": list(filled), "_fill": list(filled.values())},
        schema={"_row": pl.UInt32, "_fill": pl.Utf8},
    )
    return (
        indexed.join(patch, on="_row", how="left")
        .with_columns(pl.coalesce(pl.col("_fill"), pl.col(column).cast(pl.Utf8)).alias(column))
        .drop("_row", "_lat", "_lon", "_blank", "_fill")
    )


def period_label(period: str) -> str:
    """202611 -> 'Noviembre 2026' (the deck's cover date)."""
    if len(period) != 6 or not period.isdigit() or not 1 <= int(period[4:]) <= 12:
        raise ValueError(f"period must be AAAAMM, got {period!r}")
    return f"{MONTHS[int(period[4:]) - 1]} {period[:4]}"


def package_qa(
    scored_rows: int,
    ko_rows: int,
    bottler_rows: int,
    ko_columns: list[str],
    priorities: int,
) -> dict[str, Any]:
    """Checks of the package before it goes to gold."""
    leaked = [c for c in ko_columns if c in KO_FORBIDDEN or c.startswith("ref_")]
    checks = [
        {
            "check": "KO y BOTTLER tienen las filas de la priorización",
            "ok": ko_rows == bottler_rows == scored_rows,
            "detail": f"KO {ko_rows:,} · BOTTLER {bottler_rows:,} · priorización {scored_rows:,}",
        },
        {
            "check": "La versión KO no trae nombres, coordenadas, dataplor_id ni datos de clientes",
            "ok": not leaked,
            "detail": "ninguna" if not leaked else ", ".join(leaked),
        },
        {
            "check": "Todos los puntos tienen prioridad (1 a 6)",
            "ok": priorities == scored_rows,
            "detail": f"{priorities:,} de {scored_rows:,}",
        },
    ]
    return {
        "filas_leidas": scored_rows,
        "filas_conservadas": ko_rows,
        "filas_eliminadas": scored_rows - ko_rows,
        "pct_eliminado": 0.0,
        "eliminadas_por_motivo": {},
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }


def priority_label(area: str, existence: str) -> tuple[int, str]:
    """1. Dentro · High ... 6. Fuera · Low: inside the routes first, then existence."""
    if area not in (INSIDE, OUTSIDE) or existence not in EXISTENCE:
        raise ValueError(f"unknown area/existence: {area!r}, {existence!r}")
    order = (0 if area == INSIDE else 3) + EXISTENCE.index(existence) + 1
    return order, f"{order}. {area.capitalize()} · {existence.capitalize()}"


def with_priority(prospects: pl.DataFrame) -> pl.DataFrame:
    """Adds area (from dist_ref_m) and the 6-class priority to the scored prospects."""
    area = (
        pl.when(pl.col("dist_ref_m") <= AREA_RADIUS_M)
        .then(pl.lit(INSIDE))
        .otherwise(pl.lit(OUTSIDE))
    )
    framed = prospects.with_columns(area.alias("area"))
    labels = {
        (a, e): priority_label(a, e) for a in (INSIDE, OUTSIDE) for e in EXISTENCE
    }
    key = pl.concat_str(
        ["area", pl.col("probability_existence_cat").str.to_lowercase()], separator="|"
    )
    return framed.with_columns(
        key.replace_strict(
            {f"{a}|{e}": v[1] for (a, e), v in labels.items()}, default=None
        ).alias("prioridad"),
        key.replace_strict(
            {f"{a}|{e}": str(v[0]) for (a, e), v in labels.items()}, default=None
        ).alias("prioridad_orden"),
    )


def with_poi_ref(prospects: pl.DataFrame) -> pl.DataFrame:
    """Rows in priority order (class, then score, then id) numbered 1..N as poi_ref."""
    score = pl.col("weighted_combined_score").cast(pl.Float64, strict=False)
    ordered = prospects.sort(
        [pl.col("prioridad_orden"), score, pl.col("dataplor_id")],
        descending=[False, True, False],
        nulls_last=True,
    )
    return ordered.with_columns(
        pl.int_range(1, ordered.height + 1, dtype=pl.Int64).alias("poi_ref")
    )


def ko_columns(has_region: bool) -> list[str]:
    """KO order; region right after area when the territory names its regions."""
    cols = list(KO_COLUMNS)
    if has_region:
        cols.insert(cols.index("area") + 1, REGION)
    return cols


def bottler_columns(
    scored: list[str], ref_columns: list[str], has_region: bool = False
) -> list[str]:
    """BOTTLER order (Golfo): poi_ref, id, priority, scored columns, nearest client,
    area, region, hexes."""
    head = ["poi_ref", "dataplor_id", "prioridad", "prioridad_orden"]
    tail = [
        *ref_columns,
        "dist_ref_m",
        "area",
        *([REGION] if has_region else []),
        *(f"hex_{r}" for r in HEX_RESOLUTIONS),
    ]
    middle = [c for c in scored if c not in head and c not in tail]
    return [*head, *middle, *tail]


def _share(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def opportunity_summary(
    prospects: pl.DataFrame, clients_total: int
) -> list[dict[str, Any]]:
    """Resumen ejecutivo: universe = prospects + current clients (Golfo definition)."""
    total = prospects.height
    inside = prospects.filter(pl.col("area") == INSIDE).height
    universe = total + clients_total
    return [
        {
            "nivel": f"Total {label}",
            "universo": universe,
            "bottler": clients_total,
            "oportunidad": count,
            "pct": _share(count, universe),
        }
        for label, count in (
            ("", total),
            ("dentro del área", inside),
            ("fuera del área", total - inside),
        )
    ]


def opportunity_by(
    prospects: pl.DataFrame,
    group: str,
    clients_by_group: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Opportunity per city/state, sorted, with the cumulative share of the total."""
    counts = (
        prospects.group_by(group)
        .agg(
            pl.len().alias("oportunidad"),
            (pl.col("area") == INSIDE).sum().alias("dentro"),
        )
        .sort("oportunidad", descending=True)
    )
    total = prospects.height
    rows: list[dict[str, Any]] = []
    running = 0
    for row in counts.iter_rows(named=True):
        running += int(row["oportunidad"])
        key = str(row[group] or "(sin dato)")
        clients = (clients_by_group or {}).get(key.lower(), 0)
        entry: dict[str, Any] = {
            group: key,
            "oportunidad": int(row["oportunidad"]),
            "dentro": int(row["dentro"]),
            "fuera": int(row["oportunidad"]) - int(row["dentro"]),
            "pct_acumulado": _share(running, total),
        }
        if clients_by_group is not None:
            universe = int(row["oportunidad"]) + clients
            entry |= {
                "universo": universe,
                "bottler": clients,
                "pct": _share(int(row["oportunidad"]), universe),
            }
        rows.append(entry)
    return rows


def _top(frame: pl.DataFrame, column: str, n: int) -> list[tuple[str, int]]:
    counts = (
        frame.group_by(column).len().sort(["len", column], descending=[True, False])
    )
    return [(str(k), int(v)) for k, v in counts.head(n).iter_rows()]


def deck_figures(
    prospects: pl.DataFrame,
    clients_total: int,
    dataplor_total: int,
    matched: int,
    capture: tuple[float, float] = (0.5, 0.7),
) -> dict[str, Any]:
    """Every number the results deck shows, from the prioritised prospects."""
    existence = pl.col("probability_existence_cat").str.to_lowercase()
    by_existence = {e: prospects.filter(existence == e).height for e in EXISTENCE}
    hm = prospects.filter(existence.is_in(HIGH_MODERATE))
    hm_total = hm.height
    hm_inside = hm.filter(pl.col("area") == INSIDE).height

    cities = _top(hm, "city", 3)
    top_cities = [c for c, _ in cities]
    categories = _top(hm, "business_category", 8)
    top5 = [c for c, _ in categories[:5]]

    def category_row(name: str, frame: pl.DataFrame) -> dict[str, Any]:
        return {
            "categoria": name,
            "high": frame.filter(existence == "high").height,
            "moderate": frame.filter(existence == "moderate").height,
            "total": frame.height,
        }

    in_top5 = pl.col("business_category").is_in(top5)
    category_table = [
        category_row(c, hm.filter(pl.col("business_category") == c)) for c in top5
    ]
    category_table.append(category_row(OTHERS, hm.filter(~in_top5)))
    category_table.append(category_row("Total", hm))

    city_cols = top_cities[:2]

    def city_split(frame: pl.DataFrame) -> list[int]:
        values = [frame.filter(pl.col("city") == c).height for c in city_cols]
        return [*values, frame.height - sum(values), frame.height]

    city_table = [
        {
            "categoria": c,
            "valores": city_split(hm.filter(pl.col("business_category") == c)),
        }
        for c in top5
    ]
    city_table.append({"categoria": OTHERS, "valores": city_split(hm.filter(~in_top5))})
    city_table.append({"categoria": "Total", "valores": city_split(hm)})

    ranked = [c for c, _ in _top(hm, "business_category", hm.height or 1)]
    stages: list[dict[str, Any]] = []
    cumulative = 0
    for number, (start, end) in enumerate(((0, 3), (3, 5), (5, 8), (8, None)), start=1):
        names = ranked[start:end]
        count = hm.filter(pl.col("business_category").is_in(names)).height
        cumulative += count
        stages.append(
            {
                "etapa": number,
                "categorias": names[:4] if end is None else names,
                "pos": count,
                "pct": _share(count, clients_total),
                "pct_acumulado": _share(cumulative, clients_total),
            }
        )
    return {
        "dataplor_total": dataplor_total,
        "clients_total": clients_total,
        "matched": matched,
        "no_match": by_existence,
        "no_match_total": prospects.height,
        "hm_total": hm_total,
        "hm_inside": hm_inside,
        "hm_outside": hm_total - hm_inside,
        "pct_outside": _share(hm_total - hm_inside, hm_total),
        "cities": cities,
        "city_others": hm_total - sum(v for _, v in cities),
        "top_city": top_cities[0] if top_cities else "",
        "top_city_count": cities[0][1] if cities else 0,
        "categories": categories,
        "pct_top2": _share(sum(v for _, v in categories[:2]), hm_total),
        "pct_top5": _share(sum(v for _, v in categories[:5]), hm_total),
        "category_table": category_table,
        "city_columns": city_cols,
        "city_table": city_table,
        "stages": stages,
        "pct_growth": _share(hm_total, clients_total),
        "capture_low": round(hm_total * capture[0]),
        "capture_high": round(hm_total * capture[1]),
        "pct_capture_low": _share(round(hm_total * capture[0]), clients_total),
        "pct_capture_high": _share(round(hm_total * capture[1]), clients_total),
    }
