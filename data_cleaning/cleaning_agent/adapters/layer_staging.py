"""LayerStagingPort adapter: the local mirror of the DWH and each file's QA sidecars.

Before anything is uploaded, the file, its ``_metadata.json`` and ``_qa.html`` are
written under ``data/<same blob path>`` so the local tree is a mirror of the blob
layout (user requirement) and the person can open the QA before approving.
"""

import html
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl


class FileLayerStaging:
    def count_rows(self, path: str) -> int:
        # Lazy scan: counts a ~1 GB CSV without loading it in memory
        return int(
            pl.scan_csv(path, infer_schema=False).select(pl.len()).collect().item()
        )

    def mirror(self, source: str, target: Path) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    def write_sidecars(
        self, metadata: dict[str, Any], json_path: Path, html_path: Path
    ) -> list[str]:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        html_path.write_text(_qa_html(metadata), encoding="utf-8")
        return [str(json_path), str(html_path)]


def _rows(pairs: list[tuple[str, Any]]) -> str:
    return "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in pairs
    )


def _qa_html(meta: dict[str, Any]) -> str:
    """Self-contained QA page (no external scripts: strict CSP friendly)."""
    qa = meta.get("qa", {})
    checks = "".join(
        f"<tr><td>{'✅' if c['ok'] else '❌'}</td><td>{html.escape(c['check'])}</td>"
        f"<td>{html.escape(str(c['detail']))}</td></tr>"
        for c in qa.get("checks", [])
    )
    removed = (
        _rows([(k, f"{v:,}") for k, v in qa.get("eliminadas_por_motivo", {}).items()])
        or "<tr><td colspan=2>Ninguno</td></tr>"
    )
    origins = "".join(
        f"<li><code>{html.escape(o)}</code></li>" for o in meta.get("origen", [])
    )
    lineage = "".join(
        f"<tr><td>{html.escape(step['etapa'])}</td><td>{html.escape(step['nombre'])}</td>"
        f"<td>{html.escape(step['inicio'])}</td><td>{html.escape(step['fin'])}</td></tr>"
        for step in meta.get("linaje", [])
    )
    status = "QA OK" if qa.get("qa_ok") else "QA CON ALERTAS"
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>QA {
        html.escape(meta.get("archivo", ""))
    }</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#1b1b1b}}
table{{border-collapse:collapse;margin:8px 0 20px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:14px}}
th{{background:#f4f4f4}} code{{font-size:13px}}
.badge{{display:inline-block;padding:4px 10px;border-radius:6px;font-weight:600;
background:{"#e5f6ea" if qa.get("qa_ok") else "#fde8e8"}}}
</style></head><body>
<h1>QA · {html.escape(meta.get("capa", ""))} · {
        html.escape(meta.get("archivo", ""))
    }</h1>
<p><span class="badge">{status}</span></p>
<h2>Resumen</h2><table>{
        _rows(
            [
                ("Corrida", meta.get("run_id")),
                ("Fecha", meta.get("fecha")),
                ("País / bottler", f"{meta.get('pais')} / {meta.get('bottler')}"),
                ("Proceso", meta.get("proceso")),
                ("Destino", meta.get("destino")),
                ("Filas leídas", f"{qa.get('filas_leidas', 0):,}"),
                (
                    "Filas eliminadas",
                    f"{qa.get('filas_eliminadas', 0):,} ({qa.get('pct_eliminado', 0)}%)",
                ),
                ("Filas conservadas", f"{qa.get('filas_conservadas', 0):,}"),
                ("Versión del código", meta.get("code_version")),
            ]
        )
    }</table>
<h2>Eliminados por motivo</h2><table>{removed}</table>
<h2>Checks</h2><table><tr><th></th><th>Check</th><th>Detalle</th></tr>{checks}</table>
<h2>Paths de origen</h2><ul>{origins}</ul>
<h2>Linaje</h2><table><tr><th>Etapa</th><th>Nombre</th><th>Inicio</th><th>Fin</th></tr>{
        lineage
    }</table>
</body></html>
"""
