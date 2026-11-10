"""Production data-warehouse layout (user-defined; never invent other paths).

Layers: drop_zone -> bronze -> silver -> gold, in container ``prospecting-data`` by
default, with the run date (yyyymmdd) in every path, e.g.
``bronze/ko/ar/andina/20261109/``. The local mirror uses the same relative path.
"""

import re
from enum import StrEnum

DEFAULT_PATH_TEMPLATE = "{layer}/ko/{pais}/{bottler}/{fecha}"


class Layer(StrEnum):
    DROP_ZONE = "drop_zone"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


def folder(value: str) -> str:
    """Lowercase, spaces to underscores: blob paths are case-sensitive."""
    cleaned = "_".join(value.strip().lower().split())
    if not re.fullmatch(r"[a-z0-9_-]+", cleaned):
        raise ValueError(f"Cannot use {value!r} in a warehouse path")
    return cleaned


def layer_prefix(
    layer: Layer,
    country: str,
    bottler: str,
    run_date: str,
    template: str = DEFAULT_PATH_TEMPLATE,
) -> str:
    """``bronze/ko/ar/andina/20261109`` for the run's country, bottler and date."""
    if not re.fullmatch(r"\d{8}", run_date):
        raise ValueError("run_date must be yyyymmdd")
    return template.format(
        layer=layer.value, pais=folder(country), bottler=folder(bottler), fecha=run_date
    ).strip("/")
