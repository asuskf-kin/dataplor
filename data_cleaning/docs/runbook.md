# Runbook — run a Dataplor prospecting cycle end to end

This is the operator guide: what to have ready, what the agent asks at each step, what to answer and
where every file lands. The functional rules are in [spec.md](spec.md); every warehouse path is in
[dwh-paths.md](dwh-paths.md).

A full cycle (raw Dataplor → bronze → Front → cleaning → silver → Datamatch loop → gold prospects →
priorización → gold delivery package) takes about half a day of wall time, most of it waiting for the
Front and for priorización.

---

## 1. Before you start (once per machine)

| Need | How to check | Notes |
|---|---|---|
| `uv` (Python package manager) | `uv --version` | Installs the Python 3.12+ environment for you. |
| This repo, dependencies installed | `uv sync` in `data_cleaning/` | Includes `h3` and `python-pptx` (gold package). |
| `Priorizacion_On_Premise_code` next to this repo | `ls ../../Priorizacion_On_Premise_code` | Path set in `config.yaml` → `priorizacion.repo_dir`. Run `uv sync` inside it once. |
| Azure credentials for **this** repo | `.env` with `AZURE_STORAGE_CONNECTION_STRING` (or `AZURE_STORAGE_ACCOUNT_URL` + `az login`) | Template: `.env.example`. Never commit `.env`; the agent never prints it. |
| Azure credentials for **priorización** | its own `.env` (see its README) | Priorización reads and writes Azure itself. |
| Access to the Kin Front | https://kin-analytics.web.app/home | You run two Front steps by hand: Dataplor cleaning and Datamatch. |
| Claude Code | the `/limpiar-dataplor` skill in `.claude/skills/` | Recommended way to run the agent: it asks you every question. |
| LibreOffice (optional) | `soffice --version` | Only to preview the .pptx as PDF/PNG. |

Verify the repo before a real run (definition of done, also in `CLAUDE.md`):

```bash
uv run pytest -q
uvx ruff check cleaning_agent tests
```

---

## 2. Start a run

In Claude Code: type `/limpiar-dataplor`. Claude runs the CLI, shows you each question and sends your
answer back; it never answers for you.

Without Claude Code (same questions, JSON on stdout, logs on stderr):

```bash
uv run python -m cleaning_agent start
uv run python -m cleaning_agent status  --thread <thread_id>
uv run python -m cleaning_agent resume  --thread <thread_id> --answer '<json>'
uv run python -m cleaning_agent redo    --thread <thread_id> --after <node>   # rerun from a step
```

Every run is a thread saved in `data/checkpoints.sqlite`: close the terminal between questions and resume
later. `data/runs/<thread_id>/PROGRESS.md` always shows where the run stands.

---

## 3. The questions, in order

Each row is one stop of the agent (`interrupt.kind`). "You" = the operator.

| # | The agent asks | You answer | What happens next |
|---|---|---|---|
| 1 | **Intake**: country (ISO 2), bottler, tradicional/moderno, on/off premise/ambos, Dataplor raw path | e.g. `ar`, `andina`, `tradicional`, `on_premise`, `dataplor_raw_parquet/2026-10-15_ar.csv.parquet/part-0000…snappy.parquet` (container `dataplorraw` by default) | The raw starts downloading in the background. |
| 2 | **¿Va a limpiar el Dataplor?** | sí por distancia (GeoJSON) · sí por client bottler · no | Decides the pre-filter. |
| 3 | **Inputs**: GeoJSON of the territory or the client CSV | e.g. `prospection-datacleaning/global_geojson/Argentina_Andina.geojson` | Downloaded next to the raw (`data/raw/<pais>/<bottler>/insumos/`). |
| 4 | **Plan** (mode, paths, modules 1–6) | approve, or change modules | Pre-filter runs (minutes on a full country). |
| 5 | **Bronze upload** — QA page + metadata of the pre-filtered parquet | approve / keep local | Uploaded to bronze + a copy beside the raw (`…/distance/<fecha>/`). |
| 6 | **Front (Dataplor)** — the agent gives you the bronze files | Run the Dataplor step in the Front, then give the result CSV path and its `json_config.json` | Default container: `prospection-datacleaning`. |
| 7 | **Patterns** (only when the country file is missing or > 6 months old) | review Claude's diff of `patterns_<iso2>.py`, approve | Chain/franchise regex updated. |
| 8 | **Franchise review** — Claude lists remaining franchises (OXXO, Costco…) | confirm the list, then *remove* yes/no | Marked rows; `_sin_franquicias.csv` when removed. |
| 9 | **Silver upload** — cleaned parquet, drop report, executive report (HTML/PDF/Excel) | approve | `silver/ko/<pais>/<bottler>/dataplor/<fecha>/`. |
| 10 | **Gold upload** — executive Excel + metadata | approve | `gold/ko/<pais>/<bottler>/dataplor/<fecha>/`. |
| 11 | **Front (Datamatch) — step N** | Run Datamatch in the Front with the step JSON (`paso1.json`…). Give the result path (e.g. `silver/ko/ar/andina/<…>_data_match_process/<fecha>/final_output.csv`, container `prospecting-data`), the client base path and the JSON | The agent downloads both. |
| 12 | **Datamatch step upload** — reduced client base, matches, JSON, cycle Excel | approve | `silver/…/data_match_process/qa_process/<fecha>/pasoN/` + report in `<fecha>/`. |
| 13 | **¿Otro paso o seguimos?** | another step → back to 11 with the reduced client base as default · done → continue | Loop until you say done. |
| 14 | **Gold prospects** — cleaned Dataplor minus every matched point | approve | `gold/ko/<pais>/<bottler>/prospecting-data/<fecha>/prospects_*.csv`. |
| 15 | **Priorización** — config, period, input (the prospects), output dir | run (it writes to Azure itself, 15–50 min) | `bronze/ko/<pais>/<bottler>/providers/dataplor_on_premise_priority_<bottler>_<pais>/<fecha>/`. |
| 16 | **Priorización metadata** — QA of both outputs | approve | Sidecars uploaded; the CSVs are verified, not re-sent. |
| 17 | **Gold delivery package** — KO/BOTTLER CSVs and maps, opportunity Excel, deck | approve | `gold/…/prospecting-data/<fecha>/` + `results_ko/` + `results_bottler/`. |
| — | **Lineage** | — | `data/runs/<thread>/dataplor_pipeline_metadata.json`. |

Every upload shows the files, the destination and the QA before anything leaves the machine. Answer
`{"approved": false}` to keep a layer local. An existing blob is never overwritten unless you answer
`"replace": true`; after every upload the agent checks size and MD5.

### The Datamatch loop (step 11–13)

1. In the Front, run Datamatch with the client base of this step and the step JSON (`pasoN.json`).
2. Give the agent the result (`final_output.csv`), the client base and the JSON.
3. The agent removes the clients with `total_score > 0.5` from the base (they already have their Dataplor
   point), writes the reduced base and the cycle Excel, and asks before uploading.
4. Next step: upload the reduced base (`clients_bottler_<bottler>_pasoN.csv`, already in silver) to the
   Front as the client base and repeat. When no further step is needed, answer "done".

---

## 4. After the run

- **Presentation**: build/refresh the deck as a Slides Artifact on the "Kin Design System - Kin Official"
  (Claude does it from the gold figures); the .pptx in gold is the agent's own render.
- **Share**: Artifacts are private until shared from their Share menu.
- **Commit**: code changes only; `data/` and `.env` are git-ignored.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A step failed after a code fix | the thread keeps the old result | `redo --after <previous node>`; a failed status is reset automatically. |
| "ya existe con otro contenido" at an upload | the blob exists with other bytes | answer `"replace": true` only if you mean to replace it. |
| Priorización CSVs "exist with other content" | priorización uploads without Content-MD5 | handled: only sidecars are uploaded, CSVs are verified by the download. |
| Very few Datamatch matches, `distance_score` always 0 | client base with latitude/longitude swapped | the gold package detects and flags it; fix the column mapping in the Front JSON (latitude = the column that really holds latitudes) and rerun Datamatch. |
| Map shows nothing at country zoom | (old maps) H3 cells under one pixel | regenerate: maps now draw a density layer at low zoom. |
| Province appears twice in the map selector | Dataplor spellings ("Provincia de Córdoba", "Cordoba") | regenerate: the map groups spellings into one canonical name. |
| PDF/Excel without the Kin logo | `cairosvg` not installed | optional; the brand rule leaves the slot empty rather than redraw the logo. |
| A map (6–9 MB) does not open from the file explorer preview | large local file | open it in a browser, or serve `data/` locally: `python -m http.server 8765 --bind 127.0.0.1 --directory data` (also `.claude/launch.json` → `preview-data`) and browse to `http://127.0.0.1:8765/gold/…/results_ko/prospection_map_<bottler>_ko.html`. Nothing leaves the machine. |
