"""QA de la prospección: falsos negativos del Datamatch y lectura por categoría.

Después del último paso del Datamatch (user, 2026-11-23: "agrega este qa después de
pasar los pasos") se audita el resultado, siguiendo la skill ``prospection-qa``:

- ``match``: puntos Dataplor que algún paso del ciclo asignó a un cliente;
- ``no_match``: los que van a quedar como prospectos;
- un **falso negativo** es un ``no_match`` que en realidad es un cliente de la base:
  nombre distintivo parecido y cerca. Se mide con un score combinado
  ``0.4 · geo + 0.6 · nombre``; ninguno de los dos basta solo (un local vecino con otro
  nombre es otro negocio; un nombre igual lejos suele ser una cadena).

El nombre mezcla fuzzy (``token_sort_ratio``: errores de tipeo, abreviaturas, orden) y
coseno TF-IDF sobre todos los nombres de ambas bases, que baja el peso de las palabras
que están en todos lados ("kiosco", "almacén", "bar") y sube el de las distintivas.

Funciones puras: ni archivos ni red. El adaptador lee las bases y escribe las salidas.
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz.fuzz import token_sort_ratio
from unidecode import unidecode

# Distancia a la que el score geográfico llega a 0. Más allá el par no puede llegar al
# umbral: con geo = 0 el combinado es como mucho 0.6 < 0.65, así que solo se buscan
# candidatos dentro de este radio (exacto, no una aproximación).
GEO_RADIUS_M = 300.0
GEO_WEIGHT = 0.4
NAME_WEIGHT = 0.6
FUZZY_WEIGHT = 0.5  # nombre = 0.5 · fuzzy + 0.5 · TF-IDF
MISTAKE_THRESHOLD = 0.65
BOTH_STRONG = 0.6
EARTH_RADIUS_M = 6_371_008.8

# Columnas de categoría, en orden de preferencia (la skill: business_category, channel…)
DATAPLOR_CATEGORY_COLUMNS = ("business_category", "category", "sub_category")
CLIENT_CATEGORY_COLUMNS = (
    "pos_subchannel",
    "pos_channel",
    "business_category",
    "category",
    "trade_channel",
    "channel",
    "segment",
    "pos_consumer_type",
)

MatchReason = Literal["both_strong", "proximity_dominant", "name_dominant"]
Confidence = Literal["High", "Medium", "Low"]

# Prioridad de ``excluding_suggestion`` cuando aplica más de una (la skill)
SUGGESTIONS = (
    "false_negative_both_strong",
    "false_negative_proximity",
    "false_negative_name_similarity",
    "false_negative_category",
    "no_beverage_category",
)
REASON_SUGGESTION: dict[str, str] = {
    "both_strong": "false_negative_both_strong",
    "proximity_dominant": "false_negative_proximity",
    "name_dominant": "false_negative_name_similarity",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(name: str | None) -> list[str]:
    """Palabras del nombre, sin acentos y en minúsculas ("Almacén Don José" -> 3)."""
    return _TOKEN.findall(unidecode(name or "").lower())


def build_idf(names: Iterable[str | None]) -> dict[str, float]:
    """IDF de cada palabra: cada nombre es un documento, ``log(N / (1 + df))``."""
    df: Counter[str] = Counter()
    n = 0
    for name in names:
        n += 1
        df.update(set(tokenize(name)))
    return {t: math.log(n / (1 + c)) for t, c in df.items()} if n else {}


def tfidf_cosine(a: str | None, b: str | None, idf: Mapping[str, float]) -> float:
    """Coseno entre los vectores TF-IDF de dos nombres (0 si alguno queda vacío)."""
    ta, tb = Counter(tokenize(a)), Counter(tokenize(b))
    if not ta or not tb:
        return 0.0
    dot = na = nb = 0.0
    for t in ta.keys() | tb.keys():
        # Una palabra en casi todos los nombres puede dar IDF <= 0: no aporta
        w = max(idf.get(t, 1.0), 0.0)
        va, vb = ta.get(t, 0) * w, tb.get(t, 0) * w
        dot += va * vb
        na += va * va
        nb += vb * vb
    return dot / math.sqrt(na * nb) if na > 0 and nb > 0 else 0.0


def fuzzy_pct(a: str | None, b: str | None) -> float:
    """token_sort_ratio 0-100 sobre los nombres normalizados."""
    return float(token_sort_ratio(" ".join(tokenize(a)), " ".join(tokenize(b))))


def name_score(a: str | None, b: str | None, idf: Mapping[str, float]) -> float:
    return FUZZY_WEIGHT * fuzzy_pct(a, b) / 100 + (1 - FUZZY_WEIGHT) * tfidf_cosine(
        a, b, idf
    )


def geo_score(distance_m: float) -> float:
    """1 en el mismo punto, 0 a GEO_RADIUS_M o más (lineal)."""
    return max(0.0, 1.0 - distance_m / GEO_RADIUS_M)


def combined_score(geo: float, name: float) -> float:
    return GEO_WEIGHT * geo + NAME_WEIGHT * name


def match_reason(geo: float, name: float) -> MatchReason:
    if geo >= BOTH_STRONG and name >= BOTH_STRONG:
        return "both_strong"
    return "proximity_dominant" if geo > name else "name_dominant"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))


@dataclass(frozen=True)
class Outlet:
    """Un punto (Dataplor o cliente) con lo mínimo para comparar."""

    id: str
    name: str
    lat: float
    lon: float
    category: str = ""


@dataclass(frozen=True)
class Mistake:
    """Un no_match que parece un cliente de la base: el par con el mejor score."""

    prospect: Outlet
    client: Outlet
    distance_m: float
    fuzzy_pct: float
    tfidf: float
    name: float
    geo: float
    combined: float
    reason: MatchReason


@dataclass
class _Grid:
    """Índice por celdas de ~GEO_RADIUS_M: cada punto solo se compara con sus vecinos."""

    cell_deg: float
    cells: dict[tuple[int, int], list[Outlet]] = field(default_factory=dict)

    def key(self, lat: float, lon: float) -> tuple[int, int]:
        return math.floor(lat / self.cell_deg), math.floor(lon / self.cell_deg)

    def add(self, o: Outlet) -> None:
        self.cells.setdefault(self.key(o.lat, o.lon), []).append(o)

    def near(self, lat: float, lon: float, reach: int) -> Iterable[Outlet]:
        i, j = self.key(lat, lon)
        for di in range(-1, 2):
            for dj in range(-reach, reach + 1):
                yield from self.cells.get((i + di, j + dj), ())


def find_mistakes(
    no_match: Sequence[Outlet],
    clients: Sequence[Outlet],
    idf: Mapping[str, float],
    threshold: float = MISTAKE_THRESHOLD,
) -> list[Mistake]:
    """Para cada no_match, el cliente con mayor score combinado; falso negativo si
    llega al umbral. Solo se miran clientes a menos de GEO_RADIUS_M (ver arriba)."""
    cell_deg = GEO_RADIUS_M / 111_320.0  # grados de latitud en GEO_RADIUS_M
    grid = _Grid(cell_deg)
    for c in clients:
        grid.add(c)
    found: list[Mistake] = []
    for p in no_match:
        # Un grado de longitud se achica con la latitud: más celdas a lo ancho
        reach = math.ceil(1 / max(math.cos(math.radians(p.lat)), 0.05))
        best: Mistake | None = None
        for c in grid.near(p.lat, p.lon, reach):
            d = haversine_m(p.lat, p.lon, c.lat, c.lon)
            geo = geo_score(d)
            if geo <= 0:
                continue
            fz = fuzzy_pct(p.name, c.name)
            tf = tfidf_cosine(p.name, c.name, idf)
            name = FUZZY_WEIGHT * fz / 100 + (1 - FUZZY_WEIGHT) * tf
            score = combined_score(geo, name)
            if best is None or score > best.combined:
                best = Mistake(
                    p, c, d, fz, tf, name, geo, score, match_reason(geo, name)
                )
        if best is not None and best.combined >= threshold:
            found.append(best)
    return sorted(found, key=lambda m: -m.combined)


def reason_counts(mistakes: Sequence[Mistake]) -> dict[str, int]:
    counts = Counter(m.reason for m in mistakes)
    return {
        r: counts.get(r, 0)
        for r in ("proximity_dominant", "name_dominant", "both_strong")
    }


@dataclass(frozen=True)
class CategoryShare:
    category: str
    total: int
    match: int
    no_match: int

    @property
    def no_match_pct(self) -> float:
        return round(100 * self.no_match / self.total, 2) if self.total else 0.0


def category_shares(
    match_categories: Iterable[str | None], no_match_categories: Iterable[str | None]
) -> list[CategoryShare]:
    """Match / no_match por categoría, de mayor a menor share de no_match."""
    m = Counter((c or "(sin categoría)") for c in match_categories)
    n = Counter((c or "(sin categoría)") for c in no_match_categories)
    rows = [CategoryShare(c, m[c] + n[c], m[c], n[c]) for c in m.keys() | n.keys()]
    return sorted(rows, key=lambda r: (-r.no_match_pct, -r.total, r.category))


def excluding_suggestion(
    prospect_id: str,
    category: str | None,
    mistakes_by_id: Mapping[str, MatchReason],
    mapped: Mapping[str, tuple[str, Confidence]],
    client_categories: set[str],
    non_beverage: set[str],
) -> str:
    """La sugerencia de mayor prioridad para un no_match ("" si es un no_match genuino)."""
    reason = mistakes_by_id.get(prospect_id)
    if reason is not None:
        return REASON_SUGGESTION[reason]
    target = mapped.get(category or "")
    if target and target[0] in client_categories and target[1] in ("High", "Medium"):
        return "false_negative_category"
    if (category or "") in non_beverage:
        return "no_beverage_category"
    return ""


def market_verdict(
    match_rate_pct: float, penetration_pct: float | None
) -> Literal["consistent", "under_matched", "insufficient"]:
    """Regla de la skill: penetración alta (> 60 %) y match muy bajo (< 20 %) = alerta."""
    if penetration_pct is None:
        return "insufficient"
    if penetration_pct > 60 and match_rate_pct < 20:
        return "under_matched"
    return "consistent"


def pick_column(columns: Sequence[str], candidates: Sequence[str]) -> str:
    """Primera columna candidata presente (sin distinguir mayúsculas), "" si ninguna."""
    lower = {c.lower(): c for c in columns}
    return next((lower[c.lower()] for c in candidates if c.lower() in lower), "")


def parse_reason(value: str) -> MatchReason | None:
    """The match reason stored in the graph state (plain text) back as its literal."""
    for reason in ("both_strong", "proximity_dominant", "name_dominant"):
        if value == reason:
            return reason
    return None
