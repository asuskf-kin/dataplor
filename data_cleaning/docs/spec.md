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
  (inputs, outputs, sha256, rows, code version). The final lineage also carries `decisiones`: what the
  person decided at each point and why, from `data/runs/<thread>/decisiones.json` (a JSON list of
  `{fecha, etapa, decision, por_que}` kept by Claude Code during the run).
- **Private data**: client bases are personal/commercial data. Only the columns a step needs are read; rows
  never reach a log, the KO files or a report. The BOTTLER version carries the nearest client's id, name,
  region and jefatura (explicit exception).
- **Brand**: every HTML/PDF/Excel/deck follows the Kin brand (fonts, tokens, logo files, never the
  "Let knowledge in" tagline). **Maps never call an API**.

## 3. Flow (54 steps)

`*` = waits for the person. Status of every step: `data/runs/<thread>/PROGRESS.md`.

| Phase | Steps |
|---|---|
| Intake | `intake*` → `choose_cleaning*` → `fetch_raw` → `collect_inputs*` → `fetch_inputs` → `confirm_plan*` |
| Bronze | `prefilter` → `stage_bronze` → `confirm_bronze*` → `upload_bronze` (skipped when "no cleaning") |
| Front (Dataplor) | `front_dataplor*` → `fetch_front` |
| Patterns | `check_patterns` → `update_patterns*` (only when missing or > 6 months) |
| Cleaning | `load_input` → `run_module` × modules 1–7 (7 = Airbnb, always) → `finalize` |
| Franchises | `prepare_franchise_review` → `franchise_review*` → `confirm_franchises*` |
| Silver | `stage_silver` → `publish` → `executive_report` → `confirm_silver*` → `upload_silver` |
| Gold (report) | `stage_gold` → `confirm_gold*` → `upload_gold` |
| Client base (step 1 bottler) | `ask_validate_clients*` → `validate_clients` → `confirm_clients*` → `upload_clients` (once, mandatory; skipped only when the country has no boundary configured) |
| Datamatch loop | `front_datamatch*` → `fetch_datamatch` → `stage_datamatch_step` → `confirm_datamatch_step*` → `upload_datamatch_step` → `next_datamatch_step*` (→ `front_datamatch` again, or on) |
| Prospection QA | `prepare_prospection_qa` → `prospection_qa_review*` (Claude Code) → `build_prospection_qa` → `confirm_false_negatives*` (only when there are false negatives) |
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

### 4.2 Cleaning (modules 1–7) and franchises
| # | Module | Removes |
|---|---|---|
| 1 | Normalization | exact duplicates by name + coordinates |
| 2 | Chain filter | country chain regex (`patterns_<iso2>.py`) + names over `max_appearances` |
| 3 | BallTree dedup | same name within 50 m |
| 4 | Hours & fuzzy | mislabeled names, too few or night-only hours, fuzzy duplicates within 100 m |
| 5 | Final regex | keyword blacklist (with keep-words) |
| 6 | Crowded property | 4+ points piled in the same parent location within 100 m |
| 7 | Airbnb / departamento | rented flats inside `sub_category = lodging` (always runs; §7) |
- Patterns older than 6 months (or missing) are recreated by Claude Code; the person approves the diff.
- Franchise review: Claude marks remaining franchises (OXXO, Costco, best-known brands of the country);
  the person decides whether to remove them.
- Silver QA: input = Σ removed per module + franchises + kept; the parquet has the kept rows.

### 4.3 Datamatch loop
- Before step 1, the flow validates the client base — mandatory since 2026-11-23, with the bottler's
  territory GeoJSON (§7) — (`ask_validate_clients`; also
  available outside the graph as `clean-clients`), with the same rules as the Customer Potential
  `dw_validar`, so "valid client" means the same in both workflows), in this order, each dropped row
  counted once in the first rule it fails: channel (optional, `todos` = no filter) · valid coordinate
  (numeric, ≠ 0, lat ±90 / lon ±180) · inside the country (official IGN polygon, no tolerance; the whole
  base is swapped when more points fall inside with lat/lon exchanged, and one row outside is fixed when
  swapping or flipping a sign puts it inside) · unique coordinate (6 decimals, the first row stays) · not
  isolated (another client of any channel within 20 km). Province and municipality by coordinate are
  added. Alerts (low precision, coordinate shared by ≥ 5, duplicated `pos_id`) inform and never drop.
  QA re-reads the written CSV: rows = valid, valid + dropped = read, same values except lat/lon, all
  inside the polygon, unique coordinates; any failure stops and leaves no metadata.
  The `_qa.html` carries a static map (matplotlib PNG embedded, no API, tiles, CDN or JS): country and
  province outlines from the same local IGN files, valid clients, and the dropped ones that have a location
  (outside, isolated, other channel) plus the corrected rows, in the `MAP_PALETTE` colours.
- Each step: the Front matches the client base (`.c` columns) against the cleaned Dataplor (`.o` columns)
  with the step JSON. A client with `total_score > 0.5` (`datamatch.step_cleanup_threshold`) already has
  its Dataplor point and leaves the base.
- Step outputs: reduced base (`clients_bottler_<bottler>_pasoN.csv`), matches, the JSON, the step QA
  page `datamatch_<bottler>_pasoN_qa.html`, and one cycle Excel for all steps (history, score bands, Front
  parameters, matches with identifiers only).
- Step QA page (counts only, offline, Kin brand): real client→Dataplor distance (haversine, bands
  ≤25/50/100/250 m and median; the Front's `distance` unit changed between versions), text evidence
  (name or address ≥ 0.8, proximity only = both < 0.5), score bands, cycle history and Front parameters
  without `slack`. Checks: counts add up, no client twice, no Dataplor point given to two clients, scores in
  (threshold, 1]. Alerts: matches beyond 250 m, more than 25% proximity-only.
- Step CSVs and the validated client base are written Excel-safe like gold (`adapters/excel_csv.py`:
  UTF-8 BOM, CRLF, no field that needs quotes): the Front's list columns (`res_10_neighbors`) carry line
  breaks that split the row in Excel.
- Threshold page `datamatch_<bottler>_pasoN_umbral.html` (Kin port of QA_datamatch's threshold report,
  `domain/datamatch_thresholds.py`): scenarios (current cleanup threshold, Front threshold, elbow of the
  sensitivity curve, KDE valleys) with matches, Δ vs current, median distance and proximity-only share;
  distribution, sensitivity and component charts (embedded PNG); the 10 most marginal pairs above each
  threshold from 0.95 down to the Front threshold. It shows Dataplor and client names side by side, so it
  stays in the local mirror and is never in the upload list. Another threshold for a step:
  `redo --after fetch_datamatch --umbral <0-1>` (or `umbral` in the `front_datamatch` answer); it stays
  for later steps until changed.
- Check: base at start = matched + remaining. The loop ends only when the person says so.
- Front run with an older base (e.g. step 4 run with the step 2 base): the counts do not add up and the
  step fails. With `filtrar_a_base: true` (answer field, or `redo --after fetch_datamatch --datamatch
  '{"filtrar_a_base": true}'`) the result rows whose client is not in `clients_file` are dropped before
  matching; the count is kept as `clientes_fuera_de_base` and shown as an alert on the step QA page.
- Optional: `{"skip": true}` at `front_datamatch` skips Datamatch. With no step done, the flow goes
  straight to priorización on the silver cleaned CSV (it still holds the bottler's known clients) and
  ends with the lineage: no gold prospects and no gold package (they need the client base). After one
  or more steps, skip works like "done".

### 4.3b Prospection QA (after the last Datamatch step)
User, 2026-11-23 ("agrega este qa después de pasar los pasos"), adapted from the `prospection-qa` skill.
- **Populations.** `match` = Dataplor points matched in any step; `no_match` = the would-be prospects
  (cleaned Dataplor − matched − out of territory − rented flats); client base = the one given to the
  **first** step (full base). Columns come from the first step's Front JSON (`client.columns`,
  `options.columns`); category columns are picked from `DATAPLOR_CATEGORY_COLUMNS` /
  `CLIENT_CATEGORY_COLUMNS` (`domain/prospection_qa.py`).
- **False negative** = a `no_match` whose best client has `combined = 0.4·geo + 0.6·name ≥ 0.65`, with
  `geo = max(0, 1 − d/300 m)` (haversine) and `name = 0.5·token_sort_ratio + 0.5·TF-IDF cosine` (IDF over
  every name of both bases; accents dropped). Only clients within 300 m are compared (exact: beyond it
  `combined ≤ 0.6`). Reason: `both_strong` (both ≥ 0.6), else `proximity_dominant` / `name_dominant`.
- **`prospection_qa_review*` is Claude Code's**: reads `categories_for_review.json` (category names and
  counts only) and answers `category_mapping` (High/Medium/Low), `non_beverage` and `benchmark`
  (Coca-Cola penetration found on the web, searching with the country name only; `penetration_pct` null
  when there is no reliable figure). Verdict: `under_matched` if penetration > 60 % and match rate
  < 20 %, `insufficient` without a figure, else `consistent`.
- **Outputs** in `silver/…/qa_process/<fecha>/prospection_qa/` of the mirror. **Local only** (client
  names / coordinates): `mistakes_report.csv`, `category_mapping.xlsx`, `category_issues.xlsx`,
  `no_match_enriched.xlsx` (no_match with `excluding_suggestion`, `mapped_category`,
  `mapped_category_confidence`; priority both_strong > proximity > name > category > no_beverage),
  `prospection_qa_map_overview_<cliente>.html` and `prospection_qa_map_mistakes_<cliente>.html` (Esri
  tiles, no library or CDN). **Uploaded** with the prospects, to `qa_process/<fecha>/`:
  `prospection_qa_report_<cliente>.html` + sidecars (counts, rates, categories, ids; no names or coordinates).
- **`confirm_false_negatives*` is the person's**: `{"remove": true}` drops those Dataplor ids from the
  prospects (counted with the Datamatch clients in the executive report's step 10, and in the prospects QA
  as "falsos negativos"); `{"remove": false}` keeps them. No false negatives → no question.
- The QA never blocks the prospects: an error is a warning and the flow goes on to `stage_prospects`.

### 4.4 Gold prospects
- Prospects = cleaned Dataplor without franchises − every `id.o` matched in any step − provinces out of
  territory (if any) − rented flats − the prospection-QA false negatives the person chose to remove.
- Rented flats (extra step after the Datamatch, `LODGING_RENTAL_REGEX` in `domain/datamatch_steps.py`):
  name matches, case-insensitive,
  `\b(?:air\s*-?\s*b\s*-?\s*n\s*-?\s*b|apart(?:a?ments?|amentos?|s)?|apart\s*-?\s*hotel(?:es|s)?|departamentos?|deptos?|dptos?|depas?|dtos?|monoambientes?)\b`
  and only inside `sub_category = lodging` when the file has it (so universities' "Departamento de …" and
  bars named "Departamento" stay). `apto` is left out ("apto celíacos"); hotels, cabañas and suites stay.
  A point is counted once, by its first reason (client, then territory, then rental). The regex travels in
  the prospects metadata (`regex_alojamiento`).
- The removed rentals are written next to the prospects as `<prospects>_eliminados_alojamiento_airbnb.csv`
  (Dataplor id, name, address, categories, city, state, coordinates, `termino_regex`) and uploaded with them.
- The prospects CSV is written like every CSV (BOM, comma, CRLF, Dataplor JSON flattened); priorización
  parses `historical_popularity_scores` in JSON or flattened form (`pipeline/csv_text.py` in its repo).
- QA: input = known clients + out of territory + rented flats + prospects; every matched id is present in
  the cleaned file; ≥ 1 prospect.
- The executive report is regenerated next to the prospects (gold) with a closing funnel step
  `10 · Ya son clientes del bottler (Datamatch)`: each matched Dataplor point counted once, with the first
  step that found it, then `11 · Alojamiento tipo Airbnb (red de seguridad tras el Datamatch)` (card, funnel row, Excel
  summary). No channel CSV is written there: the prospects file is the deliverable. The silver CSV
  is never rewritten (it is the Front's input for every step, and published files are not re-uploaded).

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
- **poi_ref**: rows sorted by `prioridad_orden`, then score (desc), then `dataplor_id`, and numbered 1..N. It is
  the shared key of the KO and BOTTLER files (as in the approved Golfo package).
- **region**: the bottler's sub-territory, only when the territory GeoJSON features carry a region name
  (`region`, `Region`, `REGION`, `region_name`, `nombre_region`); otherwise the column is not written (Andina AR:
  one unnamed polygon, no `region`).
- **KO CSV** (19 columns, +`region` when known; anonymous): `poi_ref, prioridad, prioridad_orden, area, [region],
  probability_existence_cat, business_category, channel_cat, city, state, country, pop_density, car_mobility,
  walk_mobility, dist_to_main_road, dist_to_bus_stop, weighted_combined_score, hex_7, hex_8, hex_9`. Never
  `dataplor_id` (it leads back to the place), name, address, coordinates or client columns.
- **Full priorización CSV** (package root, `..._completa.csv`): every priorización column, 40k rows with
  names and coordinates; never in `results_ko`.
- **Cycle Excel closing row**: when the prospects are built, the Datamatch cycle Excel gets an "airbnb" row
  (rented flats removed from the prospects; "Quedan" = prospects) and goes back to its silver folder.
- **BOTTLER CSV** (Golfo order): `poi_ref, dataplor_id, prioridad, prioridad_orden`, every priorización column,
  `ref_<client column>_cercano…, dist_ref_m, area, [region], hex_7, hex_8, hex_9`.
- **CSV format** (both): UTF-8 with BOM, comma, decimal point (values as received), CRLF, and **no field
  ever needs quotes** (`excel_csv.write_csv`). Same for the Datamatch match CSVs, the Front client bases and
  the prospects. User 2026-11-23: the `;` + decimal comma version opened in one column in Google Sheets and
  LibreOffice and changed lat/long; the readers still detect `;` in files written meanwhile.
  Quoting rule
  (`adapters/gold_package.py::flat_text` / `write_csv`): Dataplor's JSON columns (`historical_*_scores`,
  `place_attributes`) become flat text (`2024-11: 0.9942 | 2024-12: 0.5`; attribute flags `environment_cozy |
  service_takeout`; `{}` empty), commas inside free text become ` - `, double quotes `'`, line breaks a space.
  Quoted JSON is valid CSV but LibreOffice/Excel (Spanish locale) split it at every comma and shifted the row
  (the hours landed under other headers); now even a naive comma split gives the same width on every line.
- **Opportunity Excel**: Resumen_Ejecutivo (universe = prospects + current clients), Por_Ciudad,
  Por_Provincia.
- **Maps** (KO and BOTTLER): one HTML; canvas + Web Mercator over Esri World Light Gray tiles (the only
  network use; data works offline); density dots at country zoom, H3 hexagons closer in at resolution 7
  (region), 8 (city) or 9 (neighbourhood) by zoom, or a fixed 7/8/9 chosen in the sidebar; the KO map carries
  hexagons only (no prospect or client coordinates, no client counts), the BOTTLER map adds points and clients; hexagons coloured
  by average priorización score (default) or by number of prospects, points by existence or score, quintile
  ranges in a floating legend; per-hexagon tooltip from the Dataplor columns; prospects without city,
  province or a priorización score (0 is drawn) are left out of the map only (CSVs keep them); `maps` CLI rebuilds only the maps
  of a finished run (`GoldPackagePort.build_maps`), never the uploaded CSV/Excel/deck;
  kin-hexmap palette (`MAP_PALETTE`: quintiles navy → teal → yellow → orange → red) in the canvas, Kin brand in the sidebar; points when zoomed or when the selection is small; province/city selectors (spellings
  grouped) fly to the selection; framing ignores the 2% outliers; KO shows no name of any point or client.
- **Deck** (.pptx): `cleaning_agent/adapters/assets/prospecting_deck_template.pptx` filled by shape id.
- **Client coordinates swapped** (latitude in the longitude column): detected against the prospects'
  extent, fixed for distances, flagged in every file's metadata (`alertas`, `POR VERIFICAR`).
- QA: KO rows = BOTTLER rows = priorización rows; KO has no name/coordinates/`dataplor_id`/client columns; every row has
  a priority.

## 5. Metadata of every layer file (`<archivo>_metadata.json`)

Keys in this order (Lineamientos): `origen, archivo, fecha, canal, analisis, #, % datos utiles,
por que se limpiaron, alertas, POR VERIFICAR`, then `insumos, capa, destinos, pais, bottler,
premise, proceso, run_id, code_version, qa` and step-specific keys (franchises, modules, cycle steps…).

**Paths are warehouse addresses only** (user, 2026-11-23: the metadata must not be tied to one person's
machine). `adapters/dwh_paths.py::DwhPathResolver` rewrites every value before a sidecar or lineage file is
written: a mirror file → `<container>/<blob>` (`data/<layer>/…` → `prospecting-data/<layer>/…`,
`data/prospection-datacleaning/…` as is); a downloaded file → the blob its download stage recorded; a
working file (`data/runs`, reports) → its path relative to the project; anything outside the project → the
file name only. `espejo_local` is dropped. Applies to `_metadata.json`, the `_qa.html` built from it, the
client-base metadata and `dataplor_pipeline_metadata.json`.
The per-stage lineage record never replaces a layer sidecar: when one exists it is added inside it as
`etapa_linaje` (`adapters/lineage.py`).

### Prospect maps: places without a city

A prospect with valid coordinates but no `city` (or `state`) takes the one of the nearest prospect that
has it (haversine, `domain/gold_package.py::fill_place_from_nearest`), so "Sin ciudad" no longer shows on
the map. Done offline: no coordinate is sent to a geocoding service. Only a point without coordinates keeps
the "Sin ciudad" / "Sin provincia" label. The CSVs keep the data as Dataplor delivered it.

### 5.1 Registro de prospección (final metadata)

User, 2026-11-23: "la metadata final debe responder" these 16 fields, in this order and with these names
(`domain/registry.py::REGISTRY_FIELDS`). Built at `stage_gold_package`, written into every gold sidecar
(section `vtm`) and at the top of `dataplor_pipeline_metadata.json`. Paths become DWH addresses.

| Field | Source |
|---|---|
| Fecha Corrida (Prosp.) | gold package date (yyyymmdd) |
| Iteración (Prosp.) | number of Datamatch steps in the cycle |
| Total Prospectar | prospects in the package (no match) |
| High & Moderate No Match | prospects with existence High or Moderate |
| Top Categorías Negocio (Prosp.) | top 5 High & Moderate categories with counts |
| Fecha Maestra Clientes (Prosp.) | yyyymmdd folder of the raw client base path |
| Responsable Prospección | `config.yaml` `registro_prospeccion.responsable` |
| Canal de Clientes | channel chosen in the client validation |
| Path Dataplor Clean | cleaned Dataplor in silver (`…_sin_franquicias.csv`) |
| Path DataMatch | `final_output.csv` of every Datamatch step |
| Path Dataplor Utilizado | Dataplor raw blob of the intake |
| Path Info Cruda Clientes | client base as given (before validation) |
| Path Resultados Azure (Prosp.) | gold package folder in the DWH |
| Comentarios (Prosp.) | package alerts and run warnings |
| Registrado por (Prosp.) | `config.yaml` `registro_prospeccion.registrado_por` |
| Fecha de Registro (Prosp.) | date the package was built |

A value the run cannot know is `POR COMPLETAR`.

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


## 7. Rules added on 2026-11-23

- **Module 7 · Airbnb / departamento** (`domain/cleaning/lodging_filter.py`): same regex as before
  (`LODGING_RENTAL_REGEX`, only inside `sub_category = lodging`), now in the cleaning pipeline and mandatory
  (`MANDATORY_MODULES`) and runs last, after modules 0–6. Drops go to `07_airbnb_lodging_removed.csv`; the
  executive report shows them as **step 8** (user: "un paso más para que sea 8") and in the Excel sheet
  "Airbnb". Report numbering: 0–6 modules, 7 channel, 8 Airbnb, 9 franchises by hand, 10 bottler clients
  (Datamatch), 11 Airbnb safety net after the Datamatch (0 for runs cleaned with module 7). Rented flats the
  final regex (step 5) already removed stay counted there (Andina: 172 in step 5, 242 in step 8).
- **Client validation is mandatory** and crosses each client with the bottler's territory GeoJSON (asked, or found
  in `prospection-datacleaning/global_geojson/`): column `territorio_bottler`, counts in the metadata and QA.
  Clients outside are marked, not removed (they are still clients and must not come back as prospects).
- **Paso 0** (`domain/upstream.py`): raw rows read, removed before the Front (status, coordinates, out of
  territory/far from clients), sent to the Front (bronze), removed in the Front, received from the Front. In the
  report HTML/PDF, the Excel "Resumen" and the report summary (`paso0: …`).
