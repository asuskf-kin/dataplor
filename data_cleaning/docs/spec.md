# Spec — Dataplor prospecting agent

Functional specification of the cycle: what each step does, its inputs, outputs, rules and checks.
How to run it: [runbook.md](runbook.md). Paths: [dwh-paths.md](dwh-paths.md). Code layout:
[architecture.md](architecture.md). Why each rule exists: `../DECISIONS.md`.

## 1. Purpose

Turn a raw Dataplor export of one country into a prioritised list of **on-premise prospects** for one
bottler — points of sale that exist, are not already clients, ranked by how likely they exist and how
close they are to current routes — and deliver it to the warehouse and to the client (KO / bottler).

## 2. Principles

- **Human in the loop**: every decision and every upload is a question (`interrupt`); the agent never
  answers for the person, and Claude Code never answers an interrupt on the user's behalf.
- **Warehouse discipline**: mirror under `data/` first, QA gate, `_metadata.json` + `_qa.html` per file,
  ask before upload, no re-upload, size + MD5 verified (see dwh-paths.md).
- **Traceable**: the thread id is the Correlation ID on every log line; every step writes a lineage record
  (inputs, outputs, sha256, rows, code version).
- **Private data**: client bases are personal/commercial data. Only the columns a step needs are read; rows
  never reach a log, the KO files or a report. The BOTTLER version carries the nearest client's id, name,
  region and jefatura (explicit exception).
- **Brand**: every HTML/PDF/Excel/deck follows the Kin brand (fonts, tokens, logo files, never the
  "Let knowledge in" tagline). **Maps never call an API**.

## 3. Flow (46 steps)

`*` = waits for the person. Status of every step: `data/runs/<thread>/PROGRESS.md`.

| Phase | Steps |
|---|---|
| Intake | `intake*` → `choose_cleaning*` → `fetch_raw` → `collect_inputs*` → `fetch_inputs` → `confirm_plan*` |
| Bronze | `prefilter` → `stage_bronze` → `confirm_bronze*` → `upload_bronze` (skipped when "no cleaning") |
| Front (Dataplor) | `front_dataplor*` → `fetch_front` |
| Patterns | `check_patterns` → `update_patterns*` (only when missing or > 6 months) |
| Cleaning | `load_input` → `run_module` × modules 1–6 → `finalize` |
| Franchises | `prepare_franchise_review` → `franchise_review*` → `confirm_franchises*` |
| Silver | `stage_silver` → `publish` → `executive_report` → `confirm_silver*` → `upload_silver` |
| Gold (report) | `stage_gold` → `confirm_gold*` → `upload_gold` |
| Datamatch loop | `front_datamatch*` → `fetch_datamatch` → `stage_datamatch_step` → `confirm_datamatch_step*` → `upload_datamatch_step` → `next_datamatch_step*` (→ `front_datamatch` again, or on) |
| Gold prospects | `stage_prospects` → `confirm_prospects*` → `upload_prospects` |
| Priorización | `ask_priorizacion*` → `run_priorizacion` → `stage_priorizacion` → `confirm_priorizacion*` → `upload_priorizacion` |
| Gold package | `stage_gold_package` → `confirm_gold_package*` → `upload_gold_package` |
| Close | `build_lineage` |

## 4. Steps and rules

### 4.1 Intake and pre-filter
- Intake order is fixed: country ISO 2 → bottler → tradicional/moderno → on/off premise/ambos → raw path.
- Pre-filter modes: **distancia** (points inside the territory GeoJSON) or **client bottler** (points within
  `radius_m` of a client). Both keep only active + open points and stream the parquet in batches.
- Bronze QA: rows read = removed (by reason) + kept; the file has the kept rows.

### 4.2 Cleaning (modules 1–6) and franchises
| # | Module | Removes |
|---|---|---|
| 1 | Normalization | exact duplicates by name + coordinates |
| 2 | Chain filter | country chain regex (`patterns_<iso2>.py`) + names over `max_appearances` |
| 3 | BallTree dedup | same name within 50 m |
| 4 | Hours & fuzzy | mislabeled names, too few or night-only hours, fuzzy duplicates within 100 m |
| 5 | Final regex | keyword blacklist (with keep-words) |
| 6 | Crowded property | 4+ points piled in the same parent location within 100 m |
- Patterns older than 6 months (or missing) are recreated by Claude Code; the person approves the diff.
- Franchise review: Claude marks remaining franchises (OXXO, Costco, best-known brands of the country);
  the person decides whether to remove them.
- Silver QA: input = Σ removed per module + franchises + kept; the parquet has the kept rows.

### 4.3 Datamatch loop
- Each step: the Front matches the client base (`.c` columns) against the cleaned Dataplor (`.o` columns)
  with the step JSON. A client with `total_score > 0.5` (`datamatch.step_cleanup_threshold`) already has
  its Dataplor point and leaves the base.
- Step outputs: reduced base (`clients_bottler_<bottler>_pasoN.csv`), matches, the JSON, and one cycle
  Excel for all steps (history, score bands, Front parameters, matches with identifiers only).
- Check: base at start = matched + remaining. The loop ends only when the person says so.
- Optional: `{"skip": true}` at `front_datamatch` skips Datamatch. With no step done, the flow goes
  straight to priorización on the silver cleaned CSV (it still holds the bottler's known clients) and
  ends with the lineage: no gold prospects and no gold package (they need the client base). After one
  or more steps, skip works like "done".

### 4.4 Gold prospects
- Prospects = cleaned Dataplor without franchises − every `id.o` matched in any step.
- QA: input = known clients + prospects; every matched id is present in the cleaned file; ≥ 1 prospect.

### 4.5 Priorización (external repo)
- Single source: the gold prospects (the silver cleaned CSV when Datamatch was skipped). Parameters from `priorizacion.base_config` (`mexico_golfo.yaml`) when
  the country has no YAML; geo layers switched to the country's (`bronze/providers/dataplor/<region>/<pais>/WorldPop_Overpass/`).
- Step 1 = score (popularity, reviews, open confidence → `weighted_combined_score`,
  `probability_existence_cat` low < 0.40 ≤ moderate < 0.80 ≤ high). Step 2 = H3 hexagon, population,
  distances, mobility terciles (36 columns).
- QA: step 1 rows ≤ prospects; step 2 rows = step 1; the 7 geo columns present.

### 4.6 Gold delivery package (modelled on the approved Golfo package)
- **Nearest client** (haversine BallTree) for every prospect → `ref_<column>_cercano`, `dist_ref_m`.
- **Area**: `dentro` when `dist_ref_m ≤ 300`, else `fuera`.
- **Priority**: 1 Dentro·High, 2 Dentro·Moderate, 3 Dentro·Low, 4 Fuera·High, 5 Fuera·Moderate, 6 Fuera·Low.
- **Hexagons**: `hex_7`, `hex_8`, `hex_9` (H3).
- **KO CSV** (19 columns, anonymous): `dataplor_id, prioridad, prioridad_orden, area, probability_existence_cat,
  business_category, channel_cat, city, state, country, pop_density, car_mobility, walk_mobility,
  dist_to_main_road, dist_to_bus_stop, weighted_combined_score, hex_7, hex_8, hex_9`.
- **BOTTLER CSV**: id, priority, every priorización column, nearest client, area, hexagons.
- **Opportunity Excel**: Resumen_Ejecutivo (universe = prospects + current clients), Por_Ciudad,
  Por_Provincia.
- **Maps** (KO and BOTTLER): one offline HTML; canvas + Web Mercator; density dots at country zoom, H3
  hexagons closer in, points when zoomed or when the selection is small; province/city selectors (spellings
  grouped) fly to the selection; framing ignores the 2% outliers; KO shows no name of any point or client.
- **Deck** (.pptx): `cleaning_agent/adapters/assets/prospecting_deck_template.pptx` filled by shape id.
- **Client coordinates swapped** (latitude in the longitude column): detected against the prospects'
  extent, fixed for distances, flagged in every file's metadata (`alertas`, `POR VERIFICAR`).
- QA: KO rows = BOTTLER rows = priorización rows; KO has no name/coordinates/client columns; every row has
  a priority.

## 5. Metadata of every layer file (`<archivo>_metadata.json`)

Keys in this order (Lineamientos): `origen, archivo, fecha, canal, analisis, #, % datos utiles,
por que se limpiaron, alertas, POR VERIFICAR`, then `insumos, capa, destinos, espejo_local, pais, bottler,
premise, proceso, run_id, code_version, qa` and step-specific keys (franchises, modules, cycle steps…).

## 6. Presentation

The results deck for review is a **Slides Artifact** on the "Kin Design System - Kin Official":
cover, agenda, objective, project cycle, algorithm, priorización system, results (starting point, cities,
categories, detail, hexagon map, priorities, impact by stages), next steps, glossary, data preview, closing.
Tables: Kin-yellow header row, ≥ 26 px. Numbers come from `deck_figures` (domain), the same function the
.pptx uses.

## 7. Out of scope / known limits

- The Front steps are manual by design (the person operates the Front).
- `approve_output`, `qa_explore`/`qa_thresholds` and the old final `confirm_upload` exist in code but are not
  wired in the graph (replaced by silver and the Datamatch loop).
- The Kin logo in PDF/Excel needs `cairosvg`; without it the slot stays empty.
