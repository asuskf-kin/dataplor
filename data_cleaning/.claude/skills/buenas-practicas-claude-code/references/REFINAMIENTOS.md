# Registro de refinamientos

Una entrada por revisión con cambios: fecha · versión vista → nueva · qué cambió en `practicas.md` · fuente.

- 2026-11-06 · base v2.1.318 · versión inicial a partir de la lectura completa de las 228 páginas de docs
  (`referencia/claude-code-docs/`).
- 2026-11-06 · v2.1.318 → v2.1.319 · §6: `permissions.denyInsteadOfPrompting`; §9: `/loop` autorregulado termina sin
  reprogramarse (`CLAUDE_CODE_LOOP_KEEPALIVE`) y `claude -p` en auto mode sale con 1 cuando no hay chequeo de
  seguridad. Lo demás (gateway, VS Code, fixes) no cambia ninguna práctica. Fuente:
  https://code.claude.com/docs/en/changelog.md
- 2026-11-23 · v2.1.319 → v2.1.331 · §1: `onFailure: "block"` también en hooks `mcp_tool`. §3: `claude mcp add-json
  <n> -` para tokens fuera de la línea de comandos. §4: las páginas whats-new salieron del índice de docs (se ajustó
  la cita). §5: `/code-review` revisa la rama entera y solo bugs/CLAUDE.md (limpiezas con `/simplify`); nuevo nivel
  `/ship` y `/steward`. §6: Bash en sandbox ya pide permiso (`sandbox.autoAllowBashIfSandboxed`); "don't ask again"
  no guarda reglas con secretos; Code Mode (experimental) y cómo cambian reglas, hooks y sandbox. §8: Fable 5.2 por
  defecto; auto mode ignora `allow` comodín que ejecutan cualquier paquete. §9: `/loop` y tareas programadas hasta
  30 días, `Skill(nombre)` en allow para corridas sin supervisión; Claude Ship (PR Steward, Approvals en observe,
  app fuera del bypass); compartir sesiones expone credenciales; "least agency". Obsoletas: Fable 5.1, Bash en
  sandbox sin prompt, `/code-review` para limpiezas. Lo demás (VS Code, self-hosted runner, gateway, fixes) no cambia
  prácticas. Posts ignorados por no tratar de Claude Code/agentes/prompting: claude-tag-guide-for-startups, kpmg,
  linked-billing, zero-data-retention, building-strong-safety-evaluations; self-hosted-claude-managed-agents e
  interactive-connectors-full-tool no leídos (producto API/conectores, no prácticas de Claude Code). Fuentes:
  https://code.claude.com/docs/en/changelog.md, code-mode.md, ship-command.md, claude-ship.md, pr-steward-security.md,
  approvals-setup.md, share-sessions.md, https://claude.com/resources/articles/introducing-claude-ship,
  https://claude.com/resources/articles/enterprise-guide-to-securing-coding-agents
