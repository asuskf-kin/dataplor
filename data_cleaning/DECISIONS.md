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

## 2026-11-11 · Ciclo de Datamatch (Front <-> agente)

- Cada paso: la persona corre Datamatch en el Front con un JSON (`paso1.json`, ...). El agente
  baja el resultado y la base de clientes, toma como encontrados los clientes con
  `total_score > 0.5` (`datamatch.step_cleanup_threshold`) y los quita de la base.
- Salida por paso en `silver/ko/<pais>/<bottler>/data_match_process/qa_process/<fecha>/<paso>/`
  (entidad data_match_process, no dataplor; <fecha> = día del primer paso del ciclo): base
  reducida (`clients_bottler_<cliente>_<paso>.csv`), matches, el JSON del paso, un Excel
  on-brand que explica el paso, y `_metadata.json` de cada archivo. Se sube solo con OK.
- El bucle se repite (la base reducida es el default del siguiente paso) hasta que la persona
  dice que ya; entonces sigue la prospección (QA thresholds, subida, priorización, linaje).
- Excepción explícita a "solo columnas de coordenadas" de la base de clientes: para generar la
  base reducida hay que copiar las filas completas (pedido del usuario). Se copian archivo a
  archivo; al Excel y a los logs solo llegan conteos e identificadores, nunca nombres,
  direcciones ni coordenadas, y del JSON se omite la persona a cargo.
- En el resultado del Front, `.c` es la base de clientes (POS) y `.o` es Dataplor. El config del
  QA_datamatch asume lo contrario (`id.c -> dataplor_id`): revisar antes del QA final.

## 2026-11-11 · Prospectos en gold

- Al cerrar el ciclo de Datamatch, el Dataplor limpio sin franquicias (silver) pierde los puntos
  `id.o` que hicieron match en cualquier paso: ya son clientes del bottler. Lo que queda son los
  prospectos, primer dato de gold, en `gold/ko/<pais>/<bottler>/prospecting-data/<fecha actual>/`
  (`datamatch.prospects_template`), con `_metadata.json` + `_qa.html` y subida solo con OK.
- Priorización toma por defecto ese CSV. Los pasos viejos de QA thresholds y subida final
  salieron del grafo: el ciclo los reemplaza.

## 2026-11-11 · Paquete gold de entrega (modelo Golfo)

- Tras la priorización, el paso `stage_gold_package` arma en `gold/.../prospecting-data/<fecha>/`:
  Excel de oportunidad + deck (.pptx) en la raíz, y `results_ko/` y `results_bottler/` con su CSV
  y su mapa. Formato DWH (minúsculas, sin espacios) en lugar de "Results for KO/Bottler".
- `prioridad` 1–6 = área (dentro = cliente actual a ≤300 m) × existencia, como Golfo. KO es anónima
  (sin nombre, coordenadas ni cliente); BOTTLER lleva el cliente más cercano (`ref_<col>_cercano`).
  Leer nombre y jefatura de la base de clientes es una excepción explícita (solo versión BOTTLER).
- Mapas sin API (regla del usuario): canvas propio, sin tiles ni CDN. Deck: plantilla derivada del
  deck aprobado de Golfo sin datos del cliente (`scripts/build_prospecting_deck_template.py`), con el
  logo oficial (sin "Let knowledge in"). Las presentaciones para revisión van como Artifact (Slides).
- La base de clientes de Andina trae latitud y longitud intercambiadas: el paquete lo detecta y lo
  corrige para las distancias, y lo deja en alertas / POR VERIFICAR. El Datamatch del Front leyó las
  mismas columnas: por eso solo 92 matches y `distance_score` siempre 0.

## 2026-11-11 · Mapa de prospección: navegación

- Elegir provincia o ciudad filtra y vuela a la selección (encuadre robusto: se ignora el 2% de puntos
  extremos para que un punto mal geocodificado no aleje el mapa). Ciudad sin provincia elegida selecciona
  su provincia. "Encuadrar resultados" y "Limpiar filtros" para cualquier filtro.
- Dataplor escribe una misma provincia de varias formas ("Córdoba", "Provincia de Córdoba", "Cordoba",
  "Santa Fe Province"): los selectores las agrupan en un nombre canónico (la grafía más frecuente). Los
  CSV conservan el valor original.
- A escala país las celdas H3 miden menos de un píxel: se dibuja una capa de densidad; los hexágonos al
  acercarse; los puntos con zoom o cuando la selección tiene ≤ 6.000 puntos. Clic en un hexágono = vista de
  barrio. Teclado (+ − 0 Esc) y pellizco táctil. Sigue sin ninguna API.

## 2026-11-11 · Documentación para replicar

- `docs/` (runbook, spec, dwh-paths, architecture) es la referencia para que otra persona corra el ciclo;
  se actualiza en el mismo cambio que toca un paso, una regla o una ruta.

## 2026-11-11 · Priorización desde los prospectos

- Entrada: los prospectos de gold (datos limpios sin los clientes del Datamatch), base única
  como Golfo (`dataplor_without_datamatch_area`). No hace falta el split por embotellador: los
  prospectos ya son solo del territorio Andina.
- Salidas en `bronze/ko/<pais>/<bottler>/providers/dataplor_on_premise_priority_<bottler>_<pais_nombre>/<fecha actual>/`
  (`priorizacion.output_template`): `1_priority_<bottler>_<pais_nombre>_<AAAAMM>.csv` y el
  entregable `dataplor_on_premise_priority_<bottler>_<pais_nombre>_<AAAAMM>.csv` (minúsculas).
- No hay YAML de Argentina: los parámetros salen de `mexico_golfo.yaml`
  (`priorizacion.base_config`) y las capas geográficas se cambian a las del país, que ya están en
  `bronze/providers/dataplor/<region>/<pais>/WorldPop_Overpass/` (ubicación existente del repo
  de priorización, compartida; este agente solo la lee).
- Priorización escribe sus CSV en Azure al correr (la pregunta es la aprobación); después se
  bajan al espejo local, pasan QA (filas paso 1 <= prospectos, paso 2 = paso 1, 7 columnas
  geográficas) y se suben su `_metadata.json` + `_qa.html` con OK (los CSV se verifican por MD5).

## 2026-11-11 · Datamatch opcional

- Qué: en `front_datamatch`, `{"skip": true}` salta Datamatch. Sin pasos hechos va directo a
  `ask_priorizacion` con el CSV limpio de silver (el del reporte ejecutivo, sin franquicias) como entrada,
  y después de subir la priorización termina en `build_lineage`. Con pasos hechos, equivale a "ya estamos".
- Por qué: la persona pidió priorizar Bolivia/Embol sin esperar el Datamatch del Front.
- Costo: esa priorización incluye los clientes que el bottler ya tiene (no son prospectos) y no hay
  paquete gold, porque necesita la base de clientes y los matches. La pregunta de priorización lo avisa en
  `notes`.
- La entrada sale de la ruta del espejo (`data/<blob>` = `prospecting-data/<blob>`), no de `uploaded`,
  que solo guarda la última subida.
