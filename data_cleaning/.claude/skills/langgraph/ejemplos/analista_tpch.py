"""Analista Autónomo, entrega de la clase 22: grafo LangGraph sobre TPC-H (DuckDB) con Claude.

    entender -> planear_sql -> ejecutar -> verificar --ok--> aprobar (interrupt) --sí--> publicar
                    ^                          |
                    +---- no ok (rollback) ----+  (hasta MAX_INTENTOS; luego termina sin publicar)

Criterios de salida de la clase 22 que demuestra:
- Se puede matar el proceso y reanudar desde el checkpoint: `preguntar` termina en el interrupt (el proceso
  sale) y `aprobar`, en otro proceso, retoma el mismo thread desde SQLite.
- `interrupt` detiene la publicación hasta que un humano decide.

Uso (desde esta carpeta, con el venv de requirements.txt):
    python analista_tpch.py preparar                      # crea analista.duckdb (TPC-H, sf=0.01)
    python analista_tpch.py preguntar t1 "¿Cuánto ingreso ..."   # Claude: necesita ANTHROPIC_API_KEY
    python analista_tpch.py aprobar t1 --si --nota "revisado"     # o --no
    python analista_tpch.py preguntar t2 "x" --offline    # sin red: planner/verificador deterministas (Q6)

El modelo sale de MODELO_CLAUDE (por defecto claude-opus-5-5). La API key solo se lee del entorno.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Literal

import duckdb
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

DB = Path("analista.duckdb")
CHECKPOINTS = "checkpoints.sqlite"
REPORTES = Path("reportes")
MAX_INTENTOS = 3
MUESTRA = 20  # filas que ven el verificador y el humano

sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows en cp1252
sys.stderr.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format='{"nivel":"%(levelname)s","msg":%(message)s}')
log = logging.getLogger("analista")


# --- Contratos ------------------------------------------------------------------------------------------
class PlanSQL(BaseModel):
    sql: str = Field(description="Una sola consulta SELECT (o WITH ... SELECT) en dialecto DuckDB")


class Veredicto(BaseModel):
    ok: bool = Field(description="True si el resultado responde la pregunta")
    motivo: str = Field(description="Por qué; si no es ok, qué corregir en el SQL")


class Decision(BaseModel):
    aprobado: bool
    nota: str | None = None


class Estado(TypedDict):
    pregunta: str
    esquema: str
    sql: str | None
    filas: list[list[str]] | None  # texto: el estado y el payload del interrupt deben ser serializables
    error: str | None
    veredicto: dict[str, object] | None
    intentos: int
    reporte: str | None


# Puertos: el grafo no sabe si detrás hay Claude o un stub. Así se prueba sin red (arquitectura hexagonal).
Planificador = Callable[[str, str, str | None], PlanSQL]  # (pregunta, esquema, feedback) -> plan
Verificador = Callable[[str, str, list[list[str]] | None, str | None], Veredicto]


# --- Nodos ----------------------------------------------------------------------------------------------
def entender(state: Estado) -> dict[str, object]:
    pregunta = state["pregunta"].strip()
    if not pregunta or len(pregunta) > 2000:  # validar la entrada en el borde
        raise ValueError("La pregunta debe tener entre 1 y 2000 caracteres")
    with duckdb.connect(str(DB), read_only=True) as con:
        cols = con.execute(
            "SELECT table_name, string_agg(column_name || ' ' || data_type, ', ') "
            "FROM information_schema.columns GROUP BY 1 ORDER BY 1").fetchall()
    return {"pregunta": pregunta, "esquema": "\n".join(f"{t}({c})" for t, c in cols), "intentos": 0}


def hacer_planear(planificador: Planificador) -> Callable[[Estado], dict[str, object]]:
    def planear_sql(state: Estado) -> dict[str, object]:
        feedback = None
        if state["veredicto"] and not state["veredicto"]["ok"]:
            feedback = f"Intento anterior:\n{state['sql']}\nProblema: {state['veredicto']['motivo']}"
        plan = planificador(state["pregunta"], state["esquema"], feedback)
        return {"sql": plan.sql, "intentos": state["intentos"] + 1, "filas": None, "error": None}
    return planear_sql


def ejecutar(state: Estado) -> dict[str, object]:
    sql = (state["sql"] or "").strip().rstrip(";")
    # Dos barreras deterministas: lista permitida de sentencias y conexión de solo lectura.
    if ";" in sql or not sql.lower().startswith(("select", "with")):
        return {"error": "Solo se permite una consulta SELECT/WITH", "filas": None}
    try:
        with duckdb.connect(str(DB), read_only=True) as con:
            filas = con.execute(sql).fetchmany(MUESTRA)  # DuckDB 2.0: fetch sobre el resultado de execute
    except duckdb.Error as e:  # el error de SQL es dato para el verificador, no un fallo del grafo
        return {"error": f"{type(e).__name__}: {e}"[:500], "filas": None}
    return {"filas": [[str(v) for v in f] for f in filas], "error": None}


def hacer_verificar(verificador: Verificador) -> Callable[[Estado], dict[str, object]]:
    def verificar(state: Estado) -> dict[str, object]:
        if state["error"]:  # no hace falta un LLM para saber que un error de ejecución no es una respuesta
            v = Veredicto(ok=False, motivo=state["error"])
        else:
            # Contexto fresco: el verificador ve pregunta, SQL y resultado; nunca el razonamiento del planner.
            v = verificador(state["pregunta"], state["sql"] or "", state["filas"], state["error"])
        log.info(json.dumps({"nodo": "verificar", "intento": state["intentos"], "ok": v.ok}))
        return {"veredicto": v.model_dump()}
    return verificar


def despues_de_verificar(state: Estado) -> Literal["aprobar", "planear_sql", "__end__"]:
    if state["veredicto"] and state["veredicto"]["ok"]:
        return "aprobar"
    return "planear_sql" if state["intentos"] < MAX_INTENTOS else END


def aprobar(state: Estado) -> Command[Literal["publicar", "__end__"]]:
    # Nada con efectos antes de interrupt(): al reanudar, el nodo se ejecuta otra vez desde el principio.
    d: Decision = interrupt(
        {"pregunta": state["pregunta"], "sql": state["sql"], "muestra": state["filas"],
         "veredicto": state["veredicto"]},
        response_schema=Decision,
    )
    return Command(goto="publicar" if d.aprobado else END,
                   update={"reporte": None if d.aprobado else f"Rechazado: {d.nota or 'sin nota'}"})


def publicar(state: Estado, config: RunnableConfig) -> dict[str, object]:
    thread = config["configurable"]["thread_id"]
    REPORTES.mkdir(exist_ok=True)
    destino = REPORTES / f"{thread}.md"  # un archivo por thread: reintentar sobrescribe, no duplica
    filas = "\n".join("| " + " | ".join(f) + " |" for f in state["filas"] or [])
    destino.write_text(f"# {state['pregunta']}\n\n```sql\n{state['sql']}\n```\n\n{filas}\n\n"
                       f"Verificación: {state['veredicto']}\n", encoding="utf-8")
    return {"reporte": str(destino)}


def construir(planificador: Planificador, verificador: Verificador) -> StateGraph:
    g = StateGraph(Estado)
    reintento = RetryPolicy(max_attempts=3)  # fallos transitorios de red en los nodos con LLM
    g.add_node("entender", entender)
    g.add_node("planear_sql", hacer_planear(planificador), retry_policy=reintento)
    g.add_node("ejecutar", ejecutar)
    g.add_node("verificar", hacer_verificar(verificador), retry_policy=reintento)
    g.add_node("aprobar", aprobar)
    g.add_node("publicar", publicar)
    g.add_edge(START, "entender")
    g.add_edge("entender", "planear_sql")
    g.add_edge("planear_sql", "ejecutar")
    g.add_edge("ejecutar", "verificar")
    g.add_conditional_edges("verificar", despues_de_verificar, ["aprobar", "planear_sql", END])
    g.add_edge("publicar", END)
    return g


# --- Adaptadores: Claude (real) y stubs deterministas (offline) -------------------------------------------
def adaptadores_claude() -> tuple[Planificador, Verificador]:
    from langchain_anthropic import ChatAnthropic

    modelo = ChatAnthropic(model=os.environ.get("MODELO_CLAUDE", "claude-opus-5-5"),
                           max_tokens=16000, timeout=120, max_retries=2)
    # method="json_schema" usa output_config.format. El método por defecto (function_calling) fuerza
    # tool_choice, y Opus 5.5 / Sonnet 5.5 / Fable 5.1+ responden 400 a eso: langchain-anthropic lo advierte.
    plan_llm = modelo.with_structured_output(PlanSQL, method="json_schema")
    juez_llm = modelo.with_structured_output(Veredicto, method="json_schema")

    def planificar(pregunta: str, esquema: str, feedback: str | None) -> PlanSQL:
        msg = (f"Esquema DuckDB (TPC-H):\n{esquema}\n\nPregunta de negocio: {pregunta}\n"
               "Escribe una sola consulta SELECT que la responda.")
        if feedback:
            msg += f"\n\n{feedback}"
        return plan_llm.invoke([("system", "Eres analista de datos. Respondes solo con SQL de lectura."),
                                ("user", msg)])

    def verificar(pregunta: str, sql: str, filas: list[list[str]] | None, error: str | None) -> Veredicto:
        return juez_llm.invoke([("system", "Revisas si un resultado SQL responde una pregunta. Sé escéptico."),
                                ("user", f"Pregunta: {pregunta}\nSQL:\n{sql}\nResultado (muestra): {filas}")])

    return planificar, verificar


def adaptadores_offline() -> tuple[Planificador, Verificador]:
    """Escenario fijo (TPC-H Q6) para probar el grafo sin red: el 1.er plan falla a propósito (rollback)."""
    with duckdb.connect(str(DB), read_only=True) as con:
        q6 = con.execute("SELECT query FROM tpch_queries() WHERE query_nr = 6").fetchone()[0]
        esperado = Decimal(con.execute("SELECT answer FROM tpch_answers() WHERE query_nr = 6 "
                                       "AND scale_factor = 0.01").fetchone()[0].split("\n")[1])

    def planificar(pregunta: str, esquema: str, feedback: str | None) -> PlanSQL:
        return PlanSQL(sql=q6 if feedback else q6.replace("lineitem", "lineitems"))

    def verificar(pregunta: str, sql: str, filas: list[list[str]] | None, error: str | None) -> Veredicto:
        # Ancla contra Goodhart: la verdad terreno de tpch_answers(), comparada con tolerancia, nunca con ==.
        ok = bool(filas) and abs(Decimal(filas[0][0]) - esperado) <= Decimal("0.01")
        return Veredicto(ok=ok, motivo="coincide con tpch_answers" if ok else "no coincide con tpch_answers")

    return planificar, verificar


# --- CLI ------------------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preparar")
    pq = sub.add_parser("preguntar")
    pq.add_argument("thread")
    pq.add_argument("pregunta")
    pq.add_argument("--offline", action="store_true")
    pa = sub.add_parser("aprobar")
    pa.add_argument("thread")
    grupo = pa.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--si", action="store_true")
    grupo.add_argument("--no", action="store_true")
    pa.add_argument("--nota")
    pa.add_argument("--offline", action="store_true")
    a = p.parse_args()

    if a.cmd == "preparar":
        with duckdb.connect(str(DB)) as con:
            con.execute("INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01)")
        print(f"Listo: {DB}")
        return
    if not DB.exists():
        raise SystemExit("Falta analista.duckdb: corre primero `python analista_tpch.py preparar`")

    planificador, verificador = adaptadores_offline() if a.offline else adaptadores_claude()
    cfg: RunnableConfig = {"configurable": {"thread_id": a.thread}}  # thread_id = cursor y correlation ID
    with SqliteSaver.from_conn_string(CHECKPOINTS) as checkpointer:
        app = construir(planificador, verificador).compile(checkpointer=checkpointer)
        if a.cmd == "preguntar":
            entrada: dict[str, object] | Command = {
                "pregunta": a.pregunta, "esquema": "", "sql": None, "filas": None, "error": None,
                "veredicto": None, "intentos": 0, "reporte": None}
        else:
            if not app.get_state(cfg).interrupts:
                raise SystemExit(f"El thread {a.thread} no está esperando aprobación")
            entrada = Command(resume={"aprobado": a.si, "nota": a.nota})
        r = app.invoke(entrada, cfg, durability="sync")  # sync: cada paso queda en disco antes del siguiente
    if "__interrupt__" in r:
        print("PAUSADO esperando aprobación:\n" + json.dumps(r["__interrupt__"][0].value, ensure_ascii=False,
                                                             indent=1))
        print(f"Reanuda con: python analista_tpch.py aprobar {a.thread} --si|--no")
    else:
        print(f"FIN · intentos={r['intentos']} · veredicto={r['veredicto']} · reporte={r['reporte']}")


if __name__ == "__main__":
    main()
