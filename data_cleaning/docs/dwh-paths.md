# Warehouse paths — every artifact of a cycle

Containers: **`prospecting-data`** (the DWH), **`dataplorraw`** (raw Dataplor, read only),
**`prospection-datacleaning`** (Front inputs/outputs). Rules from "Lineamientos Blob CP v1.1" plus the
decisions in `DECISIONS.md`:

- lowercase, underscores; `<capa>/ko/<pais>/<bottler>/<entidad>/[<analisis>]/<fecha>/<archivo>`;
- `<fecha>` = `yyyymmdd`; the run date for bronze/silver, the current date for the steps marked *today*;
- every file ships with `<archivo>_metadata.json` and (layer files) `<archivo>_qa.html`, is mirrored under
  `data/` with the same path first, and is uploaded only after the person approves;
- no re-upload (same size + MD5 → skipped), replace only with explicit `replace: true`.

Every template below lives in `config.yaml`; never write a path by hand in code.

| Step | Container | Path (Andina Argentina example) | Files | Config key |
|---|---|---|---|---|
| Raw Dataplor (input) | `dataplorraw` | `dataplor_raw_parquet/2026-10-15_ar.csv.parquet/part-*.snappy.parquet` | raw parquet | `dataplor_raw.container` |
| Bronze (pre-filter) | `prospecting-data` | `bronze/ko/ar/andina/dataplor/20261109/distance/` (`clients_bottler/` in client mode) | `dataplor_distance_ar_andina_20261109.parquet` + sidecars | `dwh.path_template` |
| Bronze copy beside the raw | `dataplorraw` | `dataplor_raw_parquet/2026-10-15_ar.csv.parquet/distance/20261109/` | same 3 files | — |
| Front result (input) | `prospection-datacleaning` | `andina_ARG_20261110/dataplor_cleaned/dataplor_cleaned_2.csv` + `json_config.json` | — | `dataplor_raw.front_container` |
| Silver (cleaned) | `prospecting-data` | `silver/ko/ar/andina/dataplor/20261109/` | `pdv_trad_on_ar_andina_20261109.parquet`, `*_sin_franquicias.csv`, drop report, executive report HTML/PDF/Excel, sidecars | `dwh.path_template` |
| Gold (executive Excel) | `prospecting-data` | `gold/ko/ar/andina/dataplor/20261109/` | `reporte_ejecutivo_*.xlsx` + metadata | `dwh.path_template` |
| Datamatch result (input) | `prospecting-data` | `silver/ko/ar/andina/20261110_data_match_process/20261110/final_output.csv` (written by the Front) | — | — |
| Client base (input) | `prospecting-data` | `drop_zone/ko/ar/andina/clients_bottler/20261020/Listado clientes Andina.csv` | — | — |
| Datamatch loop, step N (*today*) | `prospecting-data` | `silver/ko/ar/andina/data_match_process/qa_process/20261111/pasoN/` | reduced client base, matches, `pasoN.json`, sidecars | `datamatch.qa_process_template` |
| Datamatch cycle report (*today*) | `prospecting-data` | `silver/ko/ar/andina/data_match_process/qa_process/20261111/` | `qa_process_report_andina.xlsx` + metadata (rewritten each step: `replace: true` from step 2) | same |
| Gold prospects (*today*) | `prospecting-data` | `gold/ko/ar/andina/prospecting-data/20261111/` | `prospects_pdv_trad_on_ar_andina_20261111.csv` + sidecars | `datamatch.prospects_template` |
| Priorización (*today*) | `prospecting-data` | `bronze/ko/ar/andina/providers/dataplor_on_premise_priority_andina_argentina/20261111/` | `1_priority_andina_argentina_202611.csv`, `dataplor_on_premise_priority_andina_argentina_202611.csv` + sidecars | `priorizacion.output_template` |
| Priorización geo layers (input, shared) | `prospecting-data` | `bronze/providers/dataplor/sl/argentina/WorldPop_Overpass/` | roads, bus stops, WorldPop raster | read only (priorización repo) |
| Gold delivery package (*today*) | `prospecting-data` | `gold/ko/ar/andina/prospecting-data/20261111/` | `andina_argentina_analisis_oportunidad_on_premise_202611.xlsx`, `prospecting_andina_argentina_202611.pptx` | `gold_package` |
| — KO results | `prospecting-data` | `…/20261111/results_ko/` | `dataplor_on_premise_priority_andina_ar_202611_ko.csv`, `prospection_map_andina_ko.html` | `gold_package` |
| — BOTTLER results | `prospecting-data` | `…/20261111/results_bottler/` | `dataplor_on_premise_priority_andina_ar_202611_bottler.csv`, `prospection_map_andina_bottler.html` | `gold_package` |
| Lineage (local) | — | `data/runs/<thread>/dataplor_pipeline_metadata.json` | whole-run lineage | — |

**Silver file name**: `pdv_<canal>_<premise>_<pais>_<bottler>_<fecha>` (`trad`/`mod`, `on`/`off`/`on_off`) —
which outlets survived the cleaning.

Paths that do not follow the DWH pattern (the raw, the priorización geo layers, the Front's own output) are
production locations of other systems: the agent reads them and never moves or renames them.
