---
name: limpiar-dataplor
description: Corre el agente de limpieza y prospección de Dataplor (LangGraph con human-in-the-loop) desde Claude Code. Primero pregunta país (ISO 2), bottler, tradicional/moderno, off/on premise/ambos y el path del Dataplor raw; luego si va a limpiar el Dataplor (distancia = GeoJSON, client bottler o no), bronze, Front, Pipeline Data clean, franquicias, silver, ciclo de Datamatch, prospectos gold, priorización y paquete gold (KO / BOTTLER, Excel, mapas, deck). Úsala cuando pidan "limpia los datos", "corre el pipeline", "limpiar dataplor", "cruzar territorio", "filtrar por clientes", "reanuda la limpieza" o "en qué va la corrida <hilo>".
---

# Limpiar Dataplor (agente con human-in-the-loop)

El flujo vive en `cleaning_agent/` (LangGraph + Pydantic, arquitectura hexagonal). Claude Code es el harness:
corre la CLI, lee la pregunta pendiente y se la hace al usuario. **Claude nunca contesta una pregunta del
agente por su cuenta**: cada `interrupt` es una decisión del usuario.

## Protocolo

1. **Iniciar** (o reanudar si el usuario da un hilo):
   ```bash
   uv run python -m cleaning_agent start
   uv run python -m cleaning_agent status --thread <hilo>
   ```
   La salida es un único JSON en stdout (los logs van a stderr). Guarda `thread_id`.
   **Estado de cada paso:** el JSON trae `steps` (todo el flujo en orden: done, waiting_for_human, pending,
   retry, failed, skipped, not_run, con inicio/fin) y `current_step`. Muéstrale al usuario una tabla corta
   con ese estado en cada turno. También queda en `data/runs/<hilo>/PROGRESS.md` y `progress.json`
   (sobrevive entre sesiones: léelo al retomar un hilo).
   Los pasos largos (descargas) reportan avance en stderr (`fetch_raw: 45% (520 / 1095 MB)`): lánzalos en
   segundo plano y lee ese log si el usuario pregunta cómo va.

2. **Mientras `status == "waiting_for_human"`**, mira `interrupt.kind` y pregunta:

   | `kind` | Cómo preguntar | Respuesta a enviar |
   |---|---|---|
   | `intake` | **Primero, y en este orden**, una pregunta por campo de `interrupt.fields`: país (ISO 2, de `options`), bottler, tradicional o moderno, off premise / on premise / ambos, path del Dataplor raw. Usa AskUserQuestion donde hay `options` | `{"country": "mx", "bottler": "Femsa", "channel": "tradicional", "premise": "on_premise", "dataplor_raw": "data/raw/mx/femsa/part-*.parquet"}` |
   | `choose_cleaning` | AskUserQuestion: *"¿Va a limpiar el Dataplor?"* con las 3 opciones de `interrupt.options` (sí por distancia = GeoJSON, sí por client bottler, no) | `{"clean": true, "type": "distancia"}` · `{"clean": true, "type": "client_bottler"}` · `{"clean": false}` |
   | `collect_inputs` | Muestra `interrupt.defaults` (ya vienen del intake) y `interrupt.errors`. **distancia** → pide el GeoJSON del territorio; **client bottler** → el CSV de clientes (+ columnas lat/lon, radio); **no** → solo confirma la salida | Solo los campos que cambian, p.ej. `{"geojson": "data/raw/mx/femsa/territorio.geojson"}`; `{}` acepta los defaults |
   | `confirm_plan` | Resume modo, rutas y `interrupt.modules` (y `notes`). AskUserQuestion: aprobar / cambiar módulos / cancelar | `{"approved": true, "modules": [1,2,3,4,5,6]}` o `{"approved": false, "note": "..."}` |
   | `confirm_layer_upload` | **Acción hacia afuera.** Capa (`layer`), archivos (`files`: dato + `_metadata.json` + `_qa.html`), QA (`qa`: filas leídas, eliminadas por motivo, checks) y destino (`defaults.container` / `defaults.blob_prefix`, p.ej. `prospecting-data` / `bronze/ko/ar/andina/dataplor/20261109/distance`, más la copia junto al raw en `dataplorraw`). Ofrece abrir `qa_html`. AskUserQuestion: subir / dejar solo en el espejo local | `{"approved": true}` (o con `container`/`blob_prefix` cambiados) · `{"approved": false}` (bronze: la corrida se detiene con todo en el espejo local) |
   | `front_dataplor` | El bronze ya se subió. Manda al usuario al Front (`front_url`) con los archivos de `bronze_files`; **él** continúa el proceso ahí. Espera y pide el path del resultado y el JSON de ese paso (blobs; contenedor por defecto `prospection-datacleaning`). No operes el Front por él | `{"result_file": "andina_ARG_20261110/dataplor_cleaned/dataplor_cleaned_2.csv", "metadata_json": "andina_ARG_20261110/dataplor_cleaned/json_config.json"}` |
   | `update_patterns` | Los patrones del país faltan o tienen > 6 meses. **Tú (Claude Code)** creas/actualizas `file` (CHAIN_REGEX de cadenas y franquicias reconocidas + `PATTERNS_UPDATED`), **muestras el diff** y esperas el OK del usuario | `{"approved": true}` tras su OK · `{"approved": false}` |
   | `franchise_review` | **Tú (Claude Code)** lees `candidates_file` (nombres + registros) y detectas franquicias que quedaron (OXXO, Costco, las más reconocidas del país). Muestra la lista al usuario | `{"flagged": [{"name": "<exacto>", "marca": "OXXO"}]}` o `{"flagged": []}` |
   | `confirm_franchises` | AskUserQuestion: marqué N registros (`by_brand`); ¿eliminarlos? (se marcan siempre; si se eliminan sale `_sin_franquicias.csv`) | `{"remove": true}` · `{"remove": false}` |
   | `confirm_layer_upload` (silver / gold / datamatch / prospectos / priorización / paquete gold) | **Acción hacia afuera.** Muestra `layer`, `files`, `destinations` y `extra_destinations` (archivos que van a subcarpetas: reporte del ciclo, `results_ko/`, `results_bottler/`), `qa` y `report_files`. Si `qa` trae alertas (p.ej. coordenadas de clientes intercambiadas), dilas. AskUserQuestion: subir / no subir | `{"approved": true, "replace": false}` · `{"approved": false}` · para reemplazar un blob existente solo si la persona lo pide: `"replace": true` |
   | `front_datamatch` | **Ciclo de Datamatch.** Dale el link `front_url` y el archivo a subir; **la persona** corre Datamatch en el Front con el JSON del paso. Pide: ruta del resultado (`final_output.csv`; rutas `silver/…` se leen de `prospecting-data`), base de clientes (en pasos 2+ el default es la base reducida del paso anterior) y el JSON del paso (`pasoN.json`). No operes el Front | `{"datamatch_file": "silver/ko/ar/andina/<…>/final_output.csv", "clients_file": "drop_zone/ko/…/clientes.csv", "client_name": "andina", "step_json": "C:/…/paso1.json"}` |
   | `datamatch_loop` | Tras subir el paso: muestra `last_step` (clientes inicio / con match / restantes) y `new_clients_file` (la base reducida para el Front). AskUserQuestion: otro paso / ya estamos, seguimos con la prospección | `{"done": false}` (otro paso) · `{"done": true}` (sigue a prospectos gold, priorización y paquete gold) |
   | `ask_priorizacion` | **Acción hacia afuera** (priorización escribe sus CSV en Azure). Muestra `configs` y `defaults`: `base_config` (YAML del país o `mexico_golfo.yaml` como donante), `period` AAAAMM, `input_blob` (los prospectos gold), `output_dir` (`bronze/ko/<pais>/<bottler>/providers/dataplor_on_premise_priority_<bottler>_<pais>/<fecha>`). Si un path no cuadra con el DWH, avísalo antes | `{"run": true}` · `{"run": true, "base_config": "<yaml>"}` · `{"run": false}` |

   Envía la respuesta (en Windows, si el JSON tiene comillas difíciles, escríbelo a un archivo del scratchpad y
   usa `--answer-file`):
   ```bash
   uv run python -m cleaning_agent resume --thread <hilo> --answer '<json>'
   ```
   Si `interrupt.errors` no está vacío, la respuesta anterior era inválida: muéstrale los errores al usuario y
   vuelve a preguntar. Tras `agent.max_input_attempts` intentos el hilo se cancela.

3. **Fin**: el último paso es `build_lineage` (linaje en `data/runs/<hilo>/dataplor_pipeline_metadata.json`).
   Otros finales: `kept_local` (la persona no aprobó una subida), `cancelled`, `failed` (muestra `error`; el
   hilo queda guardado y se puede revisar con `status` o rehacer con `redo`).

4. **Presentación**: el deck de resultados para revisar se arma como **Artifact de Slides** sobre el design
   system "Kin Design System - Kin Official" (tablas con encabezado amarillo Kin, ≥ 26 px), con las cifras de
   `deck_figures` del paquete gold. El .pptx que queda en gold lo genera el agente.

Guía completa para el operador: `docs/runbook.md`; reglas: `docs/spec.md`; rutas: `docs/dwh-paths.md`.

## Reglas

- No inventes rutas ni contestes por el usuario. Si no sabe una ruta, ofrece `ls data/raw/<pais>/<bottler>/`.
- Las corridas con el Parquet completo de MX tardan minutos: lanza `resume` en segundo plano si el usuario
  aprobó el plan y avísale cuando termine.
- No abras ni muestres filas de archivos de clientes. Los pasos solo leen las columnas que necesitan
  (coordenadas; para la versión BOTTLER también id, nombre, gerencia y jefatura del cliente más cercano).
  Puedes mostrar conteos y nombres de columnas, nunca valores de clientes.
- Nunca leas ni muestres `.env` ni credenciales de Azure; si falta configurarlas, díselo al usuario.
- Entregables HTML/PDF/imagen siguen la skill `brand-guidelines-kin` (fuentes, tokens y logo embebidos).
- Para regenerar un paso tras un cambio de código: `uv run python -m cleaning_agent redo --thread <hilo> --after <nodo>`.
- El QA de Datamatch tarda ~1-2 min (`uv run --project ../../QA_datamatch`); avisa antes de lanzarlo.
- Para una prueba rápida, `max_batches: 2` en el formulario de geojson/clientes.
- El Dataplor raw se lee por defecto del blob `dataplorraw/...` (solo el raw). GeoJSON y clientes
  pueden ser locales o `<contenedor>/<blob>`; mientras se descarga el raw puedes adelantar insumos
  descargándolos a `data/raw/<pais>/<bottler>/insumos/` (el grafo no los vuelve a bajar si el tamaño coincide).
- DWH: capas drop_zone → bronze → silver → gold con la fecha yyyymmdd; las rutas salen de `config.yaml`
  (tabla en `docs/dwh-paths.md`). Si la persona da una ruta que no cuadra con el DWH (mayúsculas, espacios,
  `_` en vez de `/`, fecha antes de la entidad), avísale y propón la corregida antes de usarla.
- Mapas: nunca usan una API (sin tiles ni CDN). Presentaciones: como Artifact.
- Base de clientes con latitud/longitud intercambiadas: el paquete gold lo detecta y lo marca; recomienda
  rehacer el Datamatch con el mapeo de columnas corregido.
