"""On-brand ``_qa.html`` of one Datamatch step (user, 2026-11-23: "construyelo para cada paso").

The page answers what a reviewer needs before approving the silver upload: how many
clients found their Dataplor point, how close and with what text evidence, whether a
Dataplor point went to two clients, the cycle so far and the Front parameters used.
Only counts and parameters: no client name, address, coordinate or person in charge.
Offline: fonts, tokens and logo are embedded, no script and no network.
"""

import json
from typing import Any

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand
from cleaning_agent.adapters.qa_html import QA_CSS, bars, esc, table


def _stat(label: str, value: str) -> str:
    return (
        f'<div class="stat"><div class="label">{esc(label)}</div>'
        f'<div class="value">{esc(value)}</div></div>'
    )


def _param_rows(params: dict[str, Any], private: set[str]) -> list[tuple[str, str]]:
    """Front JSON flattened to key/value rows, without the private keys."""
    rows: list[tuple[str, str]] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if not prefix and key in private:
                    continue
                walk(f"{prefix}.{key}" if prefix else str(key), item)
        elif isinstance(value, list):
            rows.append((prefix, ", ".join(map(str, value)) or "—"))
        else:
            rows.append((prefix, "—" if value in ("", None) else str(value)))

    walk("", params)
    return rows


def step_qa_html(
    brand: KinBrand,
    client: str,
    step: dict[str, Any],
    history: list[dict[str, Any]],
    quality: dict[str, Any],
    bins: list[dict[str, Any]],
    params: dict[str, Any],
    files: list[str],
    private_keys: set[str],
) -> str:
    paso, threshold = step["paso"], step["umbral_limpieza"]
    found, start = int(step["clientes_con_match"]), int(step["clientes_inicio"])
    original = int(history[0]["clientes_inicio"]) if history else start
    found_total = sum(int(h["clientes_con_match"]) for h in history)
    checks = [
        {
            "check": "Los conteos cuadran (inicio = con match + quedan)",
            "ok": bool(step["cuadra"]),
            "detail": f"{start:,} = {found:,} + {int(step['clientes_restantes']):,}",
        },
        *quality["checks"],
    ]
    ok = all(c["ok"] for c in checks)
    stats = "".join(
        _stat(k, v)
        for k, v in (
            ("Clientes del paso", f"{start:,}"),
            ("Con match", f"{found:,}"),
            ("Quedan", f"{int(step['clientes_restantes']):,}"),
            ("Acumulado", f"{round(100 * found_total / original, 1) if original else 0}%"),
        )
    )
    distances = [(b["banda"], int(b["matches"])) for b in quality["por_distancia"]]
    evidence = [(e["evidencia"], int(e["matches"])) for e in quality["por_evidencia"]]
    score_rows = [(f"{b['desde']:.2f}–{b['hasta']:.2f}", int(b["matches"])) for b in bins]
    median = quality.get("distancia_mediana_m")
    alerts = "".join(f'<p class="alert">{esc(a)}</p>' for a in quality["alertas"])
    max_distance = step.get("distancia_match_m")
    rule_text = (
        f" o si su candidato Dataplor está a {max_distance:g} m o menos (regla de distancia)"
        if max_distance is not None
        else ""
    )
    rule_sentence = (
        f"En este paso un cliente cuenta como encontrado solo si su candidato Dataplor está "
        f"a {max_distance:g} m o menos; el total_score no decide."
        if step.get("solo_distancia") and max_distance is not None
        else f"Un cliente cuenta como encontrado si su total_score del Front es mayor que "
        f"{threshold}{rule_text}."
    )
    rules = [(k, int(v)) for k, v in (quality.get("por_regla") or {}).items()]
    rule_card = (
        f'<section class="card"><h2>¿Por qué regla salió cada cliente?</h2>'
        f"<p>score: total_score &gt; {esc(threshold)} · distancia: candidato a "
        f"{max_distance:g} m o menos aunque su score no llegue.</p>{bars(rules, found)}</section>"
        if max_distance is not None
        else ""
    )
    history_rows = [
        (
            h["paso"],
            h["fecha"],
            f"{int(h['clientes_inicio']):,}",
            f"{int(h['clientes_con_match']):,}",
            f"{int(h['clientes_restantes']):,}",
            f"{h['pct_encontrado']}%",
            h.get("umbral_front") or "—",
        )
        for h in history
    ]
    meta = {k: v for k, v in step.items() if k != "calidad"}
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Datamatch {esc(paso)}</title>
<style>{brand.head_css}{PAGE_CSS}{QA_CSS}</style></head><body><div class="page">
<div class="top">{brand.logo(LOGO_FORMAL_LIGHT)}<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">Silver · Datamatch · {esc(client)} · {esc(paso)}</p>
<h1>{step['pct_encontrado']}% de los clientes del paso ya tienen su punto Dataplor</h1>
<p class="sub">{esc(rule_sentence)} Sale de la base y el siguiente paso solo busca a los
{int(step['clientes_restantes']):,} que faltan.</p>
</section>
<div class="stats">{stats}</div>
<section class="card"><h2>QA <span class="pill {'ok' if ok else 'fail'}">{'OK' if ok else 'FALLA'}</span></h2>
{table([(c['check'], c['detail'], 'OK' if c['ok'] else 'FALLA') for c in checks], ('chequeo', 'detalle', 'resultado'))}
{alerts}</section>
{rule_card}
<section class="card"><h2>¿Qué tan cerca está cada match?</h2>
<p>Distancia real entre el cliente y su punto Dataplor{f' · mediana {median:,.0f} m' if median is not None else ''}.
El Front da puntaje de distancia hasta ~250 m.</p>
{bars(distances, found) if distances else '<p>El resultado del Front no trae coordenadas.</p>'}</section>
<section class="card"><h2>¿Con qué evidencia de texto?</h2>
{bars(evidence, found) if evidence else '<p>El resultado del Front no trae name_score ni address_score.</p>'}</section>
<section class="card"><h2>Matches por banda de total_score</h2>
{bars(score_rows, found) if score_rows else '<p>Sin matches.</p>'}</section>
<section class="card"><h2>Ciclo de Datamatch</h2>
{table(history_rows, ('paso', 'fecha', 'inicio', 'con match', 'quedan', '% encontrado', 'umbral Front'))}
<p>Encontrados en todo el ciclo: {found_total:,} de {original:,}.</p></section>
<section class="card"><h2>Parámetros del Front en este paso</h2>
{table(_param_rows(params, private_keys), ('parámetro', 'valor')) if params else '<p>No se recibió el JSON del paso.</p>'}</section>
<section class="card"><h2>Archivos</h2>
{table([(f,) for f in files], ('archivo',))}
<details><summary>Resumen del paso (JSON)</summary>
<pre>{esc(json.dumps(meta, ensure_ascii=False, indent=2, default=str))}</pre></details></section>
<div class="foot">{brand.logo(LOGO_FORMAL_LIGHT)}<span>{esc(step['fecha'])}</span></div>
</div></body></html>
"""
