"""Paso 1 bottler: validación de la base de clientes antes de Datamatch (pura, sin I/O).

Mismas reglas que la validación de clientes del workflow Customer Potential
(``dw_validar``), para que un cliente "válido" signifique lo mismo en los dos procesos:

1. canal elegido (opcional: ``None`` = todos los canales);
2. coordenada válida: numérica, distinta de 0 y en rango (lat ±90, lon ±180);
3. dentro del país, contra el polígono oficial y sin tolerancia. Si la base completa trae
   latitud y longitud en las columnas contrarias, se intercambian antes; si una fila suelta
   cae fuera y entra al invertir lat/lon o cambiar un signo, se corrige esa fila;
4. coordenada única: entre los que pasan 1-3, si varios comparten coordenada queda el primero;
5. no aislado: algún otro cliente (de cualquier canal, ubicado en el país) a ≤ 20 km.

Cada fila descartada cuenta una sola vez, en la primera regla que no pasa. Los valores
nunca se reescriben salvo la lat/lon corregida (el texto original se conserva negando el
signo en el propio texto, sin pasar por float, para no perder decimales).
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from sklearn.neighbors import BallTree

# (lon, lat) -> True si el punto cae dentro del polígono del país
Contains = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.bool_]]

ISOLATED_KM = 20.0  # sin otro cliente a ≤ 20 km = outlier espacial (usuario, 2026-10-30, Customer Potential)
MIN_DECIMALS = 3  # < 3 decimales ≈ más de 100 m de error: alerta, no invalida
MAX_SHARED = 5  # misma coordenada en ≥ 5 clientes: alerta (posible punto por defecto)
EARTH_KM = 6371.0088

REASON_CHANNEL = "otro canal"
REASON_COORD = "sin coordenadas o coordenadas inválidas (vacías, 0 o fuera de rango)"
REASON_OUTSIDE = "fuera del país (polígono oficial, sin tolerancia)"
REASON_DUPLICATE = "comparte coordenada con otro cliente (queda el primero)"
REASON_ISOLATED = f"punto aislado: ningún otro cliente a ≤ {ISOLATED_KM:g} km"
REASONS = (REASON_CHANNEL, REASON_COORD, REASON_OUTSIDE, REASON_DUPLICATE, REASON_ISOLATED)

# Orden en que se prueban las correcciones de una fila fuera del país (igual que dw_validar)
_CORRECTIONS: tuple[tuple[str, bool, int, int], ...] = (
    # (nombre, invertir lat/lon, signo lat, signo lon) sobre la coordenada ya orientada
    ("lat/lon invertidas", True, 1, 1),
    ("signo de la longitud", False, 1, -1),
    ("signo de la latitud", False, -1, 1),
    ("signo de lat y lon", False, -1, -1),
    ("lat/lon invertidas y signo de la longitud", True, 1, -1),
    ("lat/lon invertidas y signo de la latitud", True, -1, 1),
    ("lat/lon invertidas y signo de lat y lon", True, -1, -1),
)


def normalize_label(text: str) -> str:
    """Canal comparable: sin tildes, mayúsculas, solo letras y dígitos."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", plain.upper()).strip()


def parse_number(text: str) -> float:
    """Número de una celda de texto (coma decimal aceptada); NaN si no es numérica."""
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return float("nan")


def negate_text(text: str) -> str:
    """Cambia el signo de un número escrito, sin reformatearlo."""
    stripped = text.strip()
    return stripped[1:] if stripped.startswith("-") else "-" + stripped


def _decimals(text: str) -> int:
    parts = text.strip().split(".")
    return len(parts[1]) if len(parts) > 1 else 0


@dataclass(frozen=True)
class ClientValidation:
    """Resultado fila a fila y conteos de la validación de la base."""

    keep: list[bool]
    lat: list[str]  # texto final de la latitud (orientada y, si aplica, corregida)
    lon: list[str]
    correction: list[str]  # "" si la fila no se corrigió
    reason: list[str]  # primera regla que no pasa ("" si es válida)
    alerts: list[str]  # alertas que informan y no invalidan, separadas por " · "
    base_swapped: bool
    inside_as_is: int
    inside_swapped: int
    removed: dict[str, int] = field(default_factory=dict)

    @property
    def kept(self) -> int:
        return sum(self.keep)


def _orient(
    lat: NDArray[np.float64], lon: NDArray[np.float64], contains: Contains
) -> tuple[bool, int, int]:
    """La base viene invertida si caen más puntos dentro del país cambiando las columnas."""
    ok = np.isfinite(lat) & np.isfinite(lon)
    as_is = int(contains(lon[ok], lat[ok]).sum())
    swapped = int(contains(lat[ok], lon[ok]).sum())
    return swapped > as_is, as_is, swapped


def validate_clients(
    lat_text: Sequence[str],
    lon_text: Sequence[str],
    ids: Sequence[str],
    channels: Sequence[str],
    contains: Contains,
    allowed_channels: frozenset[str] | None = None,
) -> ClientValidation:
    """Valida la base completa; ``allowed_channels`` va normalizado (``normalize_label``)."""
    n = len(lat_text)
    if not (n == len(lon_text) == len(ids) == len(channels)):
        raise ValueError("client columns differ in length")
    if n == 0:
        raise ValueError("client base is empty")

    s_lat = np.array([t.strip() for t in lat_text], dtype=object)
    s_lon = np.array([t.strip() for t in lon_text], dtype=object)
    lat = np.array([parse_number(t) for t in s_lat], dtype=np.float64)
    lon = np.array([parse_number(t) for t in s_lon], dtype=np.float64)

    base_swapped, inside_as_is, inside_swapped = _orient(lat, lon, contains)
    if base_swapped:
        s_lat, s_lon, lat, lon = s_lon, s_lat, lon, lat

    finite = np.isfinite(lat) & np.isfinite(lon)
    # NaN se compara como False, por eso cada máscara se combina con ``finite``
    with np.errstate(invalid="ignore"):
        zero = finite & ((lat == 0) | (lon == 0))
        out_of_range = finite & ~zero & ((np.abs(lat) > 90) | (np.abs(lon) > 180))
    coord_ok = finite & ~zero & ~out_of_range

    inside = np.zeros(n, dtype=bool)
    if coord_ok.any():
        inside[coord_ok] = contains(lon[coord_ok], lat[coord_ok])

    # Fila fuera del país: se prueba invertir lat/lon y cambiar signos; la primera que
    # entra se aplica. Corregir en vez de descartar evita perder clientes reales.
    correction = np.full(n, "", dtype=object)
    pending = coord_ok & ~inside
    for name, flip, sign_lat, sign_lon in _CORRECTIONS:
        if not pending.any():
            break
        idx = np.flatnonzero(pending)
        c_lat = (lon if flip else lat)[idx] * sign_lat
        c_lon = (lat if flip else lon)[idx] * sign_lon
        hit = idx[contains(c_lon, c_lat)]
        for i in hit:
            t_lat, t_lon = (s_lon[i], s_lat[i]) if flip else (s_lat[i], s_lon[i])
            s_lat[i] = t_lat if sign_lat == 1 else negate_text(t_lat)
            s_lon[i] = t_lon if sign_lon == 1 else negate_text(t_lon)
            correction[i] = name
        pending[hit] = False
    corrected = correction != ""
    lat = np.array([parse_number(t) for t in s_lat], dtype=np.float64)
    lon = np.array([parse_number(t) for t in s_lon], dtype=np.float64)
    territory_ok = inside | corrected

    if allowed_channels is None:
        channel_ok = np.ones(n, dtype=bool)
    else:
        channel_ok = np.array(
            [normalize_label(c) in allowed_channels for c in channels], dtype=bool
        )

    # Coordenada repetida entre los que pasan 1-3: queda la primera fila del archivo
    base = channel_ok & coord_ok & territory_ok
    keys = np.array(
        [f"{a:.6f},{b:.6f}" for a, b in zip(lat, lon, strict=True)], dtype=object
    )
    seen: set[str] = set()
    repeated = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(base):
        if keys[i] in seen:
            repeated[i] = True
        seen.add(keys[i])

    # Aislado: contra todos los clientes ubicados en el país (cualquier canal), para no
    # sacar una tienda rural solo porque no tiene cerca otro cliente del canal elegido
    candidates = base & ~repeated
    reference = coord_ok & territory_ok
    near = np.ones(n, dtype=bool)
    if candidates.any() and reference.sum() > 1:
        tree = BallTree(np.radians(np.c_[lat[reference], lon[reference]]), metric="haversine")
        counts = tree.query_radius(
            np.radians(np.c_[lat[candidates], lon[candidates]]),
            ISOLATED_KM / EARTH_KM,
            count_only=True,
        )
        near[candidates] = np.asarray(counts) > 1  # el propio punto cuenta 1
    elif candidates.any():
        near[candidates] = False

    keep = base & ~repeated & near
    reason = np.full(n, "", dtype=object)
    for mask, text in (
        (~channel_ok, REASON_CHANNEL),
        (~coord_ok, REASON_COORD),
        (~territory_ok, REASON_OUTSIDE),
        (repeated, REASON_DUPLICATE),
        (~near, REASON_ISOLATED),
    ):
        reason[(reason == "") & mask] = text
    removed = {r: int((reason == r).sum()) for r in REASONS}

    shared: dict[str, int] = {}
    for k in keys[coord_ok]:
        shared[k] = shared.get(k, 0) + 1
    id_count: dict[str, int] = {}
    for x in ids:
        id_count[x] = id_count.get(x, 0) + 1
    alerts: list[str] = []
    for i in range(n):
        notes: list[str] = []
        if corrected[i]:
            notes.append(f"coordenada corregida ({correction[i]})")
        if coord_ok[i] and _decimals(s_lat[i]) < MIN_DECIMALS:
            notes.append("coordenada con pocos decimales (precisión baja)")
        if coord_ok[i] and shared.get(keys[i], 0) >= MAX_SHARED:
            notes.append(f"coordenada compartida por {shared[keys[i]]} clientes")
        if id_count[ids[i]] > 1:
            notes.append("pos_id duplicado")
        alerts.append(" · ".join(notes))

    return ClientValidation(
        keep=keep.tolist(),
        lat=[str(t) for t in s_lat],
        lon=[str(t) for t in s_lon],
        correction=[str(t) for t in correction],
        reason=[str(t) for t in reason],
        alerts=alerts,
        base_swapped=base_swapped,
        inside_as_is=inside_as_is,
        inside_swapped=inside_swapped,
        removed=removed,
    )
