# data_cleaning: Dataplor cleaning and prospecting agent

Agentic flow with human-in-the-loop: LangGraph + Pydantic, clean/hexagonal architecture. No notebooks.
Claude Code is the harness (skill `/limpiar-dataplor`); there are no Claude API calls in the code.
One cycle: intake → bronze → Front → cleaning → franchises → silver → Datamatch loop → gold prospects →
priorización → gold delivery package (KO / BOTTLER, Excel, offline maps, deck) → lineage.

Docs: `docs/runbook.md` (operator), `docs/spec.md` (rules), `docs/dwh-paths.md` (every path),
`docs/architecture.md` (code). Keep them in sync when a step, rule or path changes.

## Run

- With a human deciding: skill `/limpiar-dataplor`. First questions, in order: país ISO 2, bottler,
  tradicional/moderno, off/on premise/ambos, Dataplor raw path; then "¿Va a limpiar el Dataplor?".
- CLI: `uv run python -m cleaning_agent start|resume|status|redo|interactive|graph` (JSON on stdout, logs on stderr).

## Verify (definition of done)

```bash
uv run pytest -q
uvx ruff check cleaning_agent tests
uv run --with mypy --with pandas-stubs --with pyarrow-stubs --with types-PyYAML --with types-openpyxl mypy cleaning_agent/application cleaning_agent/adapters cleaning_agent/domain/models.py cleaning_agent/domain/lineage.py cleaning_agent/domain/qa.py cleaning_agent/domain/warehouse.py cleaning_agent/domain/patterns_policy.py cleaning_agent/domain/storage_errors.py cleaning_agent/domain/franchises.py cleaning_agent/domain/datamatch_steps.py cleaning_agent/domain/priorizacion.py cleaning_agent/domain/gold_package.py cleaning_agent/entrypoints cleaning_agent/wiring.py cleaning_agent/observability.py cleaning_agent/settings.py --ignore-missing-imports --strict --follow-imports=silent
```

## Layers (dependencies point inwards)

```
cleaning_agent/
  domain/        pure rules: models.py (Pydantic contracts), lineage.py, qa.py, warehouse.py,
                 datamatch_steps.py, priorizacion.py, gold_package.py, franchises.py,
                 cleaning/ (modules 0-6, dedup, step metrics), patterns/ (country chain regex, keyword lists)
  application/   ports.py (Protocols), cleaning_catalog.py (modules per country),
                 graph/ (state, nodes per phase, builder, progress)
  adapters/      filesystem, streaming/ (territory, client proximity), executive report, drop report/audit,
                 datamatch_steps, priorizacion, gold_package, prospection_map (offline), prospecting_deck,
                 azure_storage, layer_staging, lineage, brand / xlsx_brand, assets/ (deck template)
  entrypoints/   cli.py, studio.py (langgraph dev)
  wiring.py      composition root: binds ports to adapters + config.yaml
  settings.py    reads config.yaml   ·   observability.py  correlation-id logger
legacy/          old main.py and report.ipynb, reference only (not run)
```

- domain imports nothing from application/adapters/settings; application imports only domain.
- New cleaning rule: pure function in `domain/cleaning/`, registered in `application/cleaning_catalog.py`.
- New human question: node in `application/graph/`, Pydantic answer in `domain/models.py`, conditional edge
  for the retry loop. Nothing with side effects before `interrupt()`.
- New data source/sink: Protocol in `application/ports.py`, adapter in `adapters/`, wired in `wiring.py`.
- Decisions and their reasons: `DECISIONS.md`.

## Rules

- Never answer an agent `interrupt` on the user's behalf.
- Every node is wrapped by `application/graph/progress.py::tracked`: its status lands in `step_status`.
  Show `steps` to the user each turn; each run keeps `data/runs/<thread>/PROGRESS.md` for handoff.
- Graph state holds only JSON-friendly values (SQLite checkpointer). Store `model_dump()`, not models or DataFrames.
- Azure: respect the production data-warehouse paths; never invent new ones (all templates in `config.yaml`,
  table in `docs/dwh-paths.md`). Credentials only from env vars. Lineamientos Blob CP v1.1: lowercase,
  `{layer}/ko/{pais}/{bottler}/{entidad}/[analisis]/{yyyymmdd}`; never re-upload, verify size + MD5; every file
  ships with `_metadata.json` + `_qa.html`, is mirrored under `data/` first, and is uploaded only after asking.
  If a path the user gives does not match the DWH, say so and propose the fix before using it.
- Client CSVs are personal/commercial data: steps read only the columns they need (coordinates; id, name,
  region and jefatura of the nearest client for the BOTTLER version only); never print their rows.
- Maps never call an API (no tiles, no CDN). Review decks are Slides Artifacts on "Kin Design System - Kin
  Official". Every deliverable follows the `brand-guidelines-kin` skill; never "Let knowledge in".
- No `type: ignore` (org policy): type the code instead.
