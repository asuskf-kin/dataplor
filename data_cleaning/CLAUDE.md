# data_cleaning: Dataplor cleaning and prospecting agent

Agentic flow with human-in-the-loop: LangGraph + Pydantic, clean/hexagonal architecture. No notebooks.
Claude Code is the harness (skill `/limpiar-dataplor`); there are no Claude API calls in the code.
One cycle: intake → bronze → Front → cleaning (modules 1-7, 7 = Airbnb, always) → franchises → silver → client
validation (mandatory, with the bottler's territory GeoJSON) → Datamatch loop → gold prospects → priorización →
gold delivery package (KO / BOTTLER, Excel, maps, deck, registro de prospección) → lineage.
State between sessions: `data/runs/<thread>/PROGRESS.md` (where a run stands), `DECISIONS.md` (why), memory not needed.

Docs: `docs/runbook.md` (operator), `docs/spec.md` (rules), `docs/dwh-paths.md` (every path),
`docs/architecture.md` (code). Keep them in sync when a step, rule or path changes.

## Run

- With a human deciding: skill `/limpiar-dataplor`. First questions, in order: país ISO 2, bottler,
  tradicional/moderno, off/on premise/ambos, Dataplor raw path; then "¿Va a limpiar el Dataplor?".
- CLI: `uv run python -m cleaning_agent start|resume|status|redo|interactive|graph|maps|sidecars|clean-clients` (JSON on stdout, logs on stderr).
  `maps --thread <id> --gold-dir <package folder>` rebuilds only the two maps of a finished run (CSV/Excel/deck untouched).
  `sidecars --thread <id> --gold-dir <package folder> [--clientes-crudos <dwh path>]` rewrites only the gold
  `_metadata.json`/`_qa.html` (QA, `vtm`, `etapa_linaje`); for packages built before 2026-11-23, whose sidecars
  were overwritten with lineage only. Data files keep their bytes; replacing sidecars in Azure needs the user's OK.
  `clean-clients --src <csv> --country ar --bottler andina [--canal todos]` validates the client base (step 1 bottler, docs/spec.md §4.3).

## Verify (definition of done)

```bash
uv run pytest -q
uvx ruff check cleaning_agent tests
uv run --with mypy --with pandas-stubs --with pyarrow-stubs --with types-PyYAML --with types-openpyxl mypy cleaning_agent/application cleaning_agent/adapters cleaning_agent/domain/models.py cleaning_agent/domain/lineage.py cleaning_agent/domain/qa.py cleaning_agent/domain/warehouse.py cleaning_agent/domain/patterns_policy.py cleaning_agent/domain/storage_errors.py cleaning_agent/domain/franchises.py cleaning_agent/domain/datamatch_steps.py cleaning_agent/domain/datamatch_thresholds.py cleaning_agent/domain/priorizacion.py cleaning_agent/domain/gold_package.py cleaning_agent/domain/clients_bottler.py cleaning_agent/domain/dwh_paths.py cleaning_agent/domain/prospection_qa.py cleaning_agent/domain/upstream.py cleaning_agent/domain/registry.py cleaning_agent/domain/cleaning/lodging_filter.py cleaning_agent/entrypoints cleaning_agent/wiring.py cleaning_agent/observability.py cleaning_agent/settings.py --ignore-missing-imports --strict --follow-imports=silent
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
                 datamatch_steps, priorizacion, gold_package, prospection_map (Esri tiles), prospecting_deck,
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
  Metadata and lineage name DWH addresses only, never a local path (`adapters/dwh_paths.py`).
  If a path the user gives does not match the DWH, say so and propose the fix before using it.
- Client CSVs are personal/commercial data: steps read only the columns they need (coordinates; id, name,
  region and jefatura of the nearest client for the BOTTLER version only); never print their rows.
- Maps: the only network use is the free Esri World Light Gray basemap tiles (no key, no library, no CDN);
  the map canvas uses the kin-hexmap palette in `prospection_map.MAP_PALETTE`, not brand colours (user
  decision 2026-11-17). Review decks are Slides Artifacts on "Kin Design System - Kin Official". Every other
  deliverable (and the map sidebar) follows the `brand-guidelines-kin` skill; never "Let knowledge in".
- Every CSV (gold KO/BOTTLER, Datamatch matches, Front client bases, prospects): UTF-8 BOM, comma, decimal
  point, CRLF and no field that needs quotes (JSON flattened, see spec); the user opens them in Google Sheets
  and LibreOffice (2026-11-23: with `;` they opened in one column and lat/long changed format). With
  `poi_ref` as the KO/BOTTLER key; KO never carries `dataplor_id`, names, coordinates or client data (spec).
- No `type: ignore` (org policy): type the code instead.
- Metadata, QA pages and lineage name DWH addresses only (`DwhPathResolver.portable`); a new metadata writer must
  go through it. Never write a local path or `espejo_local` into anything that is uploaded.
- Airbnb / rented flats leave in cleaning module 7 (sheet "Airbnb" in the executive Excel), not in the Datamatch.
- The per-stage lineage never replaces a layer sidecar: it goes inside it as `etapa_linaje` (`adapters/lineage.py`).
- The gold metadata has a section `vtm` with the 16 fields of `domain/registry.py::REGISTRY_FIELDS`, names and order fixed by the
  user; unknown values are `POR COMPLETAR`, never invented.

## Compact Instructions

Keep: the thread id, the pending `interrupt.kind`, what the user approved or refused (uploads, replace), and the
user's literal words for any new rule. Drop: file dumps and test output once green.
