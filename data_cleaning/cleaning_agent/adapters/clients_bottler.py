"""Paso 1 bottler: escribe la base de clientes validada con su metadata y su QA de marca.

Aplica ``domain.clients_bottler.validate_clients`` contra el polígono oficial del país
(archivos locales en ``data/reference/limites/{pais}``, sin red), agrega provincia y
municipio por coordenada y escribe en el espejo local: CSV, ``_metadata.json`` y
``_qa.html``. Antes de devolver, relee el CSV escrito y comprueba que cuadra con la base
original (QA); si algo no cuadra, falla y no deja metadata de un archivo malo.

Los datos de cliente nunca se imprimen ni van a logs: solo conteos y ``pos_id``.
La subida a Azure va aparte, tras aprobación.
"""

import base64
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import shapely
from numpy.typing import NDArray
from shapely.geometry import shape

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand
from cleaning_agent.adapters.clients_bottler_map import PointLayer, clients_map_png
from cleaning_agent.adapters.dwh_paths import DwhPathResolver
from cleaning_agent.adapters.excel_csv import write_csv
from cleaning_agent.adapters.prospection_map import MAP_PALETTE
from cleaning_agent.adapters.qa_html import QA_CSS as _QA_CSS
from cleaning_agent.adapters.qa_html import bars as _bars
from cleaning_agent.adapters.qa_html import esc as _e
from cleaning_agent.adapters.qa_html import table as _table
from cleaning_agent.domain.clients_bottler import (
    ISOLATED_KM,
    REASON_CHANNEL,
    REASON_COORD,
    REASON_DUPLICATE,
    REASON_ISOLATED,
    REASON_OUTSIDE,
    REASONS,
    Contains,
    normalize_label,
    parse_number,
    validate_clients,
)
from cleaning_agent.domain.models import ClientValidationResult
from cleaning_agent.observability import get_logger

ID_COL = "pos_id"
LAT_COL = "pos_latitude"
LON_COL = "pos_longitude"
NO_DIVISION = "(sin división)"


@dataclass(frozen=True)
class Territory:
    """Polígono del país y sus divisiones (archivos GeoJSON locales + su procedencia)."""

    country: Path
    divisions: dict[str, Path]  # columna nueva -> GeoJSON (p. ej. provincia, municipio)
    name_field: str = "nam"  # IGN Argentina


@dataclass(frozen=True)
class ChannelRule:
    """Columna de canal y valores aceptados (``None`` = todos los canales)."""

    column: str
    label: str
    values: tuple[str, ...] | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provenance(geojson: Path) -> dict[str, Any]:
    """La procedencia vive al lado del GeoJSON (``adm0.json`` junto a ``adm0.geojson``)."""
    meta = geojson.with_suffix(".json")
    info: dict[str, Any] = (
        json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
    )
    return {"archivo": geojson.name, **info}


TERRITORY_COL = "territorio_bottler"
OUTSIDE_TERRITORY = "Fuera del territorio"
# Properties that usually name a zone in a bottler's GeoJSON; none -> "Dentro"
_TERRITORY_NAME_KEYS = ("name", "nombre", "nam", "zona", "region", "localidad", "territorio")


def _territory_name(properties: dict[str, Any]) -> str:
    lowered = {str(k).lower(): v for k, v in properties.items()}
    for key in _TERRITORY_NAME_KEYS:
        value = lowered.get(key)
        if value not in (None, ""):
            return str(value)
    return "Dentro del territorio"


def _features(path: Path, name_field: str | None) -> tuple[list[str], list[shapely.Geometry]]:
    """Nombres y geometrías de un GeoJSON. Se lee con json y no con GDAL: el polígono
    del IGN es un solo objeto de >100 MB y GDAL rechaza objetos tan grandes."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    names = [str(f["properties"].get(name_field, "")) if name_field else "" for f in features]
    return names, [shape(f["geometry"]) for f in features]


def load_country(path: Path) -> shapely.Geometry:
    geometry = shapely.union_all(_features(path, None)[1])
    shapely.prepare(geometry)
    return geometry


def locate(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    names: list[str],
    geoms: list[shapely.Geometry],
) -> list[str]:
    """Nombre de la división donde cae cada punto; ``(sin división)`` si ninguna."""
    pairs = shapely.STRtree(geoms).query(shapely.points(lon, lat), predicate="within")
    out = np.full(len(lat), NO_DIVISION, dtype=object)
    out[pairs[0]] = np.asarray(names, dtype=object)[pairs[1]]
    return [str(x) for x in out]


def _read_text_csv(src: Path) -> pl.DataFrame:
    """Todo como texto: el dato original queda exacto (los ceros a la izquierda incluidos)."""
    try:
        return pl.read_csv(src, infer_schema_length=0, encoding="utf8")
    except pl.exceptions.ComputeError:
        return pl.read_csv(src, infer_schema_length=0, encoding="latin1")


def _counts(values: list[str], top: int | None = None) -> dict[str, int]:
    return dict(Counter(values).most_common(top))


def clean_client_file(
    src: Path,
    out_dir: Path,
    name: str,
    territory: Territory,
    channel: ChannelRule,
    run_id: str,
    brand_assets: Path,
    country: str,
    bottler: str,
    country_name: str,
    resolver: DwhPathResolver | None = None,
    bottler_territory: Path | None = None,
) -> dict[str, Any]:
    """Valida la base, escribe CSV + metadata + QA en ``out_dir`` y devuelve el resumen."""
    log = get_logger(run_id)
    started = datetime.now(UTC).isoformat()
    df = _read_text_csv(src).fill_null("")
    for col in (ID_COL, LAT_COL, LON_COL, channel.column):
        if col not in df.columns:
            raise ValueError(f"client base has no column '{col}'")
    log.info("Clients validation: %d rows read", df.height)

    geometry = load_country(territory.country)

    def contains(lon: NDArray[np.float64], lat: NDArray[np.float64]) -> NDArray[np.bool_]:
        return np.asarray(shapely.contains_xy(geometry, lon, lat), dtype=bool)

    allowed = (
        None
        if channel.values is None
        else frozenset(normalize_label(v) for v in channel.values)
    )
    raw_channel = df.get_column(channel.column).to_list()
    v = validate_clients(
        df.get_column(LAT_COL).to_list(),
        df.get_column(LON_COL).to_list(),
        df.get_column(ID_COL).to_list(),
        raw_channel,
        contains,
        allowed,
    )
    keep = pl.Series(v.keep)
    useful = v.kept
    if useful == 0:
        raise ValueError("client base has no valid rows")

    clean = df.with_columns(
        pl.Series(LAT_COL, v.lat), pl.Series(LON_COL, v.lon)
    ).filter(keep)
    lat_ok = np.array([parse_number(t) for t in clean.get_column(LAT_COL)], dtype=np.float64)
    lon_ok = np.array([parse_number(t) for t in clean.get_column(LON_COL)], dtype=np.float64)

    # Provincia y municipio por coordenada; si la base ya trae una columna con ese nombre,
    # no se toca y la calculada va en {col}_coordenada
    new_cols: dict[str, list[str]] = {}
    map_divisions: list[shapely.Geometry] = []  # la primera división (provincias) va al mapa
    for col, path in territory.divisions.items():
        target = f"{col}_coordenada" if col in df.columns else col
        names, geoms = _features(path, territory.name_field)
        new_cols[target] = locate(lat_ok, lon_ok, names, geoms)
        if not map_divisions:
            map_divisions = geoms
    # Territorio del bottler (usuario, 2026-11-23): dónde trabaja; se marca, no se quita
    # (un cliente fuera sigue siendo cliente y no debe volver como prospecto)
    territory_counts: dict[str, int] = {}
    if bottler_territory is not None:
        _, t_geoms = _features(bottler_territory, None)
        props = json.loads(bottler_territory.read_text(encoding="utf-8"))["features"]
        t_names = [_territory_name(f.get("properties") or {}) for f in props]
        inside = locate(lat_ok, lon_ok, t_names, t_geoms)
        labels = [OUTSIDE_TERRITORY if x == NO_DIVISION else x for x in inside]
        new_cols[TERRITORY_COL] = labels
        territory_counts = _counts(labels)
    clean = clean.with_columns([pl.Series(c, vals) for c, vals in new_cols.items()])

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{name}.csv"
    meta_path = out_dir / f"{name}_metadata.json"
    qa_path = out_dir / f"{name}_qa.html"
    write_csv(clean, csv_path)  # Excel-safe: BOM, CRLF, no quoted field

    corrected_ids = [
        i for i, c, k in zip(df.get_column(ID_COL), v.correction, v.keep, strict=True)
        if c and k
    ]
    corrected_types = _counts([c for c, k in zip(v.correction, v.keep, strict=True) if c and k])
    useful_alerts = _counts(
        [a for txt, k in zip(v.alerts, v.keep, strict=True) if k and txt for a in txt.split(" · ")]
    )
    removed = {
        (f"{REASON_CHANNEL} (no es {channel.label})" if r == REASON_CHANNEL else r): n
        for r, n in v.removed.items()
        # sin filtro de canal la regla no aplica: no se lista como motivo
        if not (r == REASON_CHANNEL and channel.values is None)
    }
    division_cols = list(new_cols)
    where: dict[str, Any] = {}
    if division_cols:
        first = new_cols[division_cols[0]]
        where[f"{division_cols[0]}s"] = _counts(first)
        if len(division_cols) > 1:
            second = [
                f"{m} ({p})" for m, p in zip(new_cols[division_cols[1]], first, strict=True)
            ]
            where[f"{division_cols[1]}s_con_clientes"] = len(set(second))
            where[f"{division_cols[1]}s_top_20"] = _counts(second, 20)

    qa_checks = _qa(df, clean, v.keep, v.correction, corrected_ids, new_cols, contains, raw_channel, allowed, useful, removed)
    if not all(c["ok"] for c in qa_checks):
        csv_path.unlink()
        failed = [c["chequeo"] for c in qa_checks if not c["ok"]]
        raise AssertionError(f"QA: la base validada no cuadra: {failed}")

    total = df.height
    metrics: dict[str, Any] = {
        "filas_leidas": total,
        "filas_validas": useful,
        "pct_validas": round(100 * useful / total, 2),
        **{f"quitadas: {r}": n for r, n in removed.items()},
        "lat_lon_intercambiadas_en_toda_la_base": v.base_swapped,
        "dentro_del_pais_tal_como_viene": v.inside_as_is,
        "dentro_del_pais_intercambiadas": v.inside_swapped,
        "coordenadas_corregidas_por_fila": len(corrected_ids),
        "pos_id_duplicados": total - df.get_column(ID_COL).n_unique(),
        **(
            {
                "fuera_del_territorio_bottler": territory_counts.get(OUTSIDE_TERRITORY, 0),
                "dentro_del_territorio_bottler": useful
                - territory_counts.get(OUTSIDE_TERRITORY, 0),
            }
            if territory_counts
            else {}
        ),
    }
    meta: dict[str, Any] = {
        "run_id": run_id,
        "stage": "bronze_clients_bottler_validated",
        "name": "Base de clientes bottler validada (paso 1): canal, coordenadas y dentro del país",
        "country": country,
        "bottler": bottler,
        "canal": channel.label,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "inputs": [
            {"path": str(src), "bytes": src.stat().st_size, "sha256": _sha256(src), "rows": total}
        ],
        "outputs": [
            {
                "path": str(csv_path),
                "bytes": csv_path.stat().st_size,
                "sha256": _sha256(csv_path),
                "rows": clean.height,
            }
        ],
        "reglas": {
            "canal": {"columna": channel.column, "valores": list(channel.values or ["todos"])},
            "coordenada_valida": "numérica, distinta de 0 y en rango (lat ±90, lon ±180)",
            "dentro_del_pais": "polígono oficial, sin tolerancia",
            "correccion": "base completa invertida si caen más puntos dentro cambiando columnas; "
            "por fila: lat/lon invertidas o signo cambiado si así cae dentro",
            "coordenada_unica": "6 decimales; queda la primera fila del archivo",
            "aislado_km": ISOLATED_KM,
            "orden": list(REASONS),
        },
        "territorio": {
            "pais": _provenance(territory.country),
            **{c: _provenance(p) for c, p in territory.divisions.items()},
            **(
                {"bottler": _provenance(bottler_territory)}
                if bottler_territory is not None
                else {}
            ),
        },
        "territorio_bottler": territory_counts,
        "por_que_se_quitaron": removed,
        "donde_estan": where,
        "columnas_agregadas_por_coordenada": division_cols,
        # Solo identificadores: las coordenadas corregidas ya están en el CSV
        "coordenadas_corregidas": {
            "#": len(corrected_ids),
            "por_tipo": corrected_types,
            "pos_id": corrected_ids,
        },
        "canal_de_los_validos": _counts(
            [c or "(vacío)" for c, k in zip(raw_channel, v.keep, strict=True) if k]
        ),
        "alertas_en_validos": useful_alerts,
        "metrics": metrics,
        "qa": qa_checks,
    }
    if resolver is not None:
        # La metadata viaja con el archivo: direcciones del DWH, no rutas de esta máquina
        meta = resolver.portable(meta)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    brand = KinBrand(brand_assets)
    png = _map(brand, geometry, map_divisions, v.lat, v.lon, v.reason, v.correction, v.keep,
               lat_ok, lon_ok, channel.label)
    qa_path.write_text(_qa_html(brand, name, country_name, meta, png), encoding="utf-8")
    log.info("Clients validation: %d valid of %d, QA ok", useful, total)
    return {"csv": str(csv_path), "metadata": str(meta_path), "qa": str(qa_path), **metrics}


def _map(
    brand: KinBrand,
    country: shapely.Geometry,
    divisions: list[shapely.Geometry],
    lat_text: list[str],
    lon_text: list[str],
    reason: list[str],
    correction: list[str],
    keep: list[bool],
    lat_ok: NDArray[np.float64],
    lon_ok: NDArray[np.float64],
    channel_label: str,
) -> bytes:
    """Válidos + descartados que tienen ubicación. Los de coordenada repetida caen sobre
    el cliente que se quedó y los sin coordenada no tienen dónde dibujarse."""
    lat = np.array([parse_number(t) for t in lat_text], dtype=np.float64)
    lon = np.array([parse_number(t) for t in lon_text], dtype=np.float64)
    reasons = np.asarray(reason, dtype=object)
    fixed = np.array([bool(c) and k for c, k in zip(correction, keep, strict=True)])
    hexes = MAP_PALETTE["hex"]

    def layer(mask: NDArray[np.bool_], label: str, color: str, size: float, marker: str) -> PointLayer:
        return PointLayer(label, lat[mask], lon[mask], color, size, marker)

    removed = [
        layer(reasons == REASON_CHANNEL, f"otro canal (no es {channel_label})",
              MAP_PALETTE["low"], 6, "o"),
        layer(reasons == REASON_OUTSIDE, "fuera del país", hexes[3], 40, "X"),
        layer(reasons == REASON_ISOLATED, f"aislado (> {ISOLATED_KM:g} km)", MAP_PALETTE["high"], 22, "o"),
        layer(fixed, "válido con coordenada corregida", hexes[1], 40, "D"),
    ]
    kept = PointLayer("válidos", lat_ok, lon_ok, MAP_PALETTE["density"], 1.5)
    return clients_map_png(brand, country, divisions, kept, [x for x in removed if len(x.lat)])


def _qa(
    original: pl.DataFrame,
    clean: pl.DataFrame,
    keep: list[bool],
    correction: list[str],
    corrected_ids: list[str],
    new_cols: dict[str, list[str]],
    contains: Contains,
    raw_channel: list[str],
    allowed: frozenset[str] | None,
    useful: int,
    removed: dict[str, int],
) -> list[dict[str, Any]]:
    """Chequeos sobre el CSV ya escrito, como lo leerá el siguiente paso."""
    expected = original.filter(pl.Series(keep))
    base_cols = original.columns
    fixed = pl.Series([c != "" for c, k in zip(correction, keep, strict=True) if k])
    same_other = clean.select(
        [c for c in base_cols if c not in (LAT_COL, LON_COL)]
    ).equals(expected.select([c for c in base_cols if c not in (LAT_COL, LON_COL)]))
    lat = np.array([parse_number(t) for t in clean.get_column(LAT_COL)], dtype=np.float64)
    lon = np.array([parse_number(t) for t in clean.get_column(LON_COL)], dtype=np.float64)
    inside = int(np.asarray(contains(lon, lat)).sum())
    keys = {f"{a:.6f},{b:.6f}" for a, b in zip(lat, lon, strict=True)}
    clean_channels = {normalize_label(c) for c, k in zip(raw_channel, keep, strict=True) if k}
    first_div = next(iter(new_cols.values()), [])
    checks = [
        ("filas del CSV = válidas", clean.height, useful),
        ("válidas + quitadas = leídas", useful + sum(removed.values()), original.height),
        ("mismos valores que el original (fila por fila, salvo lat/lon)", same_other, True),
        ("filas corregidas = las de la metadata", int(fixed.sum()), len(corrected_ids)),
        ("todas las válidas dentro del polígono del país", inside, useful),
        ("coordenadas únicas entre las válidas", len(keys), useful),
        ("pos_id del CSV = pos_id válidos del original",
         clean.get_column(ID_COL).to_list() == expected.get_column(ID_COL).to_list(), True),
        ("división por coordenada en cada fila", len(first_div), useful if new_cols else 0),
        ("canal de las válidas dentro del elegido",
         allowed is None or clean_channels <= allowed, True),
    ]
    return [
        {"chequeo": name, "salida": str(got), "esperado": str(want), "ok": got == want}
        for name, got, want in checks
    ]


def _qa_html(
    brand: KinBrand, name: str, country_name: str, m: dict[str, Any], map_png: bytes
) -> str:
    met = m["metrics"]
    total, useful = met["filas_leidas"], met["filas_validas"]
    ok = all(c["ok"] for c in m["qa"])
    first_div = m["columnas_agregadas_por_coordenada"][:1]
    divisions = m["donde_estan"].get(f"{first_div[0]}s", {}) if first_div else {}
    removed = [(k, n) for k, n in m["por_que_se_quitaron"].items() if n]
    corr = m["coordenadas_corregidas"]
    stats = "".join(
        f'<div class="stat"><div class="label">{_e(k)}</div><div class="value">{_e(v)}</div></div>'
        for k, v in (
            ("Clientes", f"{total:,}"),
            ("Válidos", f"{useful:,}"),
            ("% válidos", f"{met['pct_validas']}%"),
            ("Corregidos", f"{corr['#']:,}"),
        )
    )
    qa_rows = [
        (c["chequeo"], c["salida"], c["esperado"], "OK" if c["ok"] else "FALLA") for c in m["qa"]
    ]
    swap_note = (
        "<p>La base completa venía con latitud y longitud en las columnas contrarias: se corrigió.</p>"
        if met["lat_lon_intercambiadas_en_toda_la_base"]
        else ""
    )
    top = m["donde_estan"].get(f"{m['columnas_agregadas_por_coordenada'][1]}s_top_20", {}) if len(
        m["columnas_agregadas_por_coordenada"]
    ) > 1 else {}
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA clientes bottler</title>
<style>{brand.head_css}{PAGE_CSS}{_QA_CSS}</style></head><body><div class="page">
<div class="top">{brand.logo(LOGO_FORMAL_LIGHT)}<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">Bronze · paso 1 bottler · {_e(m['bottler'])} {_e(m['country'].upper())}</p>
<h1>De cada 100 clientes, {round(100 * useful / total)} sirven</h1>
<p class="sub">Un cliente sirve si {'es de cualquier canal' if m['canal'] == 'todos' else 'es del canal ' + _e(m['canal'])}, tiene una ubicación real, está dentro de
{_e(country_name)} y no repite coordenada ni queda aislado. Solo se corrigen coordenadas invertidas o con el
signo cambiado; el resto de los datos queda tal cual.</p>
</section>
<div class="stats">{stats}</div>
<section class="card"><h2>QA <span class="pill {'ok' if ok else 'fail'}">{'OK' if ok else 'FALLA'}</span></h2>
{_table(qa_rows, ("chequeo", "salida", "esperado", "resultado"))}</section>
<section class="card"><h2>¿Por qué se quitaron?</h2>{swap_note}
{_bars(removed, total) if removed else "<p>No se quitó ningún cliente.</p>"}</section>
<section class="card"><h2>Coordenadas corregidas</h2>
{_table([(k, f"{n:,}") for k, n in corr['por_tipo'].items()], ("corrección", "clientes")) if corr['por_tipo'] else "<p>Ninguna fila necesitó corrección.</p>"}
</section>
<section class="card"><h2>¿Dónde están los válidos?</h2>
<figure class="map"><img src="data:image/png;base64,{base64.b64encode(map_png).decode()}"
alt="Mapa de los clientes válidos y los descartados por motivo">
<figcaption>Cada punto es un cliente. No se dibujan los {m['por_que_se_quitaron'].get(REASON_COORD, 0):,} sin
coordenada ni los {m['por_que_se_quitaron'].get(REASON_DUPLICATE, 0):,} de coordenada repetida, que caen sobre el
cliente que se quedó. Imagen sin conexión: no usa internet ni herramientas externas.</figcaption></figure>
{_bars(list(divisions.items())[:24], useful)}
{_table([(k, f"{n:,}") for k, n in top.items()], ("municipio (provincia)", "clientes")) if top else ""}
</section>
<section class="card"><h2>Alertas en los válidos</h2>
{_table([(k, f"{n:,}") for k, n in m['alertas_en_validos'].items()], ("alerta (informa, no invalida)", "clientes")) if m['alertas_en_validos'] else "<p>Sin alertas.</p>"}
</section>
<section class="card"><h2>Metadatos</h2><details><summary>{_e(name)}_metadata.json</summary>
<pre>{_e(json.dumps({k: x for k, x in m.items() if k != 'coordenadas_corregidas'}, ensure_ascii=False, indent=2))}</pre></details></section>
<div class="foot">{brand.logo(LOGO_FORMAL_LIGHT)}<span>run_id {_e(m['run_id'])}</span></div>
</div></body></html>
"""


CHANNELS = ("todos", "tradicional", "moderno", "ambos")


def channel_rule(section: dict[str, Any], bottler: str, canal: str) -> ChannelRule:
    """Canal elegido -> columna y valores del bottler (config); ``todos`` no filtra."""
    if canal not in CHANNELS:
        raise ValueError(f"canal must be one of {CHANNELS}")
    cfg = (section.get("channels") or {}).get(bottler) or {"column": "pos_channel"}
    if canal == "todos":
        return ChannelRule(column=str(cfg["column"]), label="todos", values=None)
    if "tradicional" not in cfg or "moderno" not in cfg:
        raise ValueError(f"no channel values configured for bottler '{bottler}'")
    values = [*cfg["tradicional"], *cfg["moderno"]] if canal == "ambos" else list(cfg[canal])
    label = "tradicional y moderno" if canal == "ambos" else canal
    return ChannelRule(column=str(cfg["column"]), label=label, values=tuple(values))


def output_name(src: Path, canal: str) -> str:
    """``Listado clientes Andina.csv`` -> ``listado_clientes_andina_todos_validos`` (DWH en minúsculas)."""
    stem = re.sub(r"[^0-9a-z]+", "_", src.stem.lower()).strip("_")
    return f"{stem}_{canal}_validos"


class ClientBottlerValidator:
    """``ClientValidationPort`` sobre la sección ``clients_bottler`` de config.yaml."""

    def __init__(
        self,
        section: dict[str, Any],
        project_root: Path,
        mirror_root: Path,
        brand_assets: Path,
        resolver: DwhPathResolver | None = None,
    ) -> None:
        self.resolver = resolver
        self.section = section
        self.project_root = project_root
        self.mirror_root = mirror_root
        self.brand_assets = brand_assets

    def supports(self, country: str) -> bool:
        return country.lower() in (self.section.get("countries") or {})

    def validate(
        self,
        src: str,
        country: str,
        bottler: str,
        canal: str,
        fecha: str,
        run_id: str,
        territory: str | None = None,
    ) -> ClientValidationResult:
        country, bottler, canal = country.lower(), bottler.lower(), canal.lower()
        if not self.supports(country):
            raise ValueError(f"no boundary configured for country '{country}'")
        if len(fecha) != 8 or not fecha.isdigit():
            raise ValueError("fecha must be yyyymmdd")
        ccfg = self.section["countries"][country]
        limits = Territory(
            country=self.project_root / ccfg["boundary"],
            divisions={
                k: self.project_root / v for k, v in (ccfg.get("divisions") or {}).items()
            },
            name_field=str(ccfg.get("name_field", "nam")),
        )
        prefix = str(self.section["output_template"]).format(
            pais=country, bottler=bottler, fecha=fecha
        )
        source = Path(src)
        summary = clean_client_file(
            src=source,
            out_dir=self.mirror_root / prefix,
            name=output_name(source, canal),
            territory=limits,
            channel=channel_rule(self.section, bottler, canal),
            run_id=run_id,
            brand_assets=self.brand_assets,
            country=country,
            bottler=bottler,
            country_name=str(ccfg.get("name", country.upper())),
            resolver=self.resolver,
            bottler_territory=Path(territory) if territory else None,
        )
        return ClientValidationResult(
            csv=summary["csv"],
            metadata=summary["metadata"],
            qa=summary["qa"],
            blob_prefix=prefix,
            rows_read=int(summary["filas_leidas"]),
            rows_valid=int(summary["filas_validas"]),
            qa_ok=True,  # clean_client_file falla si un chequeo no pasa
            summary={k: v for k, v in summary.items() if k not in ("csv", "metadata", "qa")},
        )
