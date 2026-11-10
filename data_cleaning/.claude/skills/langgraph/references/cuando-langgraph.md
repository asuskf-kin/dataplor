# ¿LangGraph u otro harness?

Criterio del curso (`curso/PATH_APRENDIZAJE.md`, parte C): **Claude Code es el harness de referencia**. Los demás
se eligen por lo que necesitas controlar, no por moda.

## 1. ¿Hace falta un grafo? (regla 3 de 5)

Pasa de loop único (o maker/checker) a grafo **solo si se cumplen al menos 3**:
1. Hay trabajo paralelizable.
2. Hay ramas o rollback.
3. El estado intermedio es valioso: reanudar, auditar, time travel.
4. El "hecho" es verificable **por nodo**.
5. El beneficio de coordinar es mayor que su costo (código, latencia, *orchestration tax*).

Con menos de 3, alcanza con un loop y un buen harness (YAGNI). El Analista Autónomo cumple 2, 3 y 4, y el 5 por
la aprobación humana: por eso la clase 22 lo pasa a grafo.

## 2. Tabla de decisión

| Necesitas… | Usa | Por qué |
|---|---|---|
| Programar y operar software en tu repo | **Claude Code** | Harness completo: CLAUDE.md, skills, hooks, permisos, subagentes, MCP, loops |
| Que el agente **sea tu producto**, con el loop de Claude Code como librería | **Claude Agent SDK** | `query()`, tools integradas, hooks, `canUseTool`, presupuestos. Solo modelos Claude (Anthropic, Bedrock, Vertex, Azure) |
| Un agente estándar, multiproveedor, con piezas de harness componibles | **LangChain `create_agent` + middleware** | Middleware prearmado: reintento de tools y modelo, fallback, límites de llamadas, resumen de contexto, HITL, PII, to-dos, selector de tools. Corre sobre LangGraph |
| Flujo **explícito y auditable**: ramas, rollback, aprobación humana, reanudar tras una caída, pasos deterministas mezclados con el LLM | **LangGraph** | `StateGraph`, checkpointer, `interrupt`, time travel, ejecución durable, `Send`/`Command` |
| Un agente tipo Claude Code pero propio y multiproveedor | **Deep Agents** (`create_deep_agent`) | Harness sobre LangGraph: planificación con to-dos, sistema de archivos con backends, subagentes, skills, memoria, `interrupt_on` |
| Un agente **siempre encendido**, con modelos locales (Ollama), gateway de chat, cron o perfiles | **Hermes Agent** | Runtime abierto de Nous Research: loop `AIAgent`, toolsets, backends de terminal, cron, gateway |

Fuentes: `concepts/products` de docs.langchain.com (framework, runtime y harness; "When to use LangGraph":
control fino, ejecución durable, flujos que mezclan pasos deterministas y agénticos, despliegue); `langchain/
middleware/built-in`; tabla Deep Agents frente a Claude Agent SDK en la doc de Deep Agents (resumida en
`referencia/langchain/notas/lc1.md`); parte C del PATH para Hermes.

## 3. Cómo se combinan (no son excluyentes)

- `create_agent` y `create_deep_agent` **devuelven grafos de LangGraph**. Se pueden meter como nodo o subgrafo en un
  `StateGraph` propio, y heredan checkpointer, streaming e `interrupt`.
- Patrón típico del curso: **grafo LangGraph afuera** (orquestación auditable) y **agentes dentro de los nodos**.
  Por ejemplo, un nodo `planear_sql` que llama a Claude con salida estructurada.
- El Claude Agent SDK también puede ir dentro de un nodo como una función más. **POR VERIFICAR**: no hay ejemplo
  oficial de LangChain de esa combinación. Ojo: dos loops anidados duplican costo y presupuestos.

## 4. Equivalencias útiles para la clase 21–23

| Necesidad | Claude Code / Agent SDK | LangChain middleware | LangGraph | Deep Agents |
|---|---|---|---|---|
| Aprobar una acción | `PreToolUse` hook / `canUseTool`, permisos `ask` | `HumanInTheLoopMiddleware` | `interrupt()` + `Command(resume)` | `interrupt_on={...}` |
| Reanudar | `--resume` / sesiones | checkpointer de LangGraph | checkpointer + `thread_id` | checkpointer |
| Subagentes | subagentes (`.claude/agents`, `agents=`) | middleware de subagente | subgrafos / `Send` | `subagents=[...]` |
| Límite de presupuesto | `--max-turns`, `maxBudgetUsd` | `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware` | `recursion_limit`, contador en el estado | heredado del middleware |
| Contexto largo | compactación automática | `SummarizationMiddleware` | lo diseñas tú (reducer o nodo de resumen) | resumen y expulsión de resultados grandes |

Los cuatro middleware de la tabla se importan desde `langchain.agents.middleware` (verificado con langchain
1.4.9). Sus parámetros no se probaron.

## 5. Señales de que LangGraph es demasiado

- El grafo es una línea recta sin ramas, sin interrupts y sin reanudación: usa una función o `create_agent`.
- Cada nodo es "llamar al LLM con todo el historial": es un loop disfrazado.
- Pasas más tiempo depurando el enrutamiento que el problema: simplifica y mide con ablación (clase 27).
