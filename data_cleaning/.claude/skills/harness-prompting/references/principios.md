# Principios de Harness Engineering aplicados a prompts e interacción

Fuente: lectura completa (2026-11-06) de https://walkinglabs.github.io/learn-harness-engineering/en/: 14 lecciones,
8 proyectos, recursos y 4 desgloses de harness (repo walkinglabs/learn-harness-engineering, carpeta `docs/en`).
Copia local en `referencia/harness-engineering/paginas/` y notas en `referencia/harness-engineering/notas/h1-h3.md`.
La fuente de cada idea está entre corchetes (`L` = lección, `P` = proyecto, `R` = recurso).
Las cifras son las que cita el curso; si se van a citar, verificarlas en la fuente original.

## Idea madre
- **Harness** = todo lo que no son los pesos del modelo. No hace al modelo más listo: cierra el lazo de trabajo
  (objetivo → inicialización → ejecución → feedback → verificación → limpieza y handoff). [index, L02]
- **Ante un fallo, culpar primero al harness y no al modelo.** Con el mismo modelo, cambiar el harness cambia el
  resultado. Ejemplos citados: el editor de juegos 2D de Anthropic (sin harness: 20 min, US$9, no funciona;
  planner + generator + evaluator: 6 h, US$200, funciona) y LangChain en Terminal Bench (52,8 % → 66,5 %). [L01, L09]
- **Cinco subsistemas**: instrucciones, herramientas, entorno, estado y feedback. El feedback (comandos de
  verificación) es el de mayor retorno por esfuerzo. [L02]
- **Pila de capas**: prompt → contexto → loop → grafo. Se apilan; ninguna reemplaza a la anterior. El harness es la
  base. [L14]

## Diagnóstico de un fallo: cinco capas [L01]
1. Especificación de la tarea.
2. Contexto provisto.
3. Entorno de ejecución.
4. Verificación y feedback.
5. Gestión de estado.

Cada fallo se atribuye a una capa y se arregla esa capa (diagnostic loop), no se reescribe el prompt a ciegas.

**Mapa fallo → artefacto mínimo** [R method-map]:
| Fallo | Síntoma | Arreglo | Artefacto |
|---|---|---|---|
| Arranque en frío | la sesión nueva redescubre setup y estado | el repo como sistema de registro | `claude-progress.md` |
| Dispersión de alcance | empieza varias cosas y no termina ninguna | limitar el alcance activo (WIP = 1) | `feature_list.json` |
| Finalización prematura | dice "hecho" sin prueba ejecutable | atar el fin a evidencia | `clean-state-checklist.md` |
| Arranque frágil | cada sesión reaprende a levantar el proyecto | estandarizar setup y verificación | `init.sh` |
| Handoff débil | no se sabe qué está verificado o roto | handoff explícito | `session-handoff.md` |
| Revisión subjetiva | la calidad depende del gusto | rúbrica fija | `evaluator-rubric.md` |

**Regla**: añadir el artefacto más pequeño que ataque el fallo observado; nunca más texto en el archivo global.

## Instrucciones [L03, L04, R prompt-calibration]
- **"Si no está en el repo, no existe."** Las decisiones del chat se pasan a archivos (ARCHITECTURE, DECISIONS,
  PROGRESS) en la misma sesión.
- **Prueba de sesión fresca**: una sesión nueva, solo con el repo, debe responder:
  1. ¿Qué es?
  2. ¿Cómo está organizado?
  3. ¿Cómo se corre?
  4. ¿Cómo se verifica?
  5. ¿Dónde estamos?
- **Archivo raíz = mapa, no manual**:
  - Entre 50 y 100 líneas (Claude Code recomienda menos de 200).
  - **Qué se queda**:
    - Propósito.
    - Arranque.
    - Verificación.
    - Hasta 15 reglas duras.
    - Artefactos de estado.
    - Reglas de cierre.
    - Enlaces a docs con su condición de uso ("leer al tocar X").
  - **Qué se va**:
    - Casos borde históricos.
    - Detalle por tema.
    - Notas de arquitectura local, que van junto al código.
- **Lost in the middle**: lo crítico va al principio o al final, nunca en medio.
- **Cada regla lleva** su origen, cuándo aplica y cuándo caduca. Se auditan y se borran las obsoletas o
  contradictorias.
- **Imponer invariantes, no microgestionar la implementación.** Por ejemplo, "datos parseados en la frontera", sin
  dictar la librería.
- **La evidencia es mixta**: ETH Zurich encontró que AGENTS.md no mejora el éxito y sube el costo más de 20 %;
  Lulla et al., que reduce el tiempo un 28 %. Hay que **medir** el efecto de cada archivo de contexto, no darlo por
  supuesto.

## Estado y continuidad [L05, L06, L12, R startup-flow]
- **El agente olvida; el repo no.** La compactación conserva el *qué* y pierde el *porqué*. Por eso existe
  DECISIONS.md, que registra la alternativa rechazada.
- **Métricas**: rebuild cost (cuánto tarda una sesión nueva en quedar operativa) y drift. Si una tarea va a usar más
  del 60 % de la ventana, se prepara el handoff de inmediato.
- **Context anxiety**: cerca del límite, el agente se apura y se salta la verificación. Depende del modelo.
- **Sesión 0 = solo inicializar**: comando de arranque y de verificación, un test de ejemplo pasando, archivo raíz,
  feature list, progreso y commit. Nada de código de negocio.
- **Protocolo de arranque**, en orden: `pwd` → progreso → feature_list → `git log --oneline -5` → `init.sh` → smoke
  o e2e → **si la base está rota, se arregla primero** → una sola feature hasta verificarla o declararla bloqueada.
- **Clean state al salir**: build y tests pasan, progreso y feature list actualizados, sin debug ni temporales, el
  arranque estándar funciona. **Sesión completa = tarea verificada + clean state.**
- **"Limpiar después" equivale a nunca.** Limpieza inmediata en cada sesión y un barrido periódico, idempotente.

## Alcance [L07, L08]
- **Overreach y under-finish se alimentan entre sí.** Remedio: **WIP = 1**, una feature activa, y no se abre la
  siguiente hasta que la actual pase el e2e. Nada de "ya que estoy, refactorizo".
- **Feature list = primitivo, no memo.** Cada ítem es una tripleta (comportamiento, comando de verificación,
  estado: `not_started → active → passing | blocked`). Solo la verificación cambia el estado a `passing`.
- **Granularidad**: que quepa en una sesión. "Implementar el carrito" es demasiado grande; "crear el campo name" es
  demasiado chico.
- **VCR** (tareas verificadas ÷ tareas activadas): si es menor que 1, no se activa nada nuevo.

## Verificación [L09, L10, L11]
- **Los agentes se sobreestiman y se autoevalúan de más.** "El código se ve bien" no equivale a "funciona". Solución:
  **separar quien hace de quien juzga** (un checker con contexto fresco y escéptico).
- **Tres capas, sin saltos**: estática → runtime (tests, arranque) → sistema (E2E). Un cambio que cruza componentes
  no está completo sin E2E. Los unit tests con mocks no ven defectos de frontera: rutas, propagación de estado,
  recursos, entorno.
- **Prioridad**: corrección funcional → rendimiento → estilo.
- **Mensajes de error para agentes**: qué falló + por qué + cómo arreglarlo (incluyendo el archivo destino).
- **Feedback de review repetido → regla ejecutable** (lint, hook o test). No se re-explica en el chat.
- **Observabilidad en dos capas**:
  - *Runtime*: logs estructurados con correlation id; las salidas vacías ("0 results") delatan fallos silenciosos.
  - *Proceso*: sprint contract y rúbrica con evidencia.
  
  El rechazo vago ("no se siente bien") no sirve.
- **El evaluador se autoconvence de aprobar.** Hay que calibrarlo contra el juicio humano en 3 a 5 rondas, volviendo
  pass/fail los criterios donde diverge. [R templates]
- **Prohibido debilitar tests o reescribir la feature list para ocultar trabajo pendiente.** Tampoco se cambian en
  silencio las reglas de verificación. [R CLAUDE.md, AGENTS.md]

## Loops [L13, P07]
- **Pasar de escribir prompts a diseñar loops.** El humano define objetivo y condición de parada antes, revisa
  después y ajusta las reglas.
- **`/goal` = objetivo + método de verificación + condición de parada.** Es para trabajo con final.
- **`/loop`** es para vigilancia sin final. Prueba rápida: "¿tiene final? Sí → `/goal`; no → `/loop`". Error típico:
  `/loop 10m "seguí implementando X"`.
- **Tipos de loop**:
  - Por turnos (chat).
  - Por objetivo (`/goal`).
  - Por tiempo (`/loop`, tareas programadas).
  - Por evento (webhooks de GitHub, disparadores de API).
- **Seis primitivos**:
  - Automatizaciones (el latido).
  - Worktrees.
  - Skills, que pagan la "deuda de intención".
  - Conectores (MCP).
  - Subagentes (Explorer → Implementer → Verifier).
  - Estado externo.
- **Cuatro costos silenciosos**:
  - Deuda de verificación.
  - Comprensión que se pudre: hay que leer los diffs importantes.
  - Rendición cognitiva: usar el loop para no pensar.
  - Explosión de tokens.
- **Madurez**: L1 `/goal` → L2 tarea programada → L3 maker/checker + worktree → L4 autoalimentado → L5 flota.
  Empezar en L1 y medir antes la línea base manual. [P07]
- **Metodología en vez de tarea** (autoresearch): un `program.md`, lo intocable fijo, presupuesto fijo, una métrica,
  y solo se conservan las mejoras verificadas.

## Grafos [L14, P08]
- **Un loop crece hasta volverse grafo** cuando necesita especialización, paralelismo, estado compartido,
  verificación y recuperación.
- **Partes del grafo**: nodos, aristas (incluye rollback), estado compartido y reglas de ruteo. Verify tiene
  **contexto fresco**.
- **Antes de dibujarlo**, responder:
  - ¿Qué loop alimenta a cuál?
  - ¿Quién es dueño de los objetivos?
  - ¿Quién puede vetar o revertir?
  - ¿Qué métricas quedan congeladas?
- **Anclas contra Goodhart**: verdad terreno y chequeo humano muestral.
- **Usar grafo solo si se cumplen al menos 3 de 5**: paralelizable, ramas o rollback, estado intermedio valioso,
  "hecho" verificable por nodo, beneficio de coordinación mayor que su costo.
- **Orchestration tax**: la revisión humana es serial y es el techo. Limitar los agentes en paralelo a lo que se
  puede revisar.

## Medir y simplificar [L02, L12, P01, P06]
- **A/B del harness**: mismo prompt, directorios aislados (no ramas), sin tocar a mano. Métricas:
  - Completitud.
  - Tiempo al primer éxito.
  - Reintentos.
  - Ítems faltantes al declarar "hecho".
  - Parada prematura.
- **Ablación periódica**: quitar un componente, correr el benchmark y comparar. Si no degrada, se queda fuera. Cada
  regla codifica una suposición sobre lo que el modelo no puede hacer, y esas suposiciones caducan.

## Correspondencia con Claude Code
| Idea del curso | Herramienta en Claude Code |
|---|---|
| archivo raíz como mapa | `CLAUDE.md` corto + `.claude/rules/` con `paths:` + skills |
| clock in / clock out | sección en CLAUDE.md, o hook `SessionStart` que inyecte PROGRESS |
| sesión 0 | prompt T3 en una sesión aparte; luego `/clear` |
| feature gating | hook `Stop` que corra la verificación (exit 2); `/goal` |
| checker independiente | subagente de solo lectura, `/code-review`, segunda sesión |
| WIP = 1 y alcance | T1 con "No tocar"; reglas `deny` para lo que nunca se toca |
| loops | `/goal`, `/loop`, `/schedule`, channels, `claude -p` |
| paralelismo | worktrees (`claude -w`), `isolation: worktree`, `/batch`, dynamic workflows |
| estado externo | PROGRESS.md, DECISIONS.md, feature_list.json, auto memory |
