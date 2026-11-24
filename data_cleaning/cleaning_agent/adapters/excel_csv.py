"""CSV that opens column-aligned in Excel and LibreOffice: UTF-8 BOM, comma, CRLF.

Shared by every CSV a person opens (gold package, Datamatch steps, validated clients).
The Front's own output carries list columns printed as arrays (``res_10_neighbors``)
with line breaks inside the field: valid CSV when quoted, but Excel and naive readers
split the row there and shift the rest (user, 2026-11-23: "el csv al abrirlo se rompe").
"""

import json
import re
from pathlib import Path
from typing import Any

import polars as pl


def flat_text(value: str | None) -> str | None:
    """One CSV field that never needs quotes: no comma, double quote or line break.

    Dataplor sends JSON inside some columns (historical_*_scores, place_attributes).
    Quoted and with doubled quotes it is valid CSV, but LibreOffice and Excel with a
    Spanish locale often split it at every comma and shift the rest of the row (the
    hours ended up under other headers). JSON becomes readable flat text; free text
    keeps its words with commas turned into " - " and double quotes into '.
    """
    if value is None:
        return None
    text = value.strip()
    if text[:1] in "{[":
        try:
            parsed: Any = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            if parsed and all(v is True for v in parsed.values()):
                # Attribute flags: only their names (environment_cozy | service_takeout)
                text = " | ".join(str(k) for k in parsed)
            else:
                text = " | ".join(f"{k}: {v}" for k, v in parsed.items())
        elif isinstance(parsed, list):
            text = " | ".join(str(v) for v in parsed)
    text = re.sub(r"\s*[\r\n]+\s*", " ", text).replace('"', "'")
    text = re.sub(r"\s*[,;]\s*", " - ", text)
    # An empty text would be written as "" (quoted); an empty field reads the same
    return text or None


def write_csv(frame: pl.DataFrame, target: Path) -> None:
    """Every CSV of the agent: UTF-8 BOM, comma, decimal point, CRLF, no quoted field.

    Every text field goes through flat_text, so no field needs quotes. The files people
    open use it too (user, 2026-11-23: with ";" and decimal comma the gold CSV opened
    "todo en una columna" in Google Sheets and LibreOffice, and lat/long changed
    format); values are written as received, so coordinates keep their decimals.
    """
    _flat(frame).write_csv(
        target, include_bom=True, line_terminator="\r\n", quote_style="necessary"
    )


def _flat(frame: pl.DataFrame) -> pl.DataFrame:
    text = [c for c, t in frame.schema.items() if t == pl.Utf8]
    return frame.with_columns(
        pl.col(c).map_elements(flat_text, return_dtype=pl.Utf8, skip_nulls=True)
        for c in text
    )


def csv_separator(path: str | Path) -> str:
    """"," today; ";" for files written between 2026-11-23 and the return to comma."""
    with open(path, encoding="utf-8-sig") as f:
        header = f.readline()
    return ";" if header.count(";") > header.count(",") else ","
