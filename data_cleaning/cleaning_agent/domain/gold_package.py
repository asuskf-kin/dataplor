"""Gold delivery package of a prospecting run (modelled on the approved Golfo package).

One package per bottler and period, in the gold folder of the prospects:

- KO version: anonymous (no name, coordinates or client data), hexagons instead;
- BOTTLER version: every column plus the nearest current client;
- opportunity Excel, one map per audience and the results deck.

Pure rules only: priority classes, column contracts and the figures of the Excel and
the deck. Files, maps and slides are written by the adapters.
"""

import re
from typing import Any

import polars as pl
from unidecode import unidecode

# A prospect within this distance of a current client is "dentro" (inside the routes)
AREA_RADIUS_M = 300.0
INSIDE, OUTSIDE = "dentro", "fuera"
EXISTENCE = ("high", "moderate", "low")
HIGH_MODERATE = ("high", "moderate")
OTHERS = "Otros"

# KO: what Coca-Cola sees. No name, address, coordinates or client data.
KO_COLUMNS = (
    "dataplor_id",
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
    leaked = [
        c
        for c in ko_columns
        if c in ("name", "latitude", "longitude", "address") or c.startswith("ref_")
    ]
    checks = [
        {
            "check": "KO y BOTTLER tienen las filas de la priorización",
            "ok": ko_rows == bottler_rows == scored_rows,
            "detail": f"KO {ko_rows:,} · BOTTLER {bottler_rows:,} · priorización {scored_rows:,}",
        },
        {
            "check": "La versión KO no trae nombres, coordenadas ni datos de clientes",
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


def bottler_columns(scored: list[str], ref_columns: list[str]) -> list[str]:
    """BOTTLER order: id, priority, the scored columns, nearest client, area, hexes."""
    head = ["dataplor_id", "prioridad", "prioridad_orden"]
    tail = [*ref_columns, "dist_ref_m", "area", *(f"hex_{r}" for r in HEX_RESOLUTIONS)]
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
