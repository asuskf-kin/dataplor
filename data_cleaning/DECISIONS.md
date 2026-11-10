# Decisions

## 2026-11-09: Agentic flow with LangGraph, Claude Code as the harness

- **LangGraph for the flow.** It passes the skill's 3-of-5 rule: human approval mid-run (4 interrupts), resume
  after a crash or a closed terminal (SQLite checkpointer), explicit and auditable branches (3 modes), retry loops
  on invalid answers, and long steps (the MX Parquet pre-filter takes minutes).
- **No Claude API.** The user asked to use Claude Code, not the API. The graph is deterministic; the "agent" side
  is Claude Code driving the CLI through the `/limpiar-dataplor` skill and asking the person at each interrupt.
  If an LLM step is ever needed, it enters through a new port with a stub for tests.
- **Pydantic at the boundary, TypedDict state.** Every human answer is validated by a Pydantic model
  (`extra="forbid"`). The graph state stores only `model_dump()` output so the SQLite checkpointer and the
  interrupt payloads stay JSON-serialisable.
- **Validation loops via conditional edges**, never `while` around `interrupt()`, and nothing with side effects
  before `interrupt()` (a resumed node re-runs from the top). Capped by `agent.max_input_attempts`.
- **Intermediate steps as Parquet in `data/runs/<thread>/`.** One step per module keeps types and lets a run
  resume from the last finished module.
- **Hexagonal, simple.** `src/` keeps the pure Polars cleaning functions (domain logic, unchanged). The new
  `cleaning_agent/` adds Pydantic contracts, Protocol ports, file-system adapters and the graph. `main.py` is a
  shim to the CLI so there is one flow, not two.
- **Client proximity uses scikit-learn's BallTree (haversine)** instead of the original script's scipy cKDTree:
  scikit-learn is a declared dependency, scipy is not.
- **Thread id = Correlation ID.** It prefixes every log line of the run.

## 2026-11-09: Datamatch (Front) -> QA -> Azure after publishing

- **Datamatch is a human step.** It runs in the Kin web app (Front); the graph only waits for the downloaded file.
  Claude Code gives the link but never signs in or operates the Front.
- **QA_datamatch is called as a subprocess** (`uv run --project`), not imported: it has its own environment
  (scipy, matplotlib, jinja2). Each run writes its own config and outputs under `data/runs/<thread>/datamatch_qa/`.
  `review_sample_*.csv` (labelling sample) is not a deliverable and is not uploaded.
- **Azure upload always needs explicit approval** (outward-facing). Credentials only from environment variables;
  Azure AD (`AZURE_STORAGE_ACCOUNT_URL` + DefaultAzureCredential) preferred over a connection string.
  SDK retry policy + timeouts + a circuit breaker (org policy). Blobs are overwritten, so re-running is safe.
- **Not reused:** the `azure_utils.py` helpers in `enterprise-coca-sniper-data` embed a storage account key in code
  (reported to the user as an incident to rotate).

## 2026-11-09: Clean/hexagonal layout, intake first, executive report after cleaning

- **One package, four layers** (`domain`, `application`, `adapters`, `entrypoints`). The old `src/` cleaning
  modules and `config/` patterns moved into `domain/`; `utils.py` and `report.py` were split into pure logic
  (domain) and file I/O (adapters). The old `main.py` (last committed version) and `report.ipynb` are kept in
  `legacy/` as reference, not run.
- **The country is chosen per run.** Chain patterns are loaded for the intake's ISO 2 code
  (`do` -> `patterns_rd`); `config.yaml` no longer has a global country or fixed input/output paths.
- **Intake order fixed by the user:** país, bottler, tradicional/moderno, off/on premise/ambos, Dataplor raw,
  then "¿Va a limpiar el Dataplor?" (distancia = GeoJSON, client bottler, no). "No" sends the raw Dataplor
  (CSV or Parquet) straight to the cleaning modules.
- **Executive report** (ex `report.ipynb`, ported to `adapters/executive_report_builder.py`) runs right after
  publishing the cleaned CSV. A report failure is a warning in the lineage, never a lost run.
- **Lineage**: each stage records inputs/outputs (sha256, rows, bytes), code version and timestamps; the final
  `dataplor_pipeline_metadata.json` merges only this run's records.
- **Pending (waiting for the user):** production warehouse paths for the Azure upload and the priorización step.
