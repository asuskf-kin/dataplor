"""Priorización On Premise: names, shared geo layers and the QA of its outputs.

Priorización (its own repo) scores the prospects and adds the geographic layers. Its
geo layers are per country and shared by every run of that repo, so they stay where
that repo keeps them (``bronze/providers/dataplor/<region>/<pais>/WorldPop_Overpass/``,
an existing production location this agent only reads).
"""

from typing import Any

# ISO 2 -> (region of the priorización datalake, country name used in its file names)
COUNTRIES: dict[str, tuple[str, str]] = {
    "ar": ("sl", "argentina"),
    "bo": ("sl", "bolivia"),
    "cl": ("sl", "chile"),
    "pe": ("lc", "peru"),
    "co": ("lc", "colombia"),
    "do": ("lc", "republicaDominicana"),
    "br": ("br", "brasil"),
    "mx": ("mx", "mexico"),
}
# Columns step 2 appends: the deliverable is incomplete without them
GEO_COLUMNS = (
    "hex_id",
    "pop_count",
    "pop_density",
    "dist_to_main_road",
    "car_mobility",
    "dist_to_bus_stop",
    "walk_mobility",
)


def country_name(iso2: str) -> str:
    try:
        return COUNTRIES[iso2.lower()][1]
    except KeyError as exc:
        raise ValueError(f"Priorización has no country mapping for {iso2!r}") from exc


def geodata_prefix(iso2: str) -> str:
    region, name = COUNTRIES[iso2.lower()][0], country_name(iso2)
    return f"bronze/providers/dataplor/{region}/{name}/WorldPop_Overpass/"


def output_names(bottler: str, iso2: str, period: str) -> tuple[str, str]:
    """(step 1, step 2) file names; step 2 is the deliverable (lowercase, DWH rule)."""
    name = country_name(iso2)
    return (
        f"1_priority_{bottler}_{name}_{period}",
        f"dataplor_on_premise_priority_{bottler}_{name}_{period}",
    )


def priorizacion_qa(
    input_rows: int, step1_rows: int, step2_rows: int, step2_columns: list[str]
) -> dict[str, Any]:
    """Checks of the two outputs before their metadata goes to the DWH."""
    missing_geo = [c for c in GEO_COLUMNS if c not in step2_columns]
    checks = [
        {
            "check": "El paso 1 no tiene más filas que la entrada",
            "ok": 0 < step1_rows <= input_rows,
            "detail": f"paso 1 {step1_rows:,} de {input_rows:,} prospectos",
        },
        {
            "check": "El paso 2 tiene las mismas filas que el paso 1",
            "ok": step2_rows == step1_rows,
            "detail": f"paso 2 {step2_rows:,} vs paso 1 {step1_rows:,}",
        },
        {
            "check": "El paso 2 trae las 7 columnas geográficas",
            "ok": not missing_geo,
            "detail": "faltan: " + ", ".join(missing_geo)
            if missing_geo
            else "completas",
        },
    ]
    return {
        "filas_leidas": input_rows,
        "filas_conservadas": step2_rows,
        "filas_eliminadas": input_rows - step2_rows,
        "pct_eliminado": round((input_rows - step2_rows) / input_rows * 100, 2)
        if input_rows
        else 0.0,
        "eliminadas_por_motivo": {},
        "columnas_paso2": len(step2_columns),
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }
