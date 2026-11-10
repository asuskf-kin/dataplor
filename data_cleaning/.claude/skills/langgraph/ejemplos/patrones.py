"""Patrones de LangGraph sin LLM: reducers, Send (map-reduce), Command, subgrafo, streaming v2,
interrupt con response_schema, time travel y RetryPolicy.

Corre sin red ni API key, así que sirve como prueba de humo de la instalación:
    python patrones.py        # imprime "OK" por patrón y falla ruidosamente si algo cambió en la API

Verificado el 2026-11-09 con langgraph 1.2.20 (Python 3.14). Cada bloque cita la página de docs.langchain.com
de la que sale.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal

from pydantic import BaseModel
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, Send, interrupt


# --- 1. Reducers + Send: map-reduce (graph-api-send-command) ----------------------------------------------
class Global(TypedDict):
    temas: list[str]
    resumenes: Annotated[list[str], operator.add]  # reducer: los workers paralelos concatenan, no se pisan


class Tarea(TypedDict):  # el worker recibe solo esto, no el estado global
    tema: str


def repartir(state: Global) -> list[Send]:
    return [Send("resumir", {"tema": t}) for t in state["temas"]]


def resumir(state: Tarea) -> dict[str, list[str]]:
    return {"resumenes": [f"resumen de {state['tema']}"]}


def map_reduce() -> None:
    g = StateGraph(Global)
    g.add_node("resumir", resumir)
    g.add_conditional_edges(START, repartir, ["resumir"])
    g.add_edge("resumir", END)
    out = g.compile().invoke({"temas": ["ventas", "costos", "margen"], "resumenes": []})
    assert sorted(out["resumenes"]) == ["resumen de costos", "resumen de margen", "resumen de ventas"], out
    print("OK  Send + reducer:", out["resumenes"])


# --- 2. Command: actualizar estado y elegir el siguiente nodo en un solo return --------------------------
class Ruta(TypedDict):
    monto: float
    via: str


def clasificar(state: Ruta) -> Command[Literal["auto", "revision"]]:
    destino: Literal["auto", "revision"] = "revision" if state["monto"] > 1000 else "auto"
    return Command(update={"via": destino}, goto=destino)


def command_routing() -> None:
    g = StateGraph(Ruta)
    g.add_node(clasificar)
    g.add_node("auto", lambda s: {"via": s["via"] + ":aprobado"})
    g.add_node("revision", lambda s: {"via": s["via"] + ":en_cola"})
    g.add_edge(START, "clasificar")  # sin aristas entre clasificar y sus destinos: las decide Command
    app = g.compile()
    assert app.invoke({"monto": 50.0, "via": ""})["via"] == "auto:aprobado"
    assert app.invoke({"monto": 5000.0, "via": ""})["via"] == "revision:en_cola"
    print("OK  Command(update, goto)")


# --- 3. Subgrafo con estado compartido, agregado como nodo (use-subgraphs) --------------------------------
class Compartido(TypedDict):
    texto: str


def subgrafo() -> None:
    sub = StateGraph(Compartido)
    sub.add_node("limpiar", lambda s: {"texto": s["texto"].strip().lower()})
    sub.add_edge(START, "limpiar")
    padre = StateGraph(Compartido)
    padre.add_node("normalizar", sub.compile())  # comparten la clave "texto": no hace falta wrapper
    padre.add_node("cerrar", lambda s: {"texto": s["texto"] + "."})
    padre.add_edge(START, "normalizar")
    padre.add_edge("normalizar", "cerrar")
    app = padre.compile()
    assert app.invoke({"texto": "  HOLA "})["texto"] == "hola."
    # Streaming v2 (streaming, LangGraph >= 1.1): cada parte es {"type", "ns", "data"}; ns != () viene del subgrafo
    tipos = {(p["type"], bool(p["ns"])) for p in app.stream(
        {"texto": " X "}, stream_mode="updates", subgraphs=True, version="v2")}
    assert ("updates", True) in tipos and ("updates", False) in tipos, tipos
    print("OK  subgrafo como nodo + stream v2 con subgraphs=True")


# --- 4. interrupt con response_schema tipado (interrupts; requiere langgraph >= 1.2.12) --------------------
class Decision(BaseModel):
    aprobado: bool
    nota: str | None = None


class Aprob(TypedDict):
    accion: str
    decision: Decision | None


def pedir_ok(state: Aprob) -> dict[str, Decision]:
    # Todo lo que esté antes de interrupt() se re-ejecuta al reanudar: aquí no va nada con efectos.
    d = interrupt({"pregunta": "¿Apruebas?", "accion": state["accion"]}, response_schema=Decision)
    return {"decision": d}


def hitl() -> None:
    g = StateGraph(Aprob)
    g.add_node(pedir_ok)
    g.add_edge(START, "pedir_ok")
    app = g.compile(checkpointer=InMemorySaver())  # sin checkpointer, interrupt no puede pausar
    cfg = {"configurable": {"thread_id": "hitl-1"}}
    r = app.invoke({"accion": "publicar reporte", "decision": None}, cfg)
    pendiente = r["__interrupt__"][0]
    assert pendiente.value["accion"] == "publicar reporte"
    assert pendiente.response_schema == Decision.model_json_schema()
    r = app.invoke(Command(resume={"aprobado": True, "nota": "ok"}), cfg)  # mismo thread_id
    assert r["decision"] == Decision(aprobado=True, nota="ok")
    print("OK  interrupt + Command(resume) + response_schema")


# --- 5. Time travel: replay y fork desde un checkpoint (use-time-travel) ---------------------------------
class Cuenta(TypedDict):
    n: int


def time_travel() -> None:
    g = StateGraph(Cuenta)
    g.add_node("doblar", lambda s: {"n": s["n"] * 2})
    g.add_node("sumar", lambda s: {"n": s["n"] + 1})
    g.add_edge(START, "doblar")
    g.add_edge("doblar", "sumar")
    app = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "tt-1"}}
    assert app.invoke({"n": 3}, cfg)["n"] == 7
    historia = list(app.get_state_history(cfg))  # del más reciente al más antiguo
    antes_de_sumar = next(s for s in historia if s.next == ("sumar",))
    # Fork: update_state no reescribe la historia, crea una rama nueva desde ese checkpoint
    rama = app.update_state(antes_de_sumar.config, {"n": 100})
    assert app.invoke(None, rama)["n"] == 101
    print("OK  get_state_history + update_state (fork) + invoke(None, config)")


# --- 6. RetryPolicy por nodo (fault-tolerance) -----------------------------------------------------------
class Intentos(TypedDict):
    ok: bool


_fallos = {"n": 0}


def inestable(state: Intentos) -> dict[str, bool]:
    _fallos["n"] += 1
    if _fallos["n"] < 3:
        raise ConnectionError("fallo transitorio simulado")
    return {"ok": True}


def reintentos() -> None:
    g = StateGraph(Intentos)
    g.add_node("inestable", inestable, retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.01))
    g.add_edge(START, "inestable")
    assert g.compile().invoke({"ok": False})["ok"] is True and _fallos["n"] == 3
    print("OK  RetryPolicy(max_attempts=3)")


if __name__ == "__main__":
    map_reduce()
    command_routing()
    subgrafo()
    hitl()
    time_travel()
    reintentos()
