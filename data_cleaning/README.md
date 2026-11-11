# Dataplor Cleaning Pipeline

A configurable, country-aware pipeline for cleaning point-of-interest (POI) datasets exported from **Dataplor**. It takes a raw CSV of businesses and runs it through six sequential filters that remove commercial chains, spatial duplicates, mislabeled records, closed/night-only venues, and over-crowded properties — leaving you with a clean list of *target* retail channels (small shops, groceries, restaurants, etc.).

Every step is auditable: you can trace exactly where a given business was dropped, keep a copy of every removed record, and get an interactive HTML report of the whole run.

---

## Table of contents

- [What it does](#what-it-does)
- [Requirements — files you must provide](#requirements--files-you-must-provide)
- [Installation (uv)](#installation-uv)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Example code](#example-code)
- [Why was a record dropped?](#why-was-a-record-dropped)
- [Outputs](#outputs)
- [Example cases](#example-cases)
- [Project structure](#project-structure)

---

## What it does

The pipeline runs six modules in order. Each one receives the surviving rows from the previous step:

| # | Module | What it removes | Key parameters |
|---|--------|-----------------|----------------|
| 1 | **Normalization** | Strips accents, upper-cases and trims `name` into `name_normalized`, then drops exact duplicates by `(name, lat, lon)`. | — |
| 2 | **Chain Filter** | Known commercial chains (Walmart, OXXO, Pemex…) via country-specific regex, plus names appearing more than `max_appearances` times. | `max_appearances=4` |
| 3 | **BallTree Dedup** | Records with the *same* normalized name within `radius_meters` of each other (keeps one). | `radius_meters=50` |
| 4 | **Hours & Fuzzy** | Mislabeled names (global keyword list), venues open too few hours or night-only, and fuzzy-similar duplicates that are spatially close. | `min_hours=20`, `night_start=19`, `fuzzy_thresh=80`, `dist_m=100` |
| 5 | **Final Regex** | A final keyword blacklist (with a `KEEP_WORDS` whitelist so legit shops survive). | — |
| 6 | **Crowded Property** | Points genuinely co-located in the same `parent_location` when `threshold`+ pile up within `radius_m`. | `threshold=4`, `radius_m=100` |

You choose which modules run and in what order (see [Example code](#example-code)).

### Agentic flow (LangGraph + human-in-the-loop)

The pipeline runs as a **LangGraph agent** (`cleaning_agent/`) that stops and asks a person at every
decision and before every upload. Claude Code is the harness (`/limpiar-dataplor`); there are no LLM API
calls in the code. One cycle, for one country and bottler:

```
intake* → ¿limpiar?* → pre-filter (GeoJSON / clients) → bronze* → Front (Dataplor)* → patterns*
  → cleaning modules 1-6 → franchise review* → silver* (cleaned parquet + reports) → gold* (executive Excel)
  → Datamatch loop* (Front step → drop matched clients → silver qa_process → again?)
  → gold prospects* → priorización* (external repo) → gold delivery package* (KO / BOTTLER, Excel, maps, deck)
  → lineage                                                  * = waits for the person
```

**Start here:**

| Document | For |
|---|---|
| [docs/runbook.md](docs/runbook.md) | running a cycle: prerequisites, every question and what to answer, troubleshooting |
| [docs/spec.md](docs/spec.md) | the rules: 46 steps, thresholds, QA checks, file contracts |
| [docs/dwh-paths.md](docs/dwh-paths.md) | where every file lands in the warehouse |
| [docs/architecture.md](docs/architecture.md) | changing the code |
| [DECISIONS.md](DECISIONS.md) | why each rule exists |

**How to run it**

- In **Claude Code**: `/limpiar-dataplor`. Claude runs the CLI, asks you each question and sends your answer
  back. It never answers for you.
- In a **terminal** (JSON on stdout, logs on stderr):
  ```bash
  uv run python -m cleaning_agent start
  uv run python -m cleaning_agent resume --thread <id> --answer '<json>'
  uv run python -m cleaning_agent status --thread <id>
  uv run python -m cleaning_agent redo   --thread <id> --after <node>
  uv run python -m cleaning_agent graph   # Mermaid diagram
  ```

Every run is a thread checkpointed in `data/checkpoints.sqlite`: close the terminal between questions and
resume later. `data/runs/<thread>/PROGRESS.md` shows the status of every step. The thread id is the run's
Correlation ID on every log line. Azure credentials come only from `AZURE_STORAGE_CONNECTION_STRING` or
`AZURE_STORAGE_ACCOUNT_URL` (see `.env.example`).

Verification: `uv run pytest -q` · `uvx ruff check cleaning_agent tests` · strict mypy (command in `CLAUDE.md`).

---

## Requirements — files you must provide

> ⚠️ **The pipeline will not run without these.** It reads real files from disk at startup and raises an error if they are missing.

### 1. Input data — the raw Dataplor export

The agent asks for its path in the intake (`.parquet`, a `part-*.parquet` glob, or `.csv`). The modules use
`name`, `latitude`, `longitude`, `dataplor_id`, `parent_location`, `monday_hours` … `sunday_hours` and,
optionally, `identified_as_chain`; extra columns are carried through untouched.

### 2. Country pattern file — `cleaning_agent/domain/patterns/patterns_<iso2>.py`

The country is asked per run (ISO 2). The chain filter loads `CHAIN_REGEX` from
`cleaning_agent/domain/patterns/patterns_<iso2>.py` (`do` uses the historical `patterns_rd.py`). Countries
without a file are rejected in the intake with the list of available ones. To add a country, copy an existing
file, adapt the chains and the agent offers it automatically.

### 3. Keyword lists (already provided)

- [`global_exclude.py`](cleaning_agent/domain/patterns/global_exclude.py) — `GLOBAL_EXCLUDE_KEYWORDS` (module 4) and `FINAL_KEYWORD_EXCLUDE_KEYWORDS` (module 5).
- [`keep_words.py`](cleaning_agent/domain/patterns/keep_words.py) — `KEEP_WORDS`, the whitelist that protects legit shops from the module 5 blacklist.

---

## Installation (uv)

This project uses [**uv**](https://docs.astral.sh/uv/) for dependency and environment management. It targets **Python ≥ 3.14** (see `.python-version`).

**1. Install uv** (if you don't have it):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**2. Sync the environment** — this creates `.venv` and installs everything from `uv.lock`:

```bash
uv sync
```

That's it. `uv sync` reads `pyproject.toml` + `uv.lock` and installs pinned versions of pandas, polars, scikit-learn, rapidfuzz, unidecode, pydantic, pyyaml, and friends.

---

## Quick start

From the project root (`data_cleaning/`):

```bash
uv run python -m cleaning_agent interactive
```

The agent first asks the cleaning mode, then the files for that mode (pre-filled from `config.yaml`), shows the
plan (modules to run) for approval, runs it, and asks before publishing the cleaned CSV. In Claude Code, use
`/limpiar-dataplor` instead. See [Agentic flow](#agentic-flow-langgraph--human-in-the-loop).

---

## Configuration

### `config.yaml`

The country, bottler, channel, premise and paths are **not** in the config: the agent asks them per run.
`config.yaml` holds defaults the forms propose and service settings:

| Section | What it holds |
|---|---|
| `agent` | default modules, names to track, checkpoints file, runs folder, retry limit |
| `territory_filter` / `client_filter` | defaults for the distancia / client bottler pre-filters |
| `nightlife_filter` | module 0 parameters |
| `datamatch` | Front URL, QA_datamatch project, client base, default thresholds |
| `priorizacion` | Priorizacion_On_Premise_code project and timeout |
| `azure_storage` | container, timeouts, retries (credentials only via environment variables) |
| `reporte` | executive report folder and file-name template |
| `paths.data_dir` | local data folder |

### `reporte:` — naming the executive report

```yaml
reporte:
  # no folder of its own: files go to the DWH mirror (see below)
  nombre: "reporte_ejecutivo_{pais}_{canal}_{bottler}_{fecha}"
```

Placeholders: `{pais}` and `{bottler}` from the intake, `{canal}` from the premise (slugified,
`todos_los_canales` for *ambos*) and `{fecha}` (`YYYYMMDD_HHMMSS`). An unknown placeholder falls back to the
default name and is reported as a warning inside the report.

### Modules and parameters

Which modules run is decided in the plan approval (`confirm_plan`), defaulting to `agent.default_modules`.
Module parameters (radii, thresholds, `max_appearances`...) are fixed in
`cleaning_agent/application/cleaning_catalog.py`; module 0 (nightlife) reads `nightlife_filter` from
`config.yaml`. Each module is a pure function in `cleaning_agent/domain/cleaning/` that can be called
directly with a Polars DataFrame, e.g.:

```python
import polars as pl
from cleaning_agent.domain.cleaning.normalize import normalize_names
from cleaning_agent.domain.cleaning.geo_dedup import balltree_spatial_deduplication

df = normalize_names(pl.read_csv("dataplor.csv"))
df_clean, _, report, dropped = balltree_spatial_deduplication(df, radius_meters=50)
```

---

## Why was a record dropped?

Every module returns a 4th element (`dropped_df`): the rows it removed, annotated with the
columns below (defined in [`drop_audit.py`](cleaning_agent/domain/cleaning/drop_audit.py)). The pipeline writes
them to `data/dropped/0X_*.csv`, so no removal is a black box. Each module fills in the
columns that apply to it.

| Column | Meaning |
| --- | --- |
| `drop_reason` | The rule that removed the row. Rules are evaluated in order and the first match wins, so each row has exactly one reason. |
| `drop_match` | What it matched on: the chain substring, the excluded keyword, the shared duplicate key, the `parent_location`… |
| `drop_pattern` | The exact regex behind the match (e.g. `\boxxo\b`) |
| `drop_group_size` | How many records shared the group |
| `drop_partners` | Ids of the records it was grouped with or compared against, up to 10 |
| `drop_detail` | Extra context: which record was kept, the similarity score, the distance to the centroid, the weekly hours… |

What each step reports:

| # | Module | `drop_reason` | `drop_match` | Who it was grouped with |
| --- | --- | --- | --- | --- |
| 1 | Normalization | `1_Exact_Duplicate_(name_normalized+latitude+longitude)` | The composite key | `drop_partners` = group ids, `drop_detail` = `kept: <id>` |
| 2 | Chain Filter | `1_Regex_Chain`, `2_Too_Many_Duplicates_(>N)`, `3_Flagged_As_Chain_In_Source` | Chain substring / shared key / `chain_name` | `drop_partners` = ids sharing the name |
| 3 | BallTree Dedup | `Geo_Spatial_Duplicate_(<Nm)` | The normalized name they shared | `drop_partners` = group ids, `drop_detail` = `kept: <id>` |
| 4 | Hours & Fuzzy | `1_Global_Keywords`, `2_Hours_Filter`, `3_Fuzzy_Dedup` | Excluded keyword / which hour rule failed / the name it matched | `drop_partners` = the record kept instead, `drop_detail` = `similarity=N%` |
| 5 | Final Regex | `1_Final_Regex_Keyword` | The blacklisted keyword found in the name | — |
| 6 | Crowded Property | `1_Crowded_Property_(>=N_within_Rm)` | The shared `parent_location` | `drop_partners` = ids in the property, `drop_detail` = distance to centroid |

Real examples from a Chile run:

```
name                  drop_reason            drop_match          drop_pattern / drop_detail
Hotel Estrella        1_Regex_Chain          hotel               \bhotel\b
Facultad de Ciencias  1_Final_Regex_Keyword  Social              \bS[oó]c[ií][aá]l\w*
Terra Luna Lodge      3_Fuzzy_Dedup          terra luna          similarity=100% (kept the other one)
Bar Nocturno          2_Hours_Filter         night_only (opens at or after 19:00)
The World of Wine     1_Crowded_Property…    ce5a9acd-75f3-…     78.0m from the property centroid
```

Caveat on `drop_pattern` in module 2: it reports the pattern behind the **leftmost** match
in the name, so `farmacia guadalajara` is attributed to `\bfarmacia\b` even if a more
specific pattern also matches.

---

## Outputs

After a full run you get:

| Location | Contents |
|----------|----------|
| `data/processed/dataplor_final_pipeline_output.csv` | **The final cleaned dataset.** |
| `data/processed/0X_*.csv` | Snapshot of survivors after each step (if `save_tracking=True`). |
| `data/dropped/0X_*.csv` | The rows each step **removed** (if `save_drops=True`), with the `drop_*` columns explaining why — see [Why was a record dropped?](#why-was-a-record-dropped). |
| `data/audit/audit_report_<timestamp>.txt` | Per-name trace of where tracked items survived or were dropped (if `items_to_track` set). |
| `data/silver/ko/<pais>/<bottler>/dataplor/<yyyymmdd>/pdv_<canal>_<premise>_<pais>_<bottler>_<yyyymmdd>.parquet` | Cleaned result (franchise review applied) + `_metadata.json` + `_qa.html`, validated before the silver upload. |
| `data/silver/.../pipeline_report_<timestamp>.html` | Interactive bar chart of records removed per step + top-5 dropped names. |
| `data/silver/.../<reporte.nombre>.html` / `.pdf` / `.xlsx` + channel CSV, each with `_metadata.json` | **Executive summary** — retention headline, funnel, drop reasons, what triggered them, impact per category and region. HTML self-contained for sharing, A4 PDF for printing. The Excel + its metadata are also copied to `data/gold/.../` (gold upload). There is no `reports/` folder. |

### Executive report

Generated right after the cleaned CSV is published (`executive_report` node): HTML, PDF and Excel in the
silver mirror (the Excel is also copied to gold), named with `reporte.nombre` ({pais}, {canal}, {bottler}, {fecha}). The channel comes from
the intake's premise (on premise / off premise / ambos = all). Code:
`cleaning_agent/adapters/executive_report_builder.py` (port of the old `report.ipynb`, kept in `legacy/`).

---

## Example cases

Run the agent and answer the intake, e.g. `mx` / `Centro Pacifico` / `tradicional` / `on_premise` /
`data/raw/mx/centro_pacifico/part-*.parquet`, then "¿Va a limpiar el Dataplor?" → *sí, por distancia* with the
territory GeoJSON. For another country, answer another ISO 2 code in the intake: no code or config change.

---

## Project structure

Clean/hexagonal layers; dependencies point inwards (domain ← application ← adapters/entrypoints).

```
data_cleaning/
├── config.yaml                 # defaults for the agent's forms (no global country: it is asked per run)
├── langgraph.json              # graph for `langgraph dev` / Studio
├── cleaning_agent/
│   ├── domain/                 # pure rules, no I/O
│   │   ├── models.py           # Pydantic contracts for every human answer
│   │   ├── lineage.py          # lineage records and final document
│   │   ├── cleaning/           # modules 0-6 (normalize, chains, dedup, hours, regex, crowded...), step metrics
│   │   └── patterns/           # patterns_<iso2>.py chain regex, keyword lists
│   ├── application/
│   │   ├── ports.py            # Protocols the graph depends on
│   │   ├── cleaning_catalog.py # modules + parameters for the run's country
│   │   └── graph/              # state, nodes (intake → … → lineage), builder
│   ├── adapters/               # filesystem, streaming pre-filters, executive/drop reports, Datamatch loop,
│   │                           # priorización, gold package (CSVs, Excel, offline map, deck), Azure, lineage
│   ├── entrypoints/            # cli.py (start/resume/status/interactive/graph), studio.py
│   ├── wiring.py               # composition root
│   ├── settings.py             # reads config.yaml
│   └── observability.py        # correlation-id logger
├── docs/                       # runbook, spec, warehouse paths, architecture
├── scripts/                    # build_prospecting_deck_template.py (approved deck -> template)
├── tests/                      # pytest, in-memory fakes for every port, synthetic data only
└── legacy/                     # old main.py and report.ipynb (reference only)
```
