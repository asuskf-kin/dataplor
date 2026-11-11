"""LayerStagingPort adapter: the local mirror of the DWH and each file's QA sidecars.

Before anything is uploaded, the file, its ``_metadata.json`` and ``_qa.html`` are
written under ``data/<same blob path>`` so the local tree is a mirror of the blob
layout and the person can open the QA before approving. Layer files are Parquet;
the QA page follows the Kin brand (adapters/brand.py).
"""

import html
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand


class FileLayerStaging:
    def __init__(self, brand: KinBrand) -> None:
        self.brand = brand

    def count_rows(self, path: str) -> int:
        # Lazy scans: count a ~2 GB file without loading it in memory
        frame = (
            pl.scan_parquet(path)
            if path.lower().endswith(".parquet")
            else pl.scan_csv(path, infer_schema=False)
        )
        return int(frame.select(pl.len()).collect().item())

    def columns(self, path: str) -> list[str]:
        """Column names of a CSV/Parquet (schema only: no row is read)."""
        lazy = (
            pl.scan_parquet(path)
            if path.endswith(".parquet")
            else pl.scan_csv(path, infer_schema=False)
        )
        return lazy.collect_schema().names()

    def mirror(self, source: str, target: Path) -> str:
        """Copies ``source`` to the mirror; CSV -> Parquet when the target is .parquet."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() == target.resolve():
            return str(target)
        if target.suffix == ".parquet" and Path(source).suffix.lower() == ".csv":
            # Streaming conversion; text columns stay text (as in the raw Dataplor)
            pl.scan_csv(source, infer_schema=False).sink_parquet(
                target, compression="snappy"
            )
        else:
            shutil.copy2(source, target)
        return str(target)

    def write_parquet(self, df: pl.DataFrame, target: Path) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(target, compression="snappy")
        return str(target)

    def list_files(self, directory: Path) -> list[str]:
        """Files of one mirror folder: what the person validates is what gets uploaded."""
        if not directory.is_dir():
            return []
        return sorted(str(f) for f in directory.iterdir() if f.is_file())

    def copy(self, source: str, target_dir: Path) -> str:
        """Same file in another layer folder (silver deliverable promoted to gold)."""
        target_dir.mkdir(parents=True, exist_ok=True)
        return str(shutil.copy2(source, target_dir / Path(source).name))

    def write_sidecars(
        self, metadata: dict[str, Any], json_path: Path, html_path: Path
    ) -> list[str]:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        html_path.write_text(qa_html(metadata, self.brand), encoding="utf-8")
        return [str(json_path), str(html_path)]


def _e(value: Any) -> str:
    return html.escape(str(value))


def _rows(pairs: list[tuple[str, Any]]) -> str:
    return "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in pairs)


def qa_html(meta: dict[str, Any], brand: KinBrand) -> str:
    """QA page of a layer file, on-brand (fonts, tokens and logo embedded)."""
    qa = meta.get("qa", {})
    ok = bool(qa.get("qa_ok"))
    checks = "".join(
        f"<tr><td><span class='pill {'ok' if c['ok'] else 'fail'}'>{'OK' if c['ok'] else 'FALLA'}</span></td>"
        f"<td>{_e(c['check'])}</td><td>{_e(c['detail'])}</td></tr>"
        for c in qa.get("checks", [])
    )
    removed = (
        "".join(
            f"<tr><td>{_e(k)}</td><td class='num'>{v:,}</td></tr>"
            for k, v in qa.get("eliminadas_por_motivo", {}).items()
        )
        or "<tr><td colspan='2'>Ninguno</td></tr>"
    )
    origins = "".join(
        f"<li><code>{_e(o)}</code></li>"
        for o in [meta.get("origen", ""), *meta.get("insumos", [])]
        if o
    )
    destinations = "".join(
        f"<li><code>{_e(d)}</code></li>" for d in meta.get("destinos", [])
    )
    lineage = "".join(
        f"<tr><td>{_e(s.get('etapa'))}</td><td>{_e(s.get('nombre'))}</td>"
        f"<td>{_e(s.get('inicio'))}</td><td>{_e(s.get('fin'))}</td></tr>"
        for s in meta.get("linaje", [])
    )
    total = meta.get("#", {})
    stats = [
        ("Filas leídas", f"{total.get('total', 0):,}"),
        ("Filas útiles", f"{total.get('utiles', 0):,}"),
        ("% datos útiles", f"{meta.get('% datos utiles', 0)}%"),
        ("QA", "OK" if ok else "FALLA"),
    ]
    stat_html = "".join(
        f"<div class='stat'><div class='label'>{_e(k)}</div><div class='value'>{_e(v)}</div></div>"
        for k, v in stats
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA {_e(meta.get("archivo", ""))}</title>
<style>{brand.head_css}{PAGE_CSS}</style></head><body><div class="page">
<div class="top">{
        brand.logo(LOGO_FORMAL_LIGHT)
    }<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">QA · {_e(meta.get("capa", ""))} · {_e(meta.get("analisis", ""))}</p>
<h1>{_e(meta.get("archivo", ""))}</h1>
<p class="sub">{_e(meta.get("pais", "")).upper()} · {_e(meta.get("bottler", ""))} · {
        _e(meta.get("canal", ""))
    } ·
{_e(meta.get("premise", ""))} · corrida {_e(meta.get("fecha", ""))}</p>
</section>
<div class="stats">{stat_html}</div>
<section class="card"><h2>Por qué se limpiaron</h2><table>{removed}</table></section>
<section class="card"><h2>Checks</h2><table>{checks}</table></section>
<section class="card"><h2>Paths de origen</h2><ul>{origins}</ul>
<h2>Destinos</h2><ul>{destinations}</ul></section>
<section class="card"><h2>Resumen</h2><table>{
        _rows(
            [
                ("Proceso", meta.get("proceso")),
                ("Corrida", meta.get("run_id")),
                ("Versión del código", meta.get("code_version")),
                ("Espejo local", meta.get("espejo_local")),
            ]
        )
    }</table></section>
<section class="card"><h2>Linaje</h2>
<table><tr><th>Etapa</th><th>Nombre</th><th>Inicio</th><th>Fin</th></tr>{
        lineage
    }</table></section>
<div class="foot">{
        brand.logo(LOGO_FORMAL_LIGHT)
    }<span class="ka-site">kinanalytics.com</span></div>
</div></body></html>
"""
