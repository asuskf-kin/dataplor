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

## 2026-11-17 · Mapa de prospección: mapa base gratuito y estilo kin-hexmap

- Qué: el mapa se dibuja sobre las teselas de Esri World Light Gray (base bajo los hexágonos, nombres de
  calles y lugares encima), con hexágonos H3 que cambian de resolución con el zoom (6 región, 7 ciudad,
  8 barrio) y un tooltip por hexágono con lo que hay en Dataplor (prospectos, existencia, a ≤300 m de un
  cliente, clientes actuales, score, categoría principal). Colores del lienzo según la skill kin-hexmap
  del equipo: quintiles navy → teal → amarillo → naranja → rojo (opacidad .62), puntos rojo/azul/gris con
  borde negro, fondo #eef0f2, tooltip oscuro. Panel lateral, fuentes y logo siguen Kin.
- Por qué: la persona pidió mapas con calles como su referencia, colores de esa referencia solo en el mapa,
  y una fuente gratuita ("sin API o que sea free"). Reemplaza "mapas sin API": las teselas son la única red;
  sin internet los datos siguen funcionando sobre fondo gris.
- Descartado: CARTO Voyager y Positron (el mapa base de kin-hexmap) responden "API key required"; calles
  OSM embebidas (20+ MB por mapa); Esri World Topo con la paleta de la primera captura (reemplazado por la
  skill). Volumen UC/mes y share/ejecución de kin-hexmap: no están en Dataplor.

## 2026-11-17 · Mapa de prospección: score, resolución y leyenda

- El mapa deja fuera los prospectos sin ciudad, sin provincia o con score 0 (Andina AR: 9.083 de 55.895);
  los CSV del paquete los conservan. Los selectores y chips ya no muestran opciones vacías.
- Resolución H3 a elección: Auto (6/7/8 según zoom) o fija en 6, 7, 8 o 9.
- Color de hexágonos por score promedio (por defecto) o por n.º de prospectos; color de puntos por existencia
  o por score. Leyenda flotante en el mapa con los rangos reales de cada quintil y el n.º de hexágonos; el
  tooltip pone primero la métrica que colorea el hexágono, con su color.
- Por qué: la persona pidió quitar los registros sin datos, elegir la resolución 6–9 y una leyenda que resalte
  el score con su color, más una mejor experiencia (controles segmentados, interruptores, tooltip que no se sale).

## 2026-11-17 · Comando `maps` (rehacer solo los mapas)

- Qué: `uv run python -m cleaning_agent maps --thread <hilo> --gold-dir <carpeta del paquete>` lee la corrida del
  checkpoint (`gold_request`) y llama a `GoldPackagePort.build_maps`, que reescribe solo los dos HTML de mapas.
- Por qué: los mapas cambiaron varias veces después de subir el paquete de Andina; `redo` rehacía todo el paquete
  (CSV, Excel, deck) y cambiaría archivos ya subidos. Con `maps` lo publicado conserva tamaño y MD5, y cualquier
  persona puede rehacer los mapas sin esta sesión.

## 2026-11-17 · Mapa KO solo hexágonos; resoluciones 7/8/9

- Qué: el mapa KO ya no lleva latitud/longitud de prospectos ni de clientes, ni conteo de clientes por hexágono:
  solo hexágonos (los ids H3 ya son columnas del CSV KO; el encuadre usa el centro de la celda res 9). El mapa
  Bottler mantiene puntos y clientes. Resoluciones H3 del mapa: 7, 8 y 9 (Auto: 7 región, 8 ciudad, 9 barrio).
- Por qué: KO es anónimo igual que su CSV (sin nombre, coordenadas ni cliente); el mapa KO anterior embebía
  coordenadas. La persona fijó las resoluciones en 7, 8 y 9.

## 2026-11-17 · CSV del paquete gold con el formato de Golfo

- Qué: KO y BOTTLER se escriben como el CSV aprobado de Golfo (UTF-8 con BOM, coma, CRLF, comillas solo donde hacen
  falta, sin saltos de línea dentro de un campo). Nueva columna `poi_ref` (1…N por prioridad, luego score) como
  clave común; el KO lleva `poi_ref` y ya no `dataplor_id` (con el id se llega al nombre y la ubicación en Dataplor).
  `region` (subterritorio del bottler, como Golfo / Centro Pacífico) solo cuando el GeoJSON del territorio nombra sus
  regiones.
- Por qué: la persona pasó el CSV BOTTLER de Golfo como ejemplo, pidió que el formato no se rompa y que se respete lo
  que es para KO; eligió KO solo con `poi_ref`, y `region` "si no lo tienes no lo pongas" (Andina: un solo polígono
  sin nombre, sin `region`).
- Las columnas `ref_*_cercano` siguen la base de clientes de cada bottler (`gold_package.client_columns.reference`).

## 2026-11-17 · CSV sin campos entre comillas (JSON aplanado)

- Qué: `write_csv` pasa cada texto por `flat_text`: el JSON de Dataplor (`historical_*_scores`, `place_attributes`) se
  aplana a `clave: valor | …` (atributos: solo los nombres; `{}` vacío), comas del texto libre → ` - `, comillas → `'`,
  saltos de línea → espacio. Ningún campo necesita comillas.
- Por qué: al abrir el CSV en LibreOffice/Excel el JSON entre comillas se partía en cada coma y corría el resto de la
  fila (la persona lo vio en las horas). Era CSV válido, pero no se veía bien; el CSV de Golfo tiene el mismo problema.
  Verificado abriendo el BOTTLER de Andina con LibreOffice sin interfaz: 48 columnas, 0 valores fuera de su columna.

## 2026-11-17 · Republicación en gold con la fecha original (Andina AR)

- Qué: se reemplazaron en `prospecting-data/gold/ko/ar/andina/prospecting-data/20261111/` los CSV KO/BOTTLER y los
  dos mapas, con `_metadata.json` + `_qa.html` nuevos (`fecha` 20261111, `actualizacion.fecha` 20261117 y motivo).
  Subida con `AzureBlobStorage.upload(replace=True)`: 12 blobs, tamaño y MD5 verificados. Excel, deck y prospectos
  no se tocaron. Registro: `data/runs/dataplor-20261109-182659-d5b4/republish_gold_20261117.json`.
- Por qué: la persona pidió "actualiza en gold, mantén la fecha anterior". Es una excepción explícita a "no re-subir"
  (Lineamientos v1.1): el KO publicado llevaba coordenadas y `dataplor_id`, y los CSV se descuadraban.

## 2026-11-23 · Validación de la base de clientes bottler igual que Customer Potential

- Qué: `clean-clients` valida la base con las reglas de `dw_validar` (potential-customer-workflow): canal,
  coordenada válida, dentro del país con el polígono oficial IGN sin tolerancia (base invertida y filas con
  lat/lon invertidas o sin signo se corrigen), coordenada única (queda la primera) y no aislado (20 km).
  Reemplaza la versión con caja de coordenadas ± 0.5° del mismo día. Destino: `bronze/ko/{pais}/{bottler}/
  clients/{fecha}/`, la carpeta de clientes validados que ya usa el DWH (antes `clients_bottler_clean`, que
  no estaba en el DWH). Canal por defecto `todos`.
- Por qué: la persona pidió "todos los procesos para validar dato bottler como lo hacemos en
  potential-customer-workflow, mismo QA". Una caja deja pasar puntos en Chile o Uruguay; el polígono no. Sin
  filtro de canal porque la base sirve para sacar de los prospectos a quien ya es cliente, de cualquier canal.
  Andina AR (20261123): 61.023 leídos → 60.103 válidos; 5 sin coordenada, 11 fuera del país, 850 coordenada
  repetida, 54 aislados; base completa invertida y 2 filas con el signo corregido. QA 9/9.

## 2026-11-23 · Mapa de puntos en el QA de clientes bottler, sin APIs

- Qué: el `_qa.html` de `clean-clients` lleva un mapa estático (PNG de matplotlib embebido) con el contorno del
  país y las provincias (IGN local), los clientes válidos y los descartados con ubicación por motivo.
- Por qué: la persona pidió ver dónde están los puntos "sin necesidad de usar herramientas externas" y que "el
  mapa no debe tener APIs". Una imagen no usa red ni JavaScript (a diferencia del mapa de prospección con
  teselas Esri) y no deja las coordenadas de clientes como texto en la página.

## 2026-11-23 · Validación de clientes bottler como paso del flujo

- Qué: nodos `ask_validate_clients*` → `validate_clients` → `confirm_clients*` → `upload_clients` justo antes
  del primer `front_datamatch`. Mismo validador que `clean-clients` (`wiring.client_validator`). El CSV
  validado pasa a ser la base de clientes por defecto del paso 1 del Datamatch. Se pregunta una vez (los pasos
  2+ usan la base reducida); no se pregunta si el país no tiene polígono configurado. Si la persona no aprueba
  la subida, la corrida se detiene como en las demás capas (el Front necesita el archivo en Azure).
- Por qué: la persona pidió "agrega este paso al flujo". Antes del Datamatch es donde entra la base al Front.

## 2026-11-23 · QA HTML por paso de Datamatch y CSV que abren bien en Excel

- Qué: cada paso del Datamatch deja `datamatch_<bottler>_pasoN_qa.html` en su carpeta (distancia real del
  match, evidencia de nombre/dirección, bandas de score, puntos Dataplor repetidos, historial y parámetros
  del Front) y `confirm_layer_upload` lo ofrece como `qa_html`. Los CSV del paso y la base de clientes
  validada se escriben como los de gold (BOM, CRLF, `flat_text`); el escritor pasó a `adapters/excel_csv.py`.
- Por qué: la persona pidió "no veo el reporte en html construyelo para cada paso" y "el csv al abrirlo se
  rompe": el resultado del Front trae `res_10_neighbors` con saltos de línea dentro del campo (15.991 en el
  paso 1 de Andina) y los archivos iban sin BOM. `flat_text` cambia comas por " - " en direcciones (el Front
  normaliza el texto; se confirma en el paso 2 con la base reducida). La base validada ya publicada en bronze
  no se reemplazó.

## 2026-11-23 · Página de umbral por paso de Datamatch (versión Kin del reporte de QA_datamatch)

- Qué: cada paso escribe `datamatch_<bottler>_pasoN_umbral.html` con los escenarios, curvas y pares
  marginales del `threshold_report` de QA_datamatch, calculados dentro del agente (numpy, sin scipy ni
  subproceso) y con la marca Kin. El umbral de limpieza se puede cambiar por paso (`umbral` /
  `redo --umbral`).
- Por qué: la persona pidió "un html donde puedo tomar decisiones, pásalo al brand y créalo también".
  Correrlo dentro del paso evita el otro proyecto, cuyo mapeo `.c`/`.o` es el inverso al del Front actual.
  Los pares llevan nombres y direcciones de clientes porque la decisión es si son el mismo lugar: por eso
  la página queda solo en el espejo local y no entra en la lista de subida (regla de datos de clientes).


## 2026-11-23 · Reporte ejecutivo con los clientes del Datamatch, en gold; decisiones en el linaje

- Qué: al armar los prospectos gold se regenera el reporte ejecutivo (HTML, PDF, Excel) con el paso
  `9 · Ya son clientes del bottler (Datamatch)` y sube con los prospectos. El linaje final trae
  `decisiones` (qué se decidió y por qué) leídas de `data/runs/<hilo>/decisiones.json`.
- Por qué: la persona pidió "primero actualiza el reporte", quitar del CSV silver los que hicieron match
  y que "esos suben a gold", y "en el linaje agregar todo lo que hicimos y por qué". El CSV de silver no
  se reescribe: es la entrada del Front en los tres pasos y lo publicado no se re-sube; el archivo sin
  los clientes es el de prospectos gold.

## 2026-11-23 · ";" y coma decimal en los CSV que abren personas

- Qué: los CSV KO/BOTTLER del paquete gold y los de matches de cada paso del Datamatch se escriben con
  ";" como separador y coma decimal (`excel_csv.write_excel_csv`). Las bases de clientes que vuelven al
  Front y los prospectos que lee la priorización siguen con coma; los lectores del agente detectan el
  separador (`csv_separator`).
- Por qué: en Excel con configuración en español los archivos con coma se abrían "todo en una columna".
  Los archivos que lee un programa no cambian: el Front y la priorización esperan coma, y la priorización
  además hace `json.loads` sobre las columnas JSON de los prospectos.

## 2026-11-23 · Los CSV vuelven a coma y punto decimal

- Qué: los CSV KO/BOTTLER del paquete gold y los `datamatch_matches_*.csv` se escriben otra vez con coma y
  punto decimal (`write_csv`), como el resto. Se retira `write_excel_csv` (";" y coma decimal).
- Por qué: la persona abre los archivos en Google Sheets y LibreOffice; con ";" salían "todo en una
  columna" y lat/long cambiaban de formato. Los lectores del agente siguen detectando ";" en los archivos
  escritos mientras duró ese formato.

## 2026-11-23 · Paso de Datamatch corrido con una base anterior: `filtrar_a_base`

- Qué: si el Front corrió un paso con una base de clientes anterior (más grande), el paso ya no tiene que
  repetirse en el Front: con `filtrar_a_base: true` el agente descarta las filas del resultado cuyo cliente
  no está en la base del paso, cuenta cuántos clientes sacó (`clientes_fuera_de_base`) y lo deja como
  alerta en el QA. Sin la opción, el chequeo "los conteos cuadran" sigue deteniendo el paso.
- Por qué: el paso 4 de Andina AR se corrió con la base del paso 2 (52.095 clientes) en vez de la del
  paso 3 (50.738); la persona eligió filtrar en vez de repetir el Front. Es opt-in para que un error de
  base no pase en silencio.

## 2026-11-23 · Paso 10: fuera los alojamientos tipo Airbnb / departamento

- Qué: al armar los prospectos gold, después de quitar clientes y provincias fuera de territorio, se
  quitan los puntos de alojamiento cuyo nombre dice Airbnb, apartamento, departamento o sus variantes
  (`LODGING_RENTAL_REGEX`). El reporte ejecutivo los muestra como paso 10 y la metadata lleva el regex.
- Por qué: la persona pidió "sacamos los puntos de venta que tengan que ver con airbnb, apartamento,
  departamento y sus variantes", como paso adicional al Datamatch y en el reporte. El regex se calibró con
  Andina AR: solo dentro de `sub_category = lodging` (fuera de ahí caían universidades y bares llamados
  "Departamento"), sin `apto` ("apto celíacos"); hoteles, cabañas, suites y "alquiler temporario" quedan
  hasta que la persona decida.

## 2026-11-23 · Prospectos gold y CSV de priorización también sin comillas

- Qué: los prospectos gold se escriben con `write_csv` (BOM, coma, CRLF, JSON de Dataplor aplanado a
  `clave: valor | …`). En `Priorizacion_On_Premise_code`: `pipeline/csv_text.py` (`flat_text`,
  `parse_scores`), el paso 1 lee `historical_popularity_scores` en JSON o aplanado, `save_csv` escribe sus
  dos CSV con el mismo formato y `load_data` quita el BOM del primer encabezado. Se verificó con los
  40.595 prospectos de Andina: mismos conteos de popularidad con JSON y con texto aplanado; el CSV escrito
  no tiene comillas y se relee con las 65 columnas.
- Por qué: la persona abre los prospectos en Google Sheets / LibreOffice y el JSON entre comillas se partía
  en columnas ("el csv sigue viendose mal"). Antes se dejaba JSON porque la priorización hacía
  `json.loads`; la persona eligió aplanar y ajustar la priorización. Esto reemplaza la excepción de la
  entrada "\";\" y coma decimal" para los prospectos.

## 2026-11-23 · Mapa: también los prospectos con score 0

- Qué: el mapa dibuja los prospectos con ciudad, provincia y score de priorización, incluido 0; solo se
  quedan fuera los que no tienen score.
- Por qué: la persona pidió "en el mapa sí agrega los puntos con score = 0".

## 2026-11-23 · CSV de los alojamientos eliminados

- Qué: junto a los prospectos gold va `<prospectos>_eliminados_alojamiento_airbnb.csv` (id, nombre,
  dirección, categoría, ciudad, provincia, coordenadas y la palabra del regex), y sube con ellos.
- Por qué: "no veo en el repo los que salieron por AIRBNB".

## 2026-11-23 · Excel del ciclo con la fila de alojamiento y priorización completa en gold

- Qué: al armar los prospectos se reescribe el Excel del ciclo de Datamatch (`qa_process_report_<bottler>.xlsx`)
  con una fila final "airbnb" en "Cuántos salieron en cada paso" (puntos Dataplor que salen de los
  prospectos; "Quedan" = prospectos) y sube a su carpeta de silver con los prospectos. El paquete gold
  lleva en la raíz `dataplor_on_premise_priority_<bottler>_<pais>_<AAAAMM>_completa.csv` con todas las
  columnas de la priorización (con nombres y coordenadas: nunca en `results_ko`). El chequeo de privacidad
  del KO relee el CSV con su separador real: con ";" fijo veía una sola columna y no revisaba nada.
- Por qué: "no veo el airbnb acá, colócalo", "me falta un csv con las priorizaciones completas, no hablo
  de bottler ni de KO" y "recuerda que KO no se debe mandar nada que identifique nombre, lat long".

## 2026-11-23 · QA de prospección después del ciclo de Datamatch
- Qué: nuevo paso entre `next_datamatch_step` (done) y `stage_prospects`, adaptado de la skill
  `prospection-qa`: falsos negativos (prospecto a ≤ 300 m de un cliente con nombre distintivo parecido,
  score 0,4·geo + 0,6·nombre ≥ 0,65), lectura por categoría, no_match enriquecido, dos mapas y reporte.
- Decisiones de la persona: los falsos negativos se reportan y **ella decide** si salen de los prospectos;
  el cruce de categorías, las no bebidas y el benchmark de mercado los hace **Claude Code en un
  interrupt** (sin API); los archivos con nombres/coordenadas de clientes quedan **solo en el espejo
  local** y solo sube el reporte agregado.
- Por qué se apartó de la skill: folium carga Leaflet de un CDN (regla de mapas: solo teselas Esri, sin
  librerías) → mapa propio sobre Esri; Nominatim mandaría coordenadas afuera → el país sale del intake;
  la búsqueda web la hace Claude Code con el nombre del país; no se imprimen filas de clientes; el
  no_match enriquecido trae columnas clave y no las 60+ del Dataplor; reporte con la marca Kin.


## 2026-11-23 · Mapas con todos los prospectos, "Quedan hoy" del ciclo y 16 falsos negativos conservados
- Qué: los dos mapas del paquete gold dibujan todo prospecto con lat/long y score (40.595 en Andina AR);
  si falta ciudad o provincia se rotula "Sin ciudad" / "Sin provincia" en vez de descartarlo. El Excel del
  ciclo separa los dos conteos: clientes que siguen sin su punto Dataplor (42.044, base del siguiente paso)
  y prospectos finales (40.595), con la fila airbnb en su propia tabla "Después del ciclo". Los 16 posibles
  falsos negativos del QA de prospección se conservan en los prospectos.
- Por qué: "los mapas deben ser el mismo número que dices en el repo final de datamatch", "el excel
  estaba mal actualizado el quedan hoy arréglalo" (el 42k de clientes se confundía con los 40k prospectos)
  y la respuesta "Keep them" al QA.


## 2026-11-23: mapas sin "Sin ciudad" y metadata solo con direcciones del DWH

- Mapas: un prospecto con coordenadas y sin ciudad/provincia toma la del prospecto más cercano que la tiene
  (haversine, offline). Ninguna coordenada sale a un servicio de geocodificación. Los CSV no cambian.
- Metadata: cada `_metadata.json`, `_qa.html`, metadata de la base de clientes y linaje nombra archivos por
  su dirección en el DWH (`<contenedor>/<blob>`); lo que no está en el DWH queda relativo al proyecto o solo
  con el nombre. Se quita `espejo_local`. Los 53 sidecars del espejo local se reescribieron así.
- Por qué: "el mapa me hace ruido existe un sin… si no tiene ciudad búscala por su lat long… si no
  encuentras dale el punto a la ciudad más cercana" y "el metadata no debe estar ligado a mi local siempre
  y únicamente al dwh porque si no otra persona no va a poder".


## 2026-11-23: Airbnb en la limpieza, clientes obligatorios con territorio, paso 0 y registro de prospección

- Airbnb / departamentos: módulo 7 de la limpieza, siempre activo, con hoja "Airbnb" en el Excel del reporte
  ejecutivo. El cierre del Datamatch queda como red de seguridad (0 en corridas nuevas).
  Por qué: "lo de Airbnb es un paso que se debe agregar al pipeline de limpieza y también sacar su hojita en el
  proceso donde eliminamos las franquicias".
- Validación de clientes bottler obligatoria; pide el GeoJSON del territorio o lo busca en
  `prospection-datacleaning/global_geojson/`, y marca cada cliente dentro/fuera (no se quitan: siguen siendo
  clientes). Por qué: "la limpieza de clientes bottler es obligatoria, adicional pide el geojson o búscalo en el
  dwh, esto para cruzar con la localidad o donde los bottlers trabajan".
- Paso 0 en el reporte ejecutivo: raw, quitados antes del Front, enviados, eliminados en el Front, recibidos.
  Por qué: "agrega en el paso 0 cuántos vienen de raw y cuántos se eliminaron en el front".
- Registro de prospección de 16 campos (nombres y orden del usuario) en cada sidecar gold y en el linaje;
  lo desconocido queda "POR COMPLETAR". "Iteración" = pasos de Datamatch del ciclo (confirmado por el usuario, 2026-11-23).
  Por qué: "la metadata final debe responder Fecha Corrida (Prosp.) … Fecha de Registro (Prosp.)".
- Metadata del espejo ya publicada (36 blobs: 34 sidecars + 2 mapas) reemplazada en su lugar con OK explícito
  ("Replace in place"), verificada por tamaño y MD5.

- El apartado del metadata gold se llama `vtm` (usuario, 2026-11-23: "en gold en el metadato debe existir un apartado vtm con los datos que te solicité").

- Airbnb en el reporte = paso 8 (después del filtro de canal, 7); el módulo corre al final de la limpieza.
  Los departamentos que ya quita el regex final quedan en el paso 5 (Andina: 172 en el paso 5, 242 en el 8).
  Por qué: "no es mejor como ponerle como un paso más para que sea 8", eligiendo la opción que no mueve los
  pasos existentes.

- Los 8 pasos de limpieza (módulos 1–6, canal 7, Airbnb 8) vienen activos por defecto en el plan
  (`config.yaml` y el respaldo de `settings.py`). Por qué: "pero para manten activado por defecto los 8 pasos".
  El módulo 0 (solo nocturnos) sigue opcional: activarlo quita el módulo 5 y deja solo bares.

- El sidecar de linaje por etapa ya no pisa el `_metadata.json` de capa (QA, destinos, `vtm`): se agrega dentro
  como `etapa_linaje`. Por qué: en la corrida Andina 20261123, 7 de 8 sidecars del paquete gold quedaron solo con
  linaje (sin QA ni `vtm`); lo detectó la réplica local e2e del 2026-11-23.

- Comando `sidecars` (2026-11-23): reescribe solo `_metadata.json`/`_qa.html` de un paquete gold ya armado (QA, `vtm`,
  `etapa_linaje` desde el linaje del hilo), sin tocar los datos. Por qué: "actualiza todo y déjalo para que otro pueda usar
  este proceso sin necesidad de esta sesión"; el arreglo de Andina 20261123 no debe depender de un script de la sesión.
  `--clientes-crudos` existe porque los hilos que validaron clientes con `clean-clients` no guardaron la base cruda.
  Andina 20261123 regenerado en local con la base `prospecting-data/drop_zone/ko/ar/andina/clients_bottler/20261020/Listado clientes Andina.csv`.
