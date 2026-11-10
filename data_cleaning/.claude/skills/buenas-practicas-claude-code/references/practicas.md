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
  - Hooks `command`/`http` (con `onFailure: "block"` si también deben fallar cerrados).
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
    [plugin-evals, whats-new w36/w37]
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
     `/security-review`.
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
- **Dónde vive cada regla**:
  - `~/.claude/settings.json` y `.claude/settings.local.json`: solo para el usuario.
  - `.claude/settings.json`: equipo, va en git. Su `deny` aplica de inmediato; su `allow` y sus hooks esperan al
    diálogo de confianza.
- `permissions.denyInsteadOfPrompting`: si una llamada iba a quedar esperando un prompt de permiso, se deniega y el
  turno sigue. Sirve en terminal, subagentes y teammates para corridas sin supervisión. (fuente:
  https://code.claude.com/docs/en/changelog.md v2.1.319, 2026-11-06)
  - Managed settings: para la organización, no se pueden sobrescribir.

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
  - Fable 5.1 con `/model fable`.
- **Auto mode**:
  - Bloquea `curl|bash`, deploys y migraciones a producción, force push sobre trabajo ajeno, envío de datos sensibles
    afuera y acciones inducidas por contenido leído.
  - Se pausa tras 3 bloqueos seguidos o 20 en total.
  - Se ajusta con `autoMode.environment`/`allow`/`soft_deny`, **siempre con `"$defaults"`** y solo en
    `~/.claude/settings.json` (el clasificador ignora la configuración de proyecto). `/auto-mode-setup` redacta el
    environment.
  - Un "don't push until I've reviewed" dicho en el chat cuenta como señal, pero puede perderse al compactar. Lo que
    importa va en `deny`.
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
- **Agent SDK**:
  - `query()` con `allowedTools`, `permissionMode`, `maxTurns`, `maxBudgetUsd`.
  - Hooks y `canUseTool` para el control humano.
  - `settingSources: []` para reproducibilidad en CI.
  - `allowedTools` **no** restringe si el modo es bypass.
  - Un producto propio se autentica con API key, no con OAuth de suscripción. [agent-sdk_*, legal-and-compliance]
- **Despliegue seguro**: tener en cuenta la "lethal trifecta" (datos privados + contenido no confiable + canal de
  exfiltración), contenedor endurecido y red cerrada con proxy. [agent-sdk_secure-deployment]

## Obsoletas (no recomendar) [best-practices]
| Consejo viejo | Por qué ya no |
|---|---|
| Gestionar el contexto de forma agresiva | ventana de 1M y compactación automática; `/clear` sigue sirviendo por foco y costo |
| IMPORTANT o MAYÚSCULAS | los modelos actuales siguen texto plano; el énfasis hace que se sobre-aplique la regla. Si es rígida, va en un hook |
| Subagentes "para proteger el contexto" o "para una mejor respuesta" | no mejoran la respuesta; solo aportan paralelismo, revisión ajena y menos ruido |
| "think hard", "be thorough" | el control es effort; `ultrathink` vale para un turno |
| "keep going", "don't be lazy" | causan sobre-trabajo; usar una comprobación, `/goal` o un hook `Stop`; "continue" si se corta |
| Describir arquitectura o layout en CLAUDE.md | Claude lee el repo |
