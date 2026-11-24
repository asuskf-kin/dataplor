"""Datamatch steps: an iterative loop between the Front and the agent (user, 2026-11-11).

Each step the person runs Datamatch in the Front (client base vs cleaned Dataplor) with
a JSON of parameters. The clients that already found their Dataplor point
(``total_score`` above the cleanup threshold) leave the client base, and the reduced
base is uploaded so the next step only matches the clients still missing. The loop
ends when the person says so; then the run continues with the prospecting steps.

Pure functions: DataFrames in, DataFrames and plain dicts out.
"""

import re
import unicodedata
from typing import Any

import polars as pl

SAFE_FOLDER = re.compile(r"[^a-z0-9_-]+")
SCORE_BIN_WIDTH = 0.05


def step_folder(step_json: str, step_number: int) -> str:
    """Folder of one step: the JSON's file name (``paso1.json`` -> ``paso1``)."""
    stem = step_json.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleaned = SAFE_FOLDER.sub("_", stem.lower()).strip("_")
    return cleaned or f"paso{step_number}"


# Why a client counts as found, in the matches file when a distance rule is on
MATCH_RULE_COL = "match_por"
RULE_SCORE = "score"
RULE_DISTANCE = "distancia"


def matched_rows(
    datamatch: pl.DataFrame,
    score_col: str,
    threshold: float,
    distance_m: pl.Series | None = None,
    max_distance_m: float | None = None,
    option_col: str | None = None,
    score_rule: bool = True,
) -> pl.DataFrame:
    """Datamatch rows whose score is strictly above the threshold (null = no match).

    With ``max_distance_m`` a client whose Dataplor candidate is that close also counts
    as found whatever its score (user, 2026-11-23: "tomar como match a los clientes que
    están a 25 metros o menos"); ``match_por`` says which rule found each one.
    ``score_rule=False`` keeps only the distance rule (user, 2026-11-23: "solo los
    match por distancia").
    """
    score = pl.col(score_col).cast(pl.Float64, strict=False)
    by_score = score.is_not_null() & (score > threshold) & pl.lit(score_rule)
    if distance_m is None or max_distance_m is None:
        return datamatch.filter(by_score)
    near = pl.col("_distancia_m").is_not_null() & (
        pl.col("_distancia_m") <= max_distance_m
    )
    if option_col is not None and option_col in datamatch.columns:
        near &= pl.col(option_col).is_not_null()
    return (
        datamatch.with_columns(distance_m.alias("_distancia_m"))
        .filter(by_score | near)
        .with_columns(
            pl.when(by_score)
            .then(pl.lit(RULE_SCORE))
            .otherwise(pl.lit(RULE_DISTANCE))
            .alias(MATCH_RULE_COL)
        )
        .drop("_distancia_m")
    )


CAUSE_COL = "causa"


def match_causes(
    matched: pl.DataFrame,
    score_col: str,
    threshold: float,
    distance_m: pl.Series | None = None,
    max_distance_m: float | None = None,
) -> pl.DataFrame:
    """Adds ``causa``: why each client left the base, readable and without client data.

    User, 2026-11-23: "añade la causa para saber por qué se fueron". Values carry only
    the score or the distance and the rule (no comma, so the CSV needs no quotes).
    """
    score = pl.col(score_col).cast(pl.Float64, strict=False)
    by_distance = (
        pl.col(MATCH_RULE_COL) == RULE_DISTANCE
        if MATCH_RULE_COL in matched.columns
        else pl.lit(False)
    )
    frame = matched.with_columns(
        (distance_m if distance_m is not None else pl.Series([None] * matched.height))
        .cast(pl.Float64)
        .alias("_distancia_m")
    )
    by_score_text = pl.format(
        "total_score {} > {}", score.round(3).cast(pl.Utf8), pl.lit(str(threshold))
    )
    near_text = pl.format(
        "candidato a {} m (<= {} m)",
        pl.col("_distancia_m").round(0).cast(pl.Int64).cast(pl.Utf8),
        pl.lit(f"{max_distance_m:g}" if max_distance_m is not None else "?"),
    )
    return frame.with_columns(
        pl.when(by_distance).then(near_text).otherwise(by_score_text).alias(CAUSE_COL)
    ).drop("_distancia_m")


def rows_in_base(
    datamatch: pl.DataFrame,
    match_client_col: str,
    clients: pl.DataFrame,
    client_id_col: str,
) -> tuple[pl.DataFrame, int]:
    """Datamatch rows whose client is in this step's base, and how many clients were not.

    For a step the Front ran with an older (larger) base: the clients already found in
    a previous step come back in its result and would be counted twice. Dropping them
    keeps the step's counts honest without rerunning the Front (user, 2026-11-23).
    """
    base = clients.get_column(client_id_col).cast(pl.Utf8).implode()
    in_base = pl.col(match_client_col).cast(pl.Utf8).is_in(base)
    outside = (
        datamatch.filter(~in_base).get_column(match_client_col).drop_nulls().n_unique()
    )
    return datamatch.filter(in_base), int(outside)


def remaining_clients(
    clients: pl.DataFrame, client_id_col: str, matched_ids: pl.Series
) -> pl.DataFrame:
    """The client base without the clients that already have their match."""
    return clients.filter(~pl.col(client_id_col).is_in(matched_ids.implode()))


def score_bins(
    scores: pl.Series, width: float = SCORE_BIN_WIDTH
) -> list[dict[str, Any]]:
    """How many matches fall in each score band (lower bound, inclusive)."""
    values = scores.cast(pl.Float64, strict=False).drop_nulls()
    if values.is_empty():
        return []
    bands = (values / width).floor() * width
    counts = (
        pl.DataFrame({"desde": bands.round(2)}).group_by("desde").len().sort("desde")
    )
    return [
        {
            "desde": float(row["desde"]),
            "hasta": round(float(row["desde"]) + width, 2),
            "matches": int(row["len"]),
        }
        for row in counts.iter_rows(named=True)
    ]


def step_summary(
    clients_in: int,
    matched: pl.DataFrame,
    clients_out: int,
    score_col: str,
    threshold: float,
    max_distance_m: float | None = None,
    score_rule: bool = True,
) -> dict[str, Any]:
    """Counts of one step, and the check that they add up."""
    found = matched.height
    by_score = (
        matched.filter(pl.col(MATCH_RULE_COL) == RULE_SCORE)
        if MATCH_RULE_COL in matched.columns
        else matched
    )
    scores: list[float] = (
        by_score.get_column(score_col)
        .cast(pl.Float64, strict=False)
        .drop_nulls()
        .to_list()
    )
    summary: dict[str, Any] = {
        "clientes_inicio": clients_in,
        "clientes_con_match": found,
        "clientes_restantes": clients_out,
        "pct_encontrado": round(found / clients_in * 100, 2) if clients_in else 0.0,
        "umbral_limpieza": threshold,
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "cuadra": clients_in == found + clients_out,
    }
    if max_distance_m is not None:
        summary |= {
            "distancia_match_m": max_distance_m,
            "con_match_por_score": by_score.height,
            "con_match_por_distancia": found - by_score.height,
            "solo_distancia": not score_rule,
        }
    return summary


# Distance bands of a match (metres). The Front scores distance as ~1 - d/250 m, so a
# match beyond 250 m won on name, address or phonetics alone.
DISTANCE_BANDS_M = (25, 50, 100, 250)
STRONG_TEXT = 0.8
WEAK_TEXT = 0.5
# Share of proximity-only matches above which the step deserves a second look
PROXIMITY_ONLY_ALERT = 0.25
EARTH_RADIUS_M = 6_371_008.8


def match_distance_m(
    matched: pl.DataFrame, lat_c: str, lon_c: str, lat_o: str, lon_o: str
) -> pl.Series | None:
    """Haversine metres between the client and its Dataplor point (None without coords).

    Recomputed instead of reading the Front's ``distance`` column, whose unit changed
    between Front versions (metres, then km).
    """
    if not {lat_c, lon_c, lat_o, lon_o} <= set(matched.columns):
        return None
    la1, lo1, la2, lo2 = (
        pl.col(c).cast(pl.Float64, strict=False).radians()
        for c in (lat_c, lon_c, lat_o, lon_o)
    )
    a = ((la2 - la1) / 2).sin() ** 2 + la1.cos() * la2.cos() * (
        (lo2 - lo1) / 2
    ).sin() ** 2
    return matched.select(
        (2 * EARTH_RADIUS_M * a.sqrt().arcsin()).alias("distancia_m")
    ).to_series()


def _band_label(low: float | None, high: float | None) -> str:
    if low is None:
        return f"≤ {high:g} m"
    if high is None:
        return f"> {low:g} m"
    return f"{low:g}–{high:g} m"


def _distance_bands(distance_m: pl.Series) -> list[dict[str, Any]]:
    d = distance_m.cast(pl.Float64, strict=False)
    lows: list[float | None] = [None, *DISTANCE_BANDS_M]
    highs: list[float | None] = [*DISTANCE_BANDS_M, None]
    bands: list[dict[str, Any]] = []
    for low, high in zip(lows, highs, strict=True):
        mask = d.is_not_null()
        if low is not None:
            mask &= d > low
        if high is not None:
            mask &= d <= high
        bands.append({"banda": _band_label(low, high), "matches": int(mask.sum())})
    missing = int(d.is_null().sum())
    if missing:
        bands.append({"banda": "sin coordenada", "matches": missing})
    return bands


def _text_evidence(matched: pl.DataFrame) -> list[dict[str, Any]]:
    if not {"name_score", "address_score"} <= set(matched.columns):
        return []
    name, address = (
        matched.get_column(c).cast(pl.Float64, strict=False).fill_null(0.0)
        for c in ("name_score", "address_score")
    )
    return [
        {"evidencia": f"nombre ≥ {STRONG_TEXT}", "matches": int((name >= STRONG_TEXT).sum())},
        {
            "evidencia": f"dirección ≥ {STRONG_TEXT}",
            "matches": int((address >= STRONG_TEXT).sum()),
        },
        {
            "evidencia": f"nombre o dirección ≥ {STRONG_TEXT}",
            "matches": int(((name >= STRONG_TEXT) | (address >= STRONG_TEXT)).sum()),
        },
        {
            "evidencia": f"solo cercanía (nombre y dirección < {WEAK_TEXT})",
            "matches": int(((name < WEAK_TEXT) & (address < WEAK_TEXT)).sum()),
        },
    ]


def _repeated(matched: pl.DataFrame, col: str) -> int:
    if col not in matched.columns:
        return 0
    ids = matched.get_column(col).drop_nulls()
    return int(ids.len() - ids.n_unique())


def match_quality(
    matched: pl.DataFrame,
    distance_m: pl.Series | None,
    client_col: str,
    dataplor_col: str,
    score_col: str,
    threshold: float,
    max_distance_m: float | None = None,
    taken_before: pl.Series | None = None,
) -> dict[str, Any]:
    """How trustworthy the matches of one step are: distance, text evidence, duplicates.

    ``max_distance_m``: clients found by the distance rule (``match_por``) are checked
    against that distance instead of the score threshold. ``taken_before``: Dataplor
    ids matched in earlier steps of the cycle; the Front does not know them, so a later
    step could give one of those points to another client.
    Only counts leave this function: no client name, address or coordinate.
    """
    total = matched.height
    distances = _distance_bands(distance_m) if distance_m is not None else []
    median = distance_m.drop_nulls().median() if distance_m is not None else None
    evidence = _text_evidence(matched)
    repeated_dataplor = _repeated(matched, dataplor_col)
    repeated_clients = _repeated(matched, client_col)
    by_rule = (
        matched.get_column(MATCH_RULE_COL)
        if MATCH_RULE_COL in matched.columns
        else pl.Series([RULE_SCORE] * total)
    )
    is_score = (by_rule == RULE_SCORE).to_numpy()
    scores = matched.get_column(score_col).cast(pl.Float64, strict=False)
    in_range = int(((scores > threshold) & (scores <= 1.0)).to_numpy()[is_score].sum())
    n_score = int(is_score.sum())
    checks = [
        {
            "check": "Ningún cliente aparece dos veces en los matches",
            "ok": repeated_clients == 0,
            "detail": f"{repeated_clients:,} repetidos",
        },
        {
            "check": "Ningún punto Dataplor quedó asignado a más de un cliente",
            "ok": repeated_dataplor == 0,
            "detail": f"{repeated_dataplor:,} repetidos",
        },
        {
            "check": f"Los matches por score están entre el umbral ({threshold}) y 1",
            "ok": in_range == n_score,
            "detail": f"{in_range:,} de {n_score:,}",
        },
    ]
    if max_distance_m is not None and distance_m is not None:
        near = distance_m.to_numpy()[~is_score]
        within = int((near <= max_distance_m).sum())
        checks.append(
            {
                "check": f"Los matches por distancia están a {max_distance_m:g} m o menos",
                "ok": within == near.size,
                "detail": f"{within:,} de {near.size:,}",
            }
        )
    if taken_before is not None and dataplor_col in matched.columns:
        again = int(
            matched.get_column(dataplor_col)
            .drop_nulls()
            .is_in(taken_before.drop_nulls().implode())
            .sum()
        )
        checks.append(
            {
                "check": "Ningún punto Dataplor ya tomado en un paso anterior",
                "ok": again == 0,
                "detail": f"{again:,} repetidos con pasos anteriores",
            }
        )
    alerts: list[str] = []
    far = sum(b["matches"] for b in distances if b["banda"].startswith(">"))
    if far:
        alerts.append(
            f"{far:,} matches a más de {DISTANCE_BANDS_M[-1]} m: ganaron solo por "
            "texto, revísalos"
        )
    only_near = sum(e["matches"] for e in evidence if e["evidencia"].startswith("solo"))
    if total and only_near / total > PROXIMITY_ONLY_ALERT:
        alerts.append(
            f"{round(100 * only_near / total, 1)}% de los matches solo tienen cercanía "
            "como evidencia: sube el peso de nombre/dirección o el umbral del Front"
        )
    return {
        "matches": total,
        "por_regla": {
            RULE_SCORE: n_score,
            **({RULE_DISTANCE: total - n_score} if total - n_score else {}),
        },
        "distancia_mediana_m": round(float(median), 1)
        if isinstance(median, int | float)
        else None,
        "por_distancia": distances,
        "por_evidencia": evidence,
        "dataplor_repetidos": repeated_dataplor,
        "clientes_repetidos": repeated_clients,
        "alertas": alerts,
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }


KNOWN_CLIENT_REASON = "Ya es cliente del bottler (Datamatch)"
# Provinces the bottler does not serve (user, 2026-11-23: "elimina los puntos
# pertenecientes a buenos aires argentina y con ello súmalos al datamatch")
TERRITORY_REASON = "Fuera de territorio"
# Rented flats are not on-premise outlets (user, 2026-11-23: "sacamos los puntos de
# venta que tengan que ver con airbnb, apartamento, departamento y sus variantes").
# Calibrated on Andina AR: "apto" is left out ("Apto celiacos" = suitable for), and the
# match only counts inside the lodging category, so "Departamento de Geologia"
# (university) or a bar called "Departamento" stay. Hotels, cabañas and suites stay.
LODGING_RENTAL_REGEX = (
    r"(?i)\b(?:air\s*-?\s*b\s*-?\s*n\s*-?\s*b"
    r"|apart(?:a?ments?|amentos?|s)?"
    r"|apart\s*-?\s*hotel(?:es|s)?"
    r"|departamentos?|deptos?|dptos?|depas?|dtos?"
    r"|monoambientes?)\b"
)
LODGING_CATEGORY_COL = "sub_category"
LODGING_CATEGORY = "lodging"
LODGING_REASON = "Alojamiento tipo Airbnb / departamento"
# Prospects the prospection QA found to be bottler clients (removed on the person's OK)
FALSE_NEGATIVE_REASON = "Cliente del bottler según el QA de prospección (falso negativo)"
# The removed rentals are written next to the prospects with this suffix (never the
# priorización input, which is the prospects CSV itself)
LODGING_FILE_SUFFIX = "_eliminados_alojamiento_airbnb"


def lodging_rentals(frame: pl.DataFrame, name_col: str = "name") -> pl.Series:
    """True for the points whose name says Airbnb / apartment / departamento.

    Only inside the lodging category when the file has it (see LODGING_RENTAL_REGEX).
    """
    if name_col not in frame.columns:
        return pl.Series([False] * frame.height, dtype=pl.Boolean)
    mask = pl.col(name_col).fill_null("").str.contains(LODGING_RENTAL_REGEX)
    if LODGING_CATEGORY_COL in frame.columns:
        mask &= pl.col(LODGING_CATEGORY_COL).fill_null("") == LODGING_CATEGORY
    return frame.select(mask.alias("alojamiento")).to_series()


def lodging_term(name: str | None) -> str:
    """The word that made a name a rental (lowercase), for the report's detail."""
    found = re.search(LODGING_RENTAL_REGEX, name or "")
    return found.group(0).lower() if found else ""


def state_key(value: str | None) -> str:
    """Province compared without accents, case, a city prefix or 'Province' wording.

    Dataplor writes the same province several ways ("Buenos Aires Province",
    "Provincia de Córdoba", "Mendoza, Mendoza Province").
    """
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = text.lower().split(",")[-1].strip()
    text = re.sub(r"^provincia de\s+|\s+province$", "", text)
    return text.strip()


def out_of_territory(states: pl.Series, excluded: list[str]) -> pl.Series:
    """True for the points whose province is one of ``excluded``."""
    keys = {state_key(e) for e in excluded if state_key(e)}
    return states.map_elements(
        lambda v: state_key(v) in keys, return_dtype=pl.Boolean, skip_nulls=False
    )


def drop_known_points(
    dataplor: pl.DataFrame, id_col: str, known_ids: pl.Series
) -> pl.DataFrame:
    """Dataplor points not matched to any bottler client: the prospects."""
    return dataplor.filter(~pl.col(id_col).is_in(known_ids.implode()))


def prospects_qa(
    rows_in: int,
    known_ids: int,
    known_in_file: int,
    rows_out: int,
    outside: int = 0,
    territory_label: str = "",
    lodging: int = 0,
    false_negatives: int = 0,
) -> dict[str, Any]:
    """Counts of the prospects file and the checks a reviewer needs before gold.

    ``outside`` counts the points dropped for being out of territory that were not
    already clients (a point is counted once, as a client first); ``lodging`` the
    Airbnb / apartment points dropped after both; ``false_negatives`` the clients the
    prospection QA found among the prospects and the person chose to remove.
    """
    removed = rows_in - rows_out
    territory = f"{TERRITORY_REASON} ({territory_label})" if territory_label else TERRITORY_REASON
    parts = (
        f"{known_in_file:,} clientes"
        + (f" + {outside:,} fuera de territorio" if outside else "")
        + (f" + {lodging:,} alojamiento tipo Airbnb" if lodging else "")
        + (f" + {false_negatives:,} falsos negativos (QA)" if false_negatives else "")
    )
    checks = [
        {
            "check": "Los conteos cuadran (entrada = clientes conocidos + fuera de "
            "territorio + alojamiento tipo Airbnb + falsos negativos + prospectos)",
            "ok": rows_in == removed + rows_out
            and removed == known_in_file + outside + lodging + false_negatives,
            "detail": f"{rows_in:,} = {parts} + {rows_out:,}",
        },
        {
            "check": "Todos los puntos con match están en el archivo limpio",
            "ok": known_in_file == known_ids,
            "detail": f"{known_in_file:,} de {known_ids:,} ids con match",
        },
        {
            "check": "Quedó al menos un prospecto",
            "ok": rows_out > 0,
            "detail": f"{rows_out:,} prospectos",
        },
    ]
    return {
        "filas_leidas": rows_in,
        "filas_conservadas": rows_out,
        "filas_eliminadas": removed,
        "pct_eliminado": round(removed / rows_in * 100, 2) if rows_in else 0.0,
        "eliminadas_por_motivo": {
            k: v
            for k, v in (
                (KNOWN_CLIENT_REASON, known_in_file),
                (territory, outside),
                (LODGING_REASON, lodging),
                (FALSE_NEGATIVE_REASON, false_negatives),
            )
            if v
        },
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }
