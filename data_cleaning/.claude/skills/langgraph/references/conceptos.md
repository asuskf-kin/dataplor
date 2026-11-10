# LangGraph · conceptos y API (Python)

Fuente: docs.langchain.com, leída el 2026-11-09 (copia local en `referencia/langchain/paginas/oss_python_langgraph_*.md`).
Versión verificada: `langgraph` 1.2.20. Lo marcado ✔ se ejecutó en `ejemplos/`; lo demás sale de la doc y no se corrió.

Base de URL: `https://docs.langchain.com/oss/python/langgraph/<página>` (añadir `.md` da el markdown crudo).

## 1. Qué es

Runtime y framework de orquestación de bajo nivel para agentes **de larga duración y con estado**. Defines un grafo
de estado compartido, nodos y aristas, y mezclas pasos deterministas con pasos del LLM. No prescribe prompts ni
arquitectura. No requiere LangChain, aunque los ejemplos lo usan para modelos y tools (`overview`).

- LangChain 1.x `create_agent` corre **sobre** LangGraph. `create_react_agent` de LangGraph está **deprecado** en
  favor de `create_agent` (`releases/langgraph-v1`).
- v1 fue una versión de estabilidad: los primitivos (estado, nodos, aristas) y el modelo de ejecución no cambiaron.

## 2. Graph API

| Pieza | API | Notas |
|---|---|---|
| Estado | `TypedDict` (también dataclass o Pydantic) | Cada clave es un *channel* |
| Reducer | `Annotated[list[X], operator.add]` | Sin reducer, la actualización **reemplaza**; con reducer, **acumula**. Necesario cuando nodos paralelos escriben la misma clave ✔ |
| Mensajes | `MessagesState` o `messages: Annotated[list[AnyMessage], operator.add]` | `from langgraph.graph import MessagesState` |
| Nodo | `builder.add_node("nombre", fn)` o `add_node(fn)` | `fn(state) -> dict` con **solo las claves que cambian**. Puede recibir `config: RunnableConfig` ✔ o `runtime: Runtime[Ctx]` |
| Arista fija | `add_edge(START, "a")`, `add_edge("a", END)` | `from langgraph.graph import StateGraph, START, END` |
| Arista condicional | `add_conditional_edges("a", ruta, ["b", END])` | `ruta(state)` devuelve el nombre del nodo. La lista de destinos sirve para dibujar el grafo ✔ |
| `Send` | `return [Send("worker", {"item": x}) ...]` desde una arista condicional | Map-reduce: un worker por ítem, en paralelo, con su propia entrada ✔ |
| `Command` | `return Command(update={...}, goto="b")` y tipo `Command[Literal["b","c"]]` | Actualiza y enruta en un solo return. Para enrutar sin actualizar, mejor arista condicional ✔ |
| Compilar | `builder.compile(checkpointer=..., store=...)` | `interrupt_before` / `interrupt_after` = breakpoints estáticos, para depurar |
| Ejecutar | `invoke`, `stream`, `stream_events`, `ainvoke`… | `config={"configurable": {"thread_id": "..."}}` |
| Límite | `recursion_limit` en el config | Ciclos sin salida terminan en `GRAPH_RECURSION_LIMIT` |
| Dibujar | `graph.get_graph().draw_mermaid()` | `draw_mermaid_png()` necesita red o dependencias extra |

**Functional API** (`functional-api`): `@entrypoint` y `@task` dan persistencia, `interrupt` y reintentos sin
definir un grafo explícito. Conviene cuando el flujo es código lineal con ifs; la Graph API, cuando quieres ver y
auditar las ramas. **POR VERIFICAR**: no se corrió ningún ejemplo de la Functional API.

## 3. Persistencia: checkpointer y store

- **Checkpointer**: guarda el estado del *thread* en cada super-step. Habilita memoria de conversación, HITL,
  time travel y tolerancia a fallos. Clave: `thread_id` (reusarlo continúa; uno nuevo empieza vacío).
- **Store**: memoria de largo plazo **entre threads** (preferencias, hechos), por namespaces.
- Implementaciones (`checkpointers`): `InMemorySaver` (incluido; se pierde al reiniciar), `SqliteSaver` /
  `AsyncSqliteSaver` (`pip install langgraph-checkpoint-sqlite`, desarrollo local ✔), `PostgresSaver` /
  `AsyncPostgresSaver` (producción; llamar `.setup()` una vez), MongoDB y Cosmos DB.
- `SqliteSaver.from_conn_string("archivo.sqlite")` es un context manager ✔.
- `durability=` en cada ejecución: `"exit"` (solo al terminar; no recupera caídas a mitad), `"async"` (riesgo
  pequeño de perder el último paso si el proceso cae), `"sync"` (escribe antes del paso siguiente) ✔.
- Inspección: `get_state(config)`, `get_state_history(config)` (del más reciente al más antiguo),
  `get_state(config, subgraphs=True)`, `checkpointer.list(None)` para todos los threads.
- Con **Agent Server** (LangSmith Deployment) la persistencia la pone el servidor: no se configura checkpointer.
- `DeltaChannel` (beta, `langgraph>=1.2`) guarda solo deltas en canales que crecen mucho.

## 4. Human-in-the-loop: `interrupt`

```python
from langgraph.types import interrupt, Command
decision = interrupt({"pregunta": "¿Apruebas?", "sql": state["sql"]}, response_schema=Decision)  # ✔
...
graph.invoke(Command(resume={"aprobado": True}), config)   # mismo thread_id ✔
```

Requisitos: checkpointer, `thread_id` y un payload serializable a JSON. Con `invoke` el payload sale en
`result["__interrupt__"]` ✔; con `stream_events(version="v3")`, en `stream.interrupts` y `stream.interrupted`.

Reglas (sección *Rules of interrupts*), que son las que más rompen grafos:
1. Al reanudar, **el nodo se vuelve a ejecutar desde el principio**. Lo que esté antes de `interrupt()` debe ser
   idempotente, o ir en otro nodo.
2. No envolver `interrupt()` en un `try/except` desnudo: pausa lanzando una excepción especial.
3. No reordenar ni saltar condicionalmente `interrupt()` dentro de un nodo: se emparejan por orden. Para validar
   la respuesta en bucle, usar una arista condicional, no `while True`.
4. `Command(resume=...)` es el **único** `Command` que se pasa como entrada. `update` y `goto` son para
   devolverlos desde nodos.
5. Varias interrupciones en paralelo se reanudan con `Command(resume={interrupt.id: valor, ...})`.
6. `response_schema` (Pydantic, TypedDict o dataclass; `langgraph>=1.2.12`) valida la respuesta y la devuelve
   tipada ✔. Studio la dibuja como formulario.

Alternativas de más alto nivel: el middleware `HumanInTheLoopMiddleware` de LangChain y el parámetro `interrupt_on`
de Deep Agents (ambos necesitan checkpointer).

## 5. Time travel

- **Replay**: `graph.invoke(None, snapshot.config)` re-ejecuta los nodos posteriores a ese checkpoint.
- **Fork**: `cfg = graph.update_state(snapshot.config, {...})` y luego `graph.invoke(None, cfg)` ✔.
  `update_state` **no** hace rollback: crea una rama nueva y la historia original queda intacta. Los valores pasan
  por los reducers igual que si los escribiera un nodo.

## 6. Tolerancia a fallos

- `add_node(..., retry_policy=RetryPolicy(max_attempts=3))` ✔. `retry_on` permite elegir qué excepciones reintentar.
- También hay timeouts por nodo (run e idle, con heartbeats). **POR VERIFICAR**: no se probaron.
- Si un nodo falla después de un efecto lateral, el reintento lo repite: usar claves de idempotencia.
- Si el proceso cae antes del primer checkpoint durable, el thread es indistinguible de uno que nunca existió.
  Para distinguirlos, registrar la admisión fuera del checkpointer (patrón outbox).

## 7. Subgrafos y multiagente

Un subgrafo es un grafo compilado usado como nodo.
- **Con claves compartidas**: `add_node("sub", subgrafo_compilado)` ✔.
- **Con esquemas distintos**: invocarlo dentro de una función nodo que traduce el estado de ida y de vuelta. Es
  el patrón para darle a cada agente su propio historial privado.
- Persistencia del subgrafo según `compile(checkpointer=...)`:
  - `None` (por defecto): *per-invocation*, hereda el checkpointer del padre; admite interrupts. Es el adecuado para
    la mayoría de los multiagentes.
  - `True`: *per-thread*; acumula memoria entre llamadas. No llamar el mismo subgrafo dos veces en un nodo.
  - `False`: sin checkpoints, como una función; sin interrupts ni recuperación.
- Patrones multiagente (supervisor, handoffs, router, subagentes como tools) en `langchain/multi-agent`. La librería
  `langgraph-supervisor` tiene guía de migración (`migrate/langgraph-supervisor`). **POR VERIFICAR**: estado actual de
  esa librería.

## 8. Streaming

- `stream(..., stream_mode=[...], version="v2")` (LangGraph ≥ 1.1): cada parte es `{"type", "ns", "data"}` ✔.
  Modos: `values`, `updates`, `messages` (tokens del LLM y metadata), `custom` (`get_stream_writer()`),
  `checkpoints`, `tasks`, `debug`. Con `subgraphs=True`, `ns` identifica el subgrafo ✔.
- `stream_events(input, version="v3")` (LangGraph 1.2): proyecciones tipadas `stream.messages`, `.values`,
  `.output`, `.subgraphs`, `.interrupts`, `.interrupted`. La doc lo recomienda para apps nuevas, pero la 1.2.20
  emite `LangChainBetaWarning: The v3 streaming protocol on Pregel is experimental` ✔.

## 9. Despliegue

- Local: `pip install -U "langgraph-cli[inmem]"` (Python ≥ 3.11), `langgraph.json` con
  `{"dependencies": ["."], "graphs": {"agente": "./agente.py:graph"}, "env": ".env"}` y `langgraph dev`
  (API en `http://127.0.0.1:2024`, Studio en smith.langchain.com). Es modo en memoria, solo para desarrollo.
- Producción: **LangSmith Deployment** (Cloud, híbrido, standalone server o self-hosted con control plane).
  Cliente: `langgraph_sdk.get_client` / `get_sync_client`. **POR VERIFICAR**: no se desplegó nada.
- Alternativa propia: el grafo compilado es una librería; se puede servir con tu propia API y un checkpointer de
  Postgres. Ahí la autenticación, la cola y el streaming los pones tú.
- Trazas: `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY` en el entorno. LangGraph traza de forma nativa.

## 10. Testing (`test`)

Compilar el grafo con `InMemorySaver` y probar nodos sueltos o el grafo con modelos falsos. `ejemplos/` usa
**inyección de dependencias** (puertos `Planificador` y `Verificador`) para probar sin red. En LangChain, los
modelos falsos `GenericFakeChatModel` y `FakeMessagesListChatModel` no implementan `bind_tools`, por eso
`calculadora.py` define `ModeloFalso` ✔.

## 11. Claude como modelo (langchain-anthropic 1.7.10)

- `ChatAnthropic(model="claude-opus-5-5", max_tokens=16000, timeout=120, max_retries=2)` o
  `init_chat_model("anthropic:claude-opus-5-5")`. La API key solo se lee de `ANTHROPIC_API_KEY`.
- **No pasar `temperature`, `top_p` ni `top_k`** (el quickstart oficial usa `temperature=0`). Con Sonnet 5.5 y Fable,
  langchain-anthropic lanza `ValueError` ✔; con Opus 5.5, la API los rechaza (fuente: skill `claude-api`).
- **Salida estructurada**: `with_structured_output(Modelo, method="json_schema")` usa `output_config.format` ✔.
  El método por defecto, `function_calling`, fuerza `tool_choice`, que da 400 en Opus 5.5, Sonnet 5.5 y Fable 5.1+.
  La librería avisa con `UserWarning` ✔.
- `bind_tools` no fuerza `tool_choice` (payload inspeccionado ✔).
- Sin `max_tokens`, la librería pide 128000 para Opus 5.5 ✔. Para llamadas sin streaming conviene acotarlo.
- **POR VERIFICAR**: ninguna llamada real a Claude se ejecutó (no había `ANTHROPIC_API_KEY` en la sesión de
  creación). Se verificó el payload que se enviaría, no la respuesta.
