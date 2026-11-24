# Prácticas de Claude Code

Base: lectura completa de code.claude.com/docs/en a **v2.1.318** (2026-11-06). Salvo otra indicación, la fuente es
`https://code.claude.com/docs/en/<página>.md`; se nombra la página entre corchetes. El refinado automático agrega
cambios con `(fuente: URL, fecha)` y los registra en `REFINAMIENTOS.md`.

## 1. Criterio rector: guía vs garantía [best-practices]
- **Guía (Claude decide)**:
  - Prompt, `CLAUDE.md`, skills, output style.
  - Clasificador de auto mode.
  - `/goal`, `/code-review`.
  - Effort.
- **Garantía (el harness impone)**:
  - Hooks `command`/`http`/`mcp_tool` (con `onFailure: "block"` si también deben fallar cerrados; en `mcp_tool`
    desde v2.1.328). (fuente: https://code.claude.com/docs/en/changelog.md v2.1.328, 2026-11-23)
  - Reglas `deny`.
  - Sandbox en modo estricto.
  - Managed settings.
  - `--max-turns` y `--max-budget-usd` (con `-p`).
  - Tests y CI.
  - Protección de rama.
- Los hooks `prompt`/`agent` consultan a otro modelo, así que **no** son deterministas.
- Si una línea de CLAUDE.md se ignora pese a ponerle énfasis, pasarla a un hook. Si un hook solo expresa una
  preferencia, borrarlo. Mantener pocas garantías: con unas 40, la mayoría son preferencias.

## 2. Diagnóstico: los cuatro fallos [best-practices]
| Síntoma | Causa | Remedio |
|---|---|---|
| Construyó otra cosa, o redescubre lo mismo en cada sesión | le falta información que no está en el repo | §3 |
| Dijo "listo" y no lo estaba | no tenía con qué comprobar | §5 |
| Hizo algo prohibido o se saltó un paso obligatorio | era una regla sin excepción escrita como guía | §6 |
| Le costó demasiado (tiempo, tokens, prompts) | un default no encaja | §8 (mirar `/usage`) |

## 3. Decirle lo que no puede ver
- **Antes de escribir algo para Claude**, dos preguntas: ¿podría encontrarlo leyendo el código? ¿Iría a buscarlo? Si
  ambas son sí, no se escribe. [best-practices]
- **Prompt específico**: archivo + síntoma + qué significa "arreglado". Si hay dos enfoques válidos y uno importa,
  decir cuál.
  - Malo: "fix the login bug".
  - Bueno: "login fails after session timeout; look at token refresh in src/auth/, write a failing test that
    reproduces it, then fix it".
- **Entregar, no describir**: `@ruta`, una imagen pegada, `cat log | claude -p "..."`.
- **Alcance**: "be ambitious: empty/error states, ..." cuando se quiere la versión completa. Claude tiende al mínimo.
- **Profundidad**: el control es `/effort`, no "think step by step" ni "be thorough". `ultrathink` sirve para un solo
  turno. [model-config]
- **Si no está claro qué se quiere**: "Interview me until you could write the spec, then write it to SPEC.md". Luego
  se construye en una **sesión nueva** a partir de la spec.
- **Herramientas externas**: si tienen CLI (`gh`), basta con que esté instalada (y `--help` si Claude no la
  conoce). Si no la tienen, MCP (`claude mcp add --transport http <n> <url>`). Desactivar en `/mcp` los servidores
  que no se usan. Para lenguajes tipados, un plugin de code intelligence (LSP). [mcp, plugins/code-intelligence]
  Si el servidor lleva un token, `claude mcp add-json <n> -` lee el JSON por stdin y el token no queda en la línea
  de comandos ni en el historial. (fuente: https://code.claude.com/docs/en/changelog.md v2.1.327, 2026-11-23)

## 4. Contexto persistente [memory, features-overview, skills]
- **CLAUDE.md**:
  - Menos de 200 líneas.
  - Contenido: comandos exactos (test, typecheck, lint, cómo correr un solo test), el código que engaña, las
    decisiones que no están en el repo y lo que hubo que corregir dos veces.
  - Nada de arquitectura ni de estructura de archivos.
  - `/init` lo genera y luego se recorta. `/doctor` sugiere recortes, `/doctor prompt-audit` encuentra instrucciones
    obsoletas o contradictorias, `/context all` verifica qué se cargó.
  - Lo personal va en `CLAUDE.local.md` (en `.gitignore`).
  - Una sección "Compact Instructions" decide qué sobrevive a la compactación.
  - Es aditivo: carga desde el directorio de trabajo hacia arriba, y los subdirectorios cuando Claude entra en ellos.
    Claude puede leer `AGENTS.md`.
- **`.claude/rules/*.md`** con `paths:` (globs): solo carga cuando Claude toca archivos que coinciden. Sirve para
  guías por directorio o lenguaje.
- **Skills** (`.claude/skills/<n>/SKILL.md`):
  - Para procedimientos y referencias de uso ocasional. Solo la `description` está siempre en contexto.
  - **`description`**: el caso de uso principal va primero. `description` + `when_to_use` se truncan a 1.536
    caracteres. Si es vaga, Claude no la dispara.
  - Campos útiles: `disable-model-invocation: true` (efectos secundarios: solo `/nombre`), `user-invocable: false`
    (conocimiento de fondo), `allowed-tools`, `disallowed-tools`, `model`, `effort`, `context: fork` + `agent`
    (aislar), `paths`, `hooks`, `arguments` / `argument-hint`, `shell: powershell`.
  - `` !`cmd` `` inyecta la salida de un comando. `@ruta` importa un archivo.
  - Lo importante arriba en SKILL.md. Las referencias largas, en archivos aparte.
  - Medir con `claude plugin eval` (baseline sin la skill, delta) y `/skill-doctor` (costo y uso).
    [plugin-evals; las páginas whats-new salieron del índice de docs el 2026-11-23, `claude plugin eval` sigue en el
    changelog v2.1.327]
- **Output style**: define cómo responde Claude (rol, tono, longitud). Solo uno activo. [output-styles]
- **Auto memory**: `MEMORY.md`, del que se cargan las primeras 200 líneas o 25 KB. [memory]
- **Cuándo agregar cada cosa** [features-overview]:
  - Error repetido dos veces → CLAUDE.md.
  - Mismo formato pedido una y otra vez → output style.
  - Mismo prompt para arrancar una tarea → skill invocable.
  - Playbook pegado por tercera vez → skill.
  - Datos que se copian de otro sistema → MCP.
  - Búsquedas de símbolos → LSP.
  - Salida ruidosa → subagente.
  - "Siempre, sin pedirlo" → hook.
  - Otro repo necesita lo mismo → plugin.
- **Precedencia cuando hay varios niveles**:
  - Skills: managed > user > project.
  - Subagentes: managed > flag CLI > project > user > plugin.
  - MCP: local > project > user.
  - Hooks: se suman.

## 5. Darle una comprobación [best-practices, goal, hooks, code-review-local]
- **Qué sirve como comprobación**: cualquier cosa que diga pasa o falla y que Claude pueda leer. Un test, el código
  de salida de un build, un linter, un diff contra un fixture, una captura de navegador contra el mockup. El comando
  que la corre es la línea más valiosa de CLAUDE.md.
- **Niveles, de menos a más estricto**:
  1. En el prompt: "run X and keep going until it passes".
  2. `/goal <condición verificable>`: un modelo aparte la evalúa en cada turno. Esencial en corridas largas.
  3. Hook `Stop`: el comando sale con código 2 (stderr vuelve a Claude). Ejemplo:
     `"Stop":[{"hooks":[{"type":"command","command":"pnpm tsc --noEmit 1>&2 || exit 2"}]}]`. Puede bloquear como
     máximo 8 veces seguidas (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`).
  4. Revisor ajeno: `/code-review [low..max]`, un subagente nuevo sobre el diff. También `/ultrareview` y
     `/security-review`. Desde v2.1.328-329, `/code-review` sin objetivo revisa toda la rama contra la rama por
     defecto, reporta solo bugs y violaciones de CLAUDE.md (marcados Important, Pre-existing o Nit) y cierra con un
     arreglo sugerido; las limpiezas de reuso, simplificación y eficiencia van con `/simplify`. `/security-review`
     ahora pide permiso antes de correr. (fuente: https://code.claude.com/docs/en/changelog.md v2.1.323/v2.1.328/v2.1.329,
     2026-11-23)
  5. PR con watch: `/ship` (cambio terminado: commit, push, PR, `/code-review` y luego atiende checks, conflictos y
     comentarios) o `/steward` (PR propio ya abierto, sin revisión previa). Requiere v2.1.330+, `gh` 2.63+ y git
     2.38+. Antes de `/ship`, `git status` y sacar lo que no va: puede commitear **todo** lo no commiteado, solo
     detecta secretos por nombre de archivo y una regla `deny` no saca un archivo del commit. Sin supervisión, auto
     mode; en `bypassPermissions` no arranca el watch. El merge lo hace la persona. (fuente:
     https://code.claude.com/docs/en/ship-command.md, 2026-11-23)
- **Evidencia**: pedir siempre el comando ejecutado y su salida, o la captura. `/verify` construye y ejecuta la app.
- **Revisión contra la spec**: "use a subagent to review the diff against SPEC.md ... report gaps that affect
  correctness and **skip style**". Sin el "skip style", el revisor sobre-señala.

## 6. Imponer lo que no admite excepción [best-practices, permissions, hooks-guide, sandboxing]
- **Hooks**:
  - `PostToolUse` con matcher `Edit|Write` para formatear.
  - `PreToolUse` que sale con 2 para bloquear rutas.
  - `SessionStart` para inyectar contexto (también tras compactar).
  - Claude puede escribir el hook ("write a hook that blocks edits to migrations/"). Revisarlo con `/hooks`.
- **Permisos** en `settings.json`:
  `{"permissions":{"allow":["Bash(pnpm tsc --noEmit)"],"ask":["Bash(git push *)"],"deny":["Read(./.env)","Read(./secrets/**)"]}}`.
  - `deny` aplica en **todos** los modos, incluido bypass.
  - Orden de evaluación: hooks `PreToolUse` → deny → ask → allow → modo o clasificador.
- **Límites de las reglas**:
  - `Read(./.env)` atrapa `cat .env`, pero no un script que abra el archivo.
  - Un deny de `WebFetch(domain:)` no frena `curl` sin sandbox.
  - Para seguridad, usar **reglas y sandbox** juntos.
- **Sandbox** (`/sandbox`):
  - Aísla la red y el sistema de archivos de Bash a nivel de sistema operativo (macOS, Linux, WSL2).
  - El modo estricto (pestaña Overrides) quita el reintento fuera del sandbox.
  - `bypassPermissions` y `--dangerously-skip-permissions` solo dentro de un contenedor, VM o `srt`, nunca como root.
    [sandbox-environments]
  - Desde v2.1.325, los comandos Bash en sandbox siguen el flujo normal de permisos (antes corrían sin prompt). Para
    volver a correrlos sin prompt: `sandbox.autoAllowBashIfSandboxed: true` (si el sandbox lo prende managed, en la
    fuente managed de mayor rango). El sandbox ya no escribe en `.claude` (settings, skills, agents, hooks) de los
    directorios agregados ni en carpetas sensibles del home. (fuente: https://code.claude.com/docs/en/changelog.md
    v2.1.325/v2.1.326, 2026-11-23)
- **Dónde vive cada regla**:
  - `~/.claude/settings.json` y `.claude/settings.local.json`: solo para el usuario.
  - `.claude/settings.json`: equipo, va en git. Su `deny` aplica de inmediato; su `allow` y sus hooks esperan al
    diálogo de confianza.
- `permissions.denyInsteadOfPrompting`: si una llamada iba a quedar esperando un prompt de permiso, se deniega y el
  turno sigue. Sirve en terminal, subagentes y teammates para corridas sin supervisión. (fuente:
  https://code.claude.com/docs/en/changelog.md v2.1.319, 2026-11-06)
  - Managed settings: para la organización, no se pueden sobrescribir.
- "Don't ask again" sobre una regla que parece contener un secreto, o que iría a un `settings.local.json` trackeado
  por git, dura solo la sesión y no se guarda. Igual, nunca escribir secretos en reglas. (fuente:
  https://code.claude.com/docs/en/changelog.md v2.1.323, 2026-11-23)
- **Code Mode** (experimental, opt-in con `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1`, solo terminal, v2.1.323+): Claude
  escribe JavaScript que hace varias llamadas de herramientas en un paso. Útil para cambios repetidos en muchos
  archivos, búsquedas que hay que filtrar o comandos independientes en paralelo. Qué cambia en las garantías:
  - Cada llamada sigue pasando por `deny`/`ask` y hooks `PreToolUse` con su nombre normal; en auto mode el
    clasificador revisa el **código**, no cada llamada, y no ve valores calculados en ejecución. Lo que hay que
    controlar sí o sí va en reglas o hooks.
  - Un hook que filtra comandos shell debe revisar cada parte del comando (puede llegar como `cd 'app' && git push`).
    Para revisar el código, hook `PreToolUse` con matcher `REPL` (`tool_input.code`); para redactar la salida,
    `PostToolUse` sobre `REPL` con `updatedToolOutput` (`UserPromptSubmit` ya no recibe esa salida desde v2.1.328).
  - Un hook que falla deja pasar la llamada por defecto: en hooks de guarda, `"onFailure": "block"`.
  - El sandbox cubre solo los comandos shell; el JS y sus llamadas de archivos, web y MCP corren fuera. Para aislar
    todo, contenedor o VM; sandbox estricto para que no se reintente fuera.
  (fuente: https://code.claude.com/docs/en/code-mode.md, 2026-11-23)

## 7. Conducir la sesión [best-practices, checkpointing, interactive-mode, sessions]
- **Mirar el primer minuto**:
  - `Esc` en cuanto se desvía; escribir y pulsar Enter deja un mensaje en cola que Claude lee en el mismo turno.
  - Tras **dos correcciones fallidas**, `/clear` y un prompt mejor que incorpore lo aprendido.
- **Rewind**: `/rewind` o `Esc Esc` restaura código, conversación o ambos, y puede resumir desde un punto. Los
  checkpoints **no** cubren cambios hechos por Bash ni por subagentes: complementan git, no lo sustituyen.
- **Otros controles**:
  - `/btw`: pregunta lateral que no queda en el historial.
  - `/rename x` y luego `claude --resume x`; `claude --continue`.
  - `/branch` o `--fork-session` para bifurcar.
  - `/diff` para revisar antes del commit.
- **Plan mode** (`Shift+Tab`, `/plan`): explora y propone sin editar. `Ctrl+G` edita el plan. Aprobar el plan y
  ejecutar en auto o accept edits.

## 8. Defaults y economía [best-practices, model-config, costs, permission-modes, sub-agents]
- **Defaults actuales**:
  - Auto mode en terminal y VS Code (v2.1.283+).
  - Opus 5.5 con effort medium.
  - Ventana de 1M con compactación automática.
  - Subagentes en segundo plano y fork mode activo.
- **Effort**:
  - high/xhigh: bugs en código ajeno, tests intermitentes, cambios de esquema.
  - low: iterar rápido.
  - max: solo para problemas difíciles sin supervisión (en tareas comunes sobre-piensa).
- **Modelo**:
  - Sonnet en tareas rutinarias.
  - Haiku en subagentes simples (`model: haiku`).
  - Fable 5.2 (`claude-fable-5-2`, 1M de contexto) con `/model fable`; es el Fable por defecto desde v2.1.321 y las
    selecciones guardadas de 5.1 migran a `fable`. (fuente: https://code.claude.com/docs/en/changelog.md v2.1.321,
    2026-11-23)
- **Auto mode**:
  - Bloquea `curl|bash`, deploys y migraciones a producción, force push sobre trabajo ajeno, envío de datos sensibles
    afuera y acciones inducidas por contenido leído.
  - Se pausa tras 3 bloqueos seguidos o 20 en total.
  - Se ajusta con `autoMode.environment`/`allow`/`soft_deny`, **siempre con `"$defaults"`** y solo en
    `~/.claude/settings.json` (el clasificador ignora la configuración de proyecto). `/auto-mode-setup` redacta el
    environment.
  - Un "don't push until I've reviewed" dicho en el chat cuenta como señal, pero puede perderse al compactar. Lo que
    importa va en `deny`.
  - Auto mode ignora las reglas `allow` comodín que ejecutan cualquier paquete o programa (`Bash(pnpm dlx *)`,
    `/usr/bin/npm run:*`, reglas sin programa o que empiezan con `$HOME`): esas las decide el clasificador. No
    contar con ellas para desbloquear una corrida. (fuente: https://code.claude.com/docs/en/changelog.md
    v2.1.326/v2.1.327, 2026-11-23)
- **Modo manual con muchos prompts**: `/fewer-permission-prompts` crea un allowlist de solo lectura.
- **Costo**:
  - `/usage` desglosa por skill, subagente, plugin y MCP.
  - `/clear` entre tareas sin relación (`/clear nombre` guarda la sesión).
  - `/compact <foco>`.
  - Vigilar `/loop`, `/goal` y los subagentes, que consumen aunque el usuario no escriba.
  - Caché: unos 60 minutos con suscripción, 5 con API key o proveedores cloud; los subagentes usan 5.
- **Subagentes**:
  - Sirven para paralelismo, para sacar ruido de la conversación, como revisor independiente o para tener menos
    herramientas.
  - **No** dan una respuesta más inteligente, cuestan tokens y a veces tiempo.
  - Revisor de solo lectura: `.claude/agents/reviewer.md` con `tools: Read, Grep, Glob`.
  - Frontmatter útil: `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `skills` (precarga), `memory`,
    `isolation: worktree`, `effort`, `omitClaudeMd`, `initialPrompt`.

## 9. Autonomía sin supervisión [best-practices, headless, scheduled-tasks, routines, agents, worktrees]
- **Cinco preguntas antes de soltarlo**:
  1. ¿Qué es "hecho"? `/goal`, SPEC o un test rojo.
  2. ¿Cómo se comprueba? Suite, hook `Stop` o revisor.
  3. ¿Qué puede tocar? Permisos, `dontAsk`, sandbox, worktree, una sola rama.
  4. ¿Qué lo detiene? `--max-turns`, `--max-budget-usd`, spend limit.
  5. ¿Adónde va el resultado y quién lo firma? PR o resumen, y un humano aprueba.
- **Script**: `claude --bare -p "... Reply OK or FAIL." --allowedTools "Read,Edit,Bash(git add *)" --permission-mode dontAsk --max-turns 20`.
  - `--bare` ignora hooks, skills, plugins, MCP y CLAUDE.md, y se autentica con API key. No sirve si la corrida
    necesita hooks.
  - Formatos: `--output-format json`, o `stream-json` con `--verbose`; `--json-schema` para salida validable.
  - Probar con 3 casos antes de lanzar el lote.
  - En CI, revisar el código de salida: desde v2.1.319, `claude -p` en auto mode sale con 1 (antes salía con 0) si se
    rechazaron acciones por no haber chequeo de seguridad disponible. Detrás de un LLM gateway, o con telemetría o
    feature flags apagados, auto mode pregunta o deniega lo que el servidor no puede revisar
    (`CLAUDE_CODE_AUTO_MODE_SERVER`). (fuente: changelog v2.1.319, 2026-11-06)
- **Disparadores**:
  - `/loop 15m <prompt>`: dentro de la sesión. No dejarlo corriendo en una conversación larga. Desde v2.1.319 el
    `/loop` autorregulado termina cuando un turno acaba sin reprogramarse (antes dejaba una alarma de respaldo;
    `CLAUDE_CODE_LOOP_KEEPALIVE=1` vuelve al comportamiento anterior). En sesiones cloud el timer muere con el
    contenedor. (fuente: changelog v2.1.319, 2026-11-06)
  - `/schedule`: tareas programadas en la nube, con disparadores de GitHub o de API; requiere login de claude.ai.
    Proteger `main` con una branch rule y vigilar las primeras corridas.
  - Desde v2.1.330, `/loop` y las tareas programadas recurrentes duran hasta 30 días (antes 7) mientras la sesión
    siga abierta: ponerles condición de fin y revisarlas en `/tasks`, que ahora las lista y permite pararlas. Desde
    v2.1.325 preguntan antes de correr una skill que declara `allowed-tools` o hooks; para que corra sin supervisión,
    `Skill(nombre)` en `permissions.allow`. Las tareas guardadas por versiones anteriores pueden necesitar
    reprogramarse (v2.1.329). (fuente: https://code.claude.com/docs/en/changelog.md v2.1.325/v2.1.329/v2.1.330,
    2026-11-23)
  - Tareas programadas de Desktop.
  - Channels: eventos empujados a la sesión.
- **Paralelismo**:
  - Worktrees (`claude -w nombre`, `.worktreeinclude` solo para archivos pequeños).
  - Agent view (`claude agents`, `claude --bg`).
  - Dynamic workflows: para más de un puñado de agentes o hallazgos cruzados.
  - Agent teams: experimental.
  - `/batch`: divide en 5 a 30 unidades, cada una con su worktree y su PR.
  - Cross-session messaging.
  - Una segunda sesión es el revisor independiente más barato.
- **CI**: GitHub Actions (`/install-github-app`, `@claude`) o GitLab, con OIDC, permisos mínimos y `--max-turns`.
  Code Review gestionado con `REVIEW.md`. [github-actions, code-review]
- **Claude Ship** (Team/Enterprise, beta): Code Review + PR Steward (empuja fixes a checks, conflictos y comentarios
  sin preguntar; no aprueba ni mergea; se para con `@claude stop` o quitando el label `claude-pr-steward-watching`)
  + Claude Approvals (política en `.claude/approvals.yml`, dice cuántas personas aprueban cada ruta y dónde puede
  aprobar Claude). Prácticas: empezar Approvals en modo `observe` hasta que coincida con los revisores; exigir
  reviews con branch rules y dejar la app de Claude **fuera** de la lista de bypass; fijar el origen del check
  requerido a la app de Claude; poner límite de gasto (observe también se cobra). Steward lee las instrucciones
  desde la rama por defecto. (fuente: https://code.claude.com/docs/en/claude-ship.md,
  https://code.claude.com/docs/en/pr-steward-security.md, https://code.claude.com/docs/en/approvals-setup.md,
  https://claude.com/resources/articles/introducing-claude-ship, 2026-11-23)
- **Compartir sesiones** (cloud o Remote Control): quien recibe el link ve prompts, archivos leídos, salidas de
  comandos, resultados de conectores y **credenciales** que hayan aparecido; en Remote Control, también archivos
  fuera de la carpeta y páginas de Chrome. Revisar la sesión antes y dejarla Private si tiene algo sensible.
  (fuente: https://code.claude.com/docs/en/share-sessions.md, 2026-11-23)
- **Agent SDK**:
  - `query()` con `allowedTools`, `permissionMode`, `maxTurns`, `maxBudgetUsd`.
  - Hooks y `canUseTool` para el control humano.
  - `settingSources: []` para reproducibilidad en CI.
  - `allowedTools` **no** restringe si el modo es bypass.
  - Un producto propio se autentica con API key, no con OAuth de suscripción. [agent-sdk_*, legal-and-compliance]
- **Despliegue seguro**: tener en cuenta la "lethal trifecta" (datos privados + contenido no confiable + canal de
  exfiltración), contenedor endurecido y red cerrada con proxy. [agent-sdk_secure-deployment]
  "Least agency": sacar los secretos permanentes del entorno del agente (OIDC o workload identity con token corto
  por job), hooks que bloqueen commits con secretos más secret scanning al push, y chequear las llamadas contra
  política fuera del modelo. (fuente: https://claude.com/resources/articles/enterprise-guide-to-securing-coding-agents,
  2026-11-23)

## Obsoletas (no recomendar) [best-practices]
| Consejo viejo | Por qué ya no |
|---|---|
| Gestionar el contexto de forma agresiva | ventana de 1M y compactación automática; `/clear` sigue sirviendo por foco y costo |
| IMPORTANT o MAYÚSCULAS | los modelos actuales siguen texto plano; el énfasis hace que se sobre-aplique la regla. Si es rígida, va en un hook |
| Subagentes "para proteger el contexto" o "para una mejor respuesta" | no mejoran la respuesta; solo aportan paralelismo, revisión ajena y menos ruido |
| "think hard", "be thorough" | el control es effort; `ultrathink` vale para un turno |
| "keep going", "don't be lazy" | causan sobre-trabajo; usar una comprobación, `/goal` o un hook `Stop`; "continue" si se corta |
| Describir arquitectura o layout en CLAUDE.md | Claude lee el repo |
| "Fable 5.1 con `/model fable`" | desde v2.1.321 `fable` es Fable 5.2 (fuente: https://code.claude.com/docs/en/changelog.md v2.1.321, 2026-11-23) |
| Contar con que el Bash en sandbox corre sin prompts | desde v2.1.325 sigue el flujo normal de permisos; hace falta `sandbox.autoAllowBashIfSandboxed: true` (fuente: https://code.claude.com/docs/en/changelog.md v2.1.325, 2026-11-23) |
| `/code-review` para limpiezas de estilo o reuso | desde v2.1.328 solo reporta bugs y violaciones de CLAUDE.md; las limpiezas van con `/simplify` (fuente: https://code.claude.com/docs/en/changelog.md v2.1.328, 2026-11-23) |
