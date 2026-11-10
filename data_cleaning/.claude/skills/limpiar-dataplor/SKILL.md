---
name: limpiar-dataplor
description: Corre el agente de limpieza de Dataplor (LangGraph con human-in-the-loop) desde Claude Code. Primero pregunta país (ISO 2), bottler, tradicional/moderno, off/on premise/ambos y el path del Dataplor raw; luego si va a limpiar el Dataplor (distancia = GeoJSON, client bottler o no), corre el Pipeline Data clean, el reporte ejecutivo, Datamatch (Front + QA) y la subida a Azure. Úsala cuando pidan "limpia los datos", "corre el pipeline", "limpiar dataplor", "cruzar territorio", "filtrar por clientes", "reanuda la limpieza" o "en qué va la corrida <hilo>".
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
   | `confirm_layer_upload` | **Acción hacia afuera.** Capa (`layer`), archivos (`files`: dato + `_metadata.json` + `_qa.html`), QA (`qa`: filas leídas, eliminadas por motivo, checks) y destino (`defaults.container` / `defaults.blob_prefix`, p.ej. `prospecting-data` / `bronze/ko/ar/andina/20261109/distance`). Ofrece abrir `qa_html`. AskUserQuestion: subir / dejar solo en el espejo local | `{"approved": true}` (o con `container`/`blob_prefix` cambiados) · `{"approved": false}` (bronze: la corrida se detiene con todo en el espejo local) |
   | `front_dataplor` | El bronze ya se subió. Manda al usuario al Front (`front_url`) con los archivos de `bronze_files`; **él** continúa el proceso ahí. Espera y pide el path del resultado y el JSON de ese paso (normalmente blobs `contenedor/ruta`). No operes el Front por él | `{"result_file": "prospecting-data/.../x.csv", "metadata_json": "prospecting-data/.../x.json"}` |
   | `approve_output` | Muestra `interrupt.summary` (filas por módulo) y la ruta de `interrupt.html_report`. AskUserQuestion: publicar / descartar | `{"approved": true}` o `{"approved": false, "note": "..."}` |
   | `ask_datamatch` | AskUserQuestion: *"¿Hacemos Datamatch con este resultado?"* (sí / no) | `{"run_datamatch": true}` |
   | `front_datamatch` | Dale el link `interrupt.front_url` y el archivo `interrupt.file_to_upload`: **la persona** lo sube al Front, corre Datamatch y descarga el resultado. No inicies sesión ni operes el Front por ella. Luego pide la ruta del archivo descargado (y confirma `clients_file` / `client_name` de `defaults`) | `{"datamatch_file": "C:/.../final_output.csv"}` |
   | `qa_thresholds` | Dile que abra `interrupt.qa_report` (HTML del QA) y pregunta los thresholds; muestra los `defaults` | `{"match": 0.71, "super_match": 0.8}` |
   | `confirm_upload` | **Es una acción hacia afuera.** Lista `interrupt.files` y el destino (`defaults.container` / `defaults.blob_prefix`). Si `storage_configured` es false, avisa que falta `AZURE_STORAGE_ACCOUNT_URL` (o `AZURE_STORAGE_CONNECTION_STRING`). AskUserQuestion: subir / dejar local | `{"approved": true, "container": "...", "blob_prefix": "..."}` o `{"approved": false}` |

   Envía la respuesta (en Windows, si el JSON tiene comillas difíciles, escríbelo a un archivo del scratchpad y
   usa `--answer-file`):
   ```bash
   uv run python -m cleaning_agent resume --thread <hilo> --answer '<json>'
   ```
   Si `interrupt.errors` no está vacío, la respuesta anterior era inválida: muéstrale los errores al usuario y
   vuelve a preguntar. Tras `agent.max_input_attempts` intentos el hilo se cancela.

3. **Fin**: `uploaded` (archivos en Azure), `kept_local` (CSV y QA solo en local), `cancelled`, `rejected`,
   `failed` o `error` (muestra `error`; el hilo queda guardado y se puede revisar con `status`).

## Reglas

- No inventes rutas ni contestes por el usuario. Si no sabe una ruta, ofrece `ls data/raw/<pais>/<bottler>/`.
- Las corridas con el Parquet completo de MX tardan minutos: lanza `resume` en segundo plano si el usuario
  aprobó el plan y avísale cuando termine.
- No abras ni muestres archivos de clientes: solo se usan sus columnas de coordenadas.
- Nunca leas ni muestres `.env` ni credenciales de Azure; si falta configurarlas, díselo al usuario.
- El QA de Datamatch tarda ~1-2 min (`uv run --project ../../QA_datamatch`); avisa antes de lanzarlo.
- Para una prueba rápida, `max_batches: 2` en el formulario de geojson/clientes.
- El Dataplor raw se lee por defecto del blob `dataplorraw/...` (solo el raw). GeoJSON y clientes
  pueden ser locales o `<contenedor>/<blob>`; mientras se descarga el raw puedes adelantar insumos
  descargándolos a `data/raw/<pais>/<bottler>/insumos/` (el grafo no los vuelve a bajar si el tamaño coincide).
- DWH: capas drop_zone → bronze → silver → gold con la fecha yyyymmdd; pregunta la ruta de cada archivo.
