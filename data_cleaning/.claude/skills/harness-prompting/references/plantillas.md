# Plantillas para prompts y archivos de harness

Adaptadas de Learn Harness Engineering (walkinglabs). La fuente de cada una está entre corchetes: `L07` = lección 7,
`P` = proyectos, `R` = recursos. Ruta local: `referencia/harness-engineering/paginas/`. Se rellenan; no se copian
vacías.

## T1. Tarea puntual: una feature por prompt [L01, L07, L08]
```
Tarea: <una sola feature, tamaño "cabe en una sesión">
Por qué ahora: <motivo / prioridad>
Contexto que no está en el repo: <decisión, restricción, gotcha>
Hecho significa (comportamiento + comando):
- <comportamiento observable> → `<comando que lo verifica>`
- Verificación completa: `<make check | pnpm test && pnpm lint && pnpm tsc --noEmit>`
No tocar: <archivos/módulos/dependencias fuera de alcance>
Al terminar: pega la salida real de la verificación y lista lo que no pudiste verificar.
No refactorices lo adyacente: anótalo como pendiente.
```

## T2. Objetivo autónomo (`/goal` o maker) [L13 goal-template]
```
Goal: <una frase con el estado final>
Acceptance criteria (cada uno con comando):
- `<tests>` pasa completo · `<lint>` 0 errores · `<typecheck>` pasa · cobertura de <módulo> ≥ <N>%
Scope — fair game: <rutas editables> · hands off: <rutas/config/migraciones/deps que no se tocan>
Verificación, en orden: tipos → lint → unit → (e2e si existe); arreglar antes de pasar al siguiente.
Stop: todo pasa | máx <20> turnos | sin progreso 3 rondas (mismo error) | bloqueo que requiere humano.
Cómo trabajar: lee AGENTS.md/CLAUDE.md y feature_list primero; escribe el enfoque antes de tocar código;
verifica tras cada subtarea; si te atascas >2 rondas cambia de enfoque; actualiza el progreso al final de cada ronda.
```
Con Claude Code: `/goal <criterios en una línea>` y, para garantizar, un hook `Stop` con el comando de verificación.

## T3. Primera sesión de un proyecto: solo inicializar [L06]
```
Esta sesión es SOLO de inicialización; no escribas código de negocio.
Entrega: (1) comando canónico de arranque y de verificación (Makefile/init.sh con set -euo pipefail);
(2) framework de tests con ≥1 test de ejemplo pasando; (3) AGENTS.md/CLAUDE.md corto (qué es, cómo se corre,
cómo se verifica, reglas duras); (4) feature_list.json con ≥3 features y su verificación, todas en false;
(5) PROGRESS.md inicial; (6) commit limpio.
Aceptación: setup desde cero OK · test pasa · una sesión nueva responde "cómo correr/cómo testear" solo con el repo.
```

## T4. Feature list (primitivo, no memo) [L08, R templates]
```json
[{"id": "F03", "behavior": "POST /cart/items {product_id, quantity} devuelve 201",
  "verification": "curl -s -o /dev/null -w '%{http_code}' -X POST localhost:3000/api/cart/items ... == 201",
  "state": "not_started", "evidence": ""}]
```
Estados: `not_started → active → passing | blocked`. Solo uno `active`. El agente **no** marca `passing` por su
cuenta: lo marca la verificación. Política de paso [L08 pass-gate]: se ejercitó el flujo, hay evidencia registrada,
no hay error bloqueante en la ruta probada y la app no queda rota.

## T5. Entrada y salida de sesión [L05, L12]
```
## Al iniciar (clock in)
1. Lee PROGRESS.md y DECISIONS.md   2. Corre <check> para confirmar un estado consistente
3. Sigue desde "Next Steps"
## Antes de cerrar (clock out) — Session Exit Checklist
- [ ] Build pasa   - [ ] Tests pasan (incluidos los previos)   - [ ] feature_list/PROGRESS actualizados
- [ ] Sin código de debug, temporales ni TODO sueltos   - [ ] La ruta estándar de arranque funciona   - [ ] Commit
```

## T6. Handoff (antes de /clear, cambio de sesión o fin del día) [L05 session-handoff]
```
## Completado
- ...
## Roto o sin verificar
- ...
## Siguiente mejor paso
- ...
## Decisiones tomadas (qué, por qué, alternativa rechazada)
- ...
```
Prompt: "Antes de cerrar, escribe el handoff en PROGRESS.md con esas 4 secciones, desde la feature list y la salida
real de los tests, no de memoria."

## T7. DECISIONS.md (lo que la compactación pierde) [L05]
```
## AAAA-MM-DD: <decisión>
- Motivo: ...   - Alternativa rechazada: ... (por qué)   - Restricción: ...
```

## T8. Definition of Done por niveles [L09, L10]
```
## Definition of Done
- Feature completa = pasó la verificación end-to-end, no "el código está escrito"
1. Unit  2. Integración  3. E2E (obligatorio si el cambio cruza componentes)
- No se pasa al nivel siguiente si falla el anterior. Saltarse un nivel = no completo.
- Prioridad: corrección funcional → rendimiento → estilo. Sin refactor hasta verificar lo esencial.
```

## T9. Sprint contract (antes de codificar algo con revisión) [L11]
```
# Sprint Contract: <objetivo>
## Scope        - <qué se modifica>
## Done means   - <3-5 comportamientos observables>
## Verification - <tests/e2e/regresión visual>
## Exclusions   - <lo que explícitamente no se hace>
```

## T10. Maker (implementador) [L13 maker-prompt]
```
Eres el Maker. Lee AGENTS.md y los docs relevantes; explica tu plan antes de cambiar nada;
corre la verificación básica (build, lint, unit); si no sabes algo, dilo, no inventes; registra el progreso.
Entrega: archivos modificados · resumen · resultado de la verificación básica · zonas de duda (para el Checker).
```

## T11. Checker (revisor independiente, contexto fresco) [L13 checker-prompt, L09]
```
Eres el Checker. Tu objetivo es encontrar problemas, no elogiar. Lee todos los cambios, contrástalos punto por
punto con <SPEC/contrato/criterios>, corre los comandos completos de verificación y lista cada problema con:
ubicación (archivo:línea), evidencia, severidad (Critical/Medium/Minor) y sugerencia.
Revisa: corrección funcional y casos borde · si los tests prueban algo real · impacto en otras partes
y dependencias nuevas. Omite el estilo salvo que rompa una convención escrita.
Veredicto: Pass | Fail | Minor issues, acceptable. Incluye la salida real de tests, lint y tipos.
```
En Claude Code: subagente con `tools: Read, Grep, Glob, Bash` (o solo lectura) y `/code-review`. No debe heredar el
contexto del Maker.

## T12. Rúbrica del evaluador [L11]
| Dimensión | A | B | C | D |
|---|---|---|---|---|
| Corrección | todos los tests pasan | pasa el flujo principal | parcial | no compila |
| Arquitectura | cumple | desviación menor | desviación obvia | violación grave |
| Tests | principal + bordes | solo principal | esqueleto | ninguno |
Cada puntaje lleva su evidencia (un número medido, un log), nunca "no se siente bien".

## T13. Estado de un loop [L13 loop-state]
```
Loop: <nombre> · Ronda <k>/<N> · Estado: In progress|Completed|Blocked|Failed
Goal: ...
Ronda k: qué hizo el maker · verificación Pass/Fail/Partial · issues · plan próxima ronda · ¿humano? Sí/No
Acumulado: rondas ok/fallidas · issues · intervenciones · archivos tocados
Bloqueos recurrentes: ...
```

## T14. program.md: metodología en vez de tarea (estilo autoresearch) [L13]
```
Objetivo: <métrica única, dirección (menor/mayor es mejor)>
Intocable: <archivos de infraestructura/evaluación fijos>   Editable por el agente: <archivo(s)>
Presupuesto fijo por experimento: <tiempo/recursos> (para que los resultados sean comparables)
Ciclo: leer dirección → ver estado y resultados → hipótesis → cambiar → commit → correr → evaluar
→ si mejora, conservar y registrar en results.tsv; si no, revertir y registrar el fallo → siguiente.
Registro: results.tsv (timestamp, commit, métrica, recursos, descripción).
```

## T15. graph.md (cuando un loop ya no alcanza) [L14]
```
Estado compartido: {requirements (research), code (implement), review pass|fail (verify), attempts (+1, suma)}
Nodos: research (agente) · implement (agente, ≤3 intentos) · verify (agente, CONTEXTO FRESCO) · merge (código)
Aristas: research→implement→verify→merge→end
Ruteo: verify→merge si review==pass · verify→implement si fail · attempts>N → humano
Checkpoint: tras cada paso · pausa antes de merge para aprobación humana
```
Solo si se cumplen ≥3 de: unidades paralelizables, ramas o rollback, estado intermedio valioso, "hecho" verificable
por nodo, beneficio de coordinación mayor que su costo.

## T16. Primer loop [L13]
```
Goal: <tarea recurrente ≥2/semana, p. ej. "revisar los 10 issues más recientes">
Por ítem: <reglas: saltar si ya etiquetado; etiquetar; si se arregla en <10 min, rama + fix>
Stop when: todos procesados | un ítem requiere decisión humana
Maker/Checker separados · memoria: un .md que la siguiente corrida lee primero · disparador: /loop o tarea programada
(empezar 1/día y observar una semana)
```

## T17. Mensaje de error para agentes [L10]
`ERROR: <qué y dónde> · WHY: <regla y motivo> · FIX: <acción concreta y archivo destino>`

## T18. Feedback de review → regla [L10]
Si un comentario de revisión se repite (o si hubo que corregir lo mismo dos veces): conviértelo en un chequeo
ejecutable (lint, hook o test) con un mensaje de tipo T17. No lo repitas en prompts.
