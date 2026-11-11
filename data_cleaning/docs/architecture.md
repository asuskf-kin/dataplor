# Architecture — for whoever maintains the agent

LangGraph + Pydantic, hexagonal (clean) architecture. Claude Code is the harness: there are no LLM API
calls in the code. Dependencies point inwards.

```
cleaning_agent/
  domain/        pure rules, no I/O
    models.py            Pydantic contracts: every human answer, every port result
    cleaning/            modules 0-6, dedup, step metrics
    patterns/            country chain regex (patterns_<iso2>.py), keyword lists
    qa.py                bronze / silver QA
    warehouse.py         layer prefixes, silver PDV label
    franchises.py        franchise marks
    datamatch_steps.py   Datamatch loop: matched rows, reduced base, prospects QA
    priorizacion.py      priorización names, geo-layer prefix, QA
    gold_package.py      priority 1-6, KO/BOTTLER columns, opportunity tables, deck figures,
                         swapped-coordinates rule, canonical province names
    lineage.py           stage records
  application/
    ports.py             Protocols (one per external system)
    cleaning_catalog.py  modules per country
    graph/               state, nodes per phase, builder (edges), progress (step status)
      nodes.py           Dependencies + intake/cleaning nodes + shared helpers
      warehouse_nodes.py bronze, front, silver, gold, Datamatch loop, prospects
      franchise_nodes.py · delivery_nodes.py · priorizacion_nodes.py · gold_nodes.py
  adapters/            one per port
    azure_storage.py     upload (no re-upload, MD5), download, list (retry + circuit breaker)
    layer_staging.py     local mirror, sidecars (_metadata.json + _qa.html)
    datamatch_steps.py   loop step files + cycle Excel
    gold_package.py      KO/BOTTLER CSVs, opportunity Excel; calls the map and deck renderers
    prospection_map.py   offline canvas map (no API)
    prospecting_deck.py  .pptx renderer (template by shape id)
    priorizacion.py      priorización repo as a subprocess (own venv, own .env)
    brand.py · xlsx_brand.py   Kin brand for HTML, matplotlib and Excel
    assets/prospecting_deck_template.pptx
  entrypoints/         cli.py (start, resume, status, redo, interactive, graph), studio.py
  wiring.py            composition root: binds ports to adapters + config.yaml
  settings.py          reads config.yaml
scripts/build_prospecting_deck_template.py   one-off: approved deck -> sanitized template
```

Rules: `domain` imports nothing from `application`/`adapters`; `application` imports only `domain`.
Graph state holds JSON values only (SQLite checkpointer): store `model_dump()`, never models or DataFrames.

## How to add…

| You want | Where |
|---|---|
| a cleaning rule | pure function in `domain/cleaning/`, registered in `application/cleaning_catalog.py` |
| a human question | node in `application/graph/`, Pydantic answer in `domain/models.py`, conditional edge for the retry loop in `builder.py`, label in `progress.py`; nothing with side effects before `interrupt()` |
| a data source/sink | Protocol in `application/ports.py`, adapter in `adapters/`, wired in `wiring.py`, fake in `tests/fakes.py` |
| a warehouse path | template in `config.yaml`, field in `Dependencies`, wired in `wiring.py`; document it in `docs/dwh-paths.md` |
| an upload | a `stage_*` node that writes the mirror + sidecars and sets `pending_upload`, then `make_confirm_layer` + `make_upload_layer` (use `extra` for files in sub-folders) |

## Deck template

The .pptx template is the approved Golfo deck with the client removed. To rebuild it from a newer approved
deck (keeps shape ids, so the renderer keeps working):

```bash
uv run --with pymupdf python scripts/build_prospecting_deck_template.py "<approved deck>.pptx"
```

It replaces texts with `{{placeholders}}`, empties tables, swaps client images for placeholders, removes
alt texts, speaker notes and the forbidden tagline, renames the theme, and places the official logo files
(rasterized with PyMuPDF; the SVG class colors are inlined first). Check the result by rendering it
(`soffice --headless --convert-to pdf <deck>.pptx`) and looking at every slide.

## Tests and checks (definition of done)

```bash
uv run pytest -q
uvx ruff check cleaning_agent tests
uv run --with mypy --with pandas-stubs --with pyarrow-stubs --with types-PyYAML --with types-openpyxl mypy <modules in CLAUDE.md> --ignore-missing-imports --strict --follow-imports=silent
```

Tests use in-memory fakes for every port (`tests/fakes.py`) and synthetic data only (no production data or
client names). No `type: ignore` (org policy).

## Dependencies worth knowing

`h3` (hexagons), `python-pptx` (deck), `scikit-learn` (BallTree), `openpyxl` (Excel), `matplotlib` (charts),
`polars` (data). PyMuPDF is used only by the template script (`uv run --with`), not by the agent.
