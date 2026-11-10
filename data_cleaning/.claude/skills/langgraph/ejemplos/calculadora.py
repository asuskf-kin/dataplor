"""Loop agente <-> herramientas escrito a mano con la Graph API (adaptado del quickstart oficial de LangGraph).

Es el mismo loop que Claude Code ejecuta por dentro: llamar al modelo, si pide tools ejecutarlas, repetir.
Aquí se ve explícito, nodo por nodo, para compararlo con el loop de Claude Code (clase 22).

    python calculadora.py "Suma 3 y 4, y multiplica el resultado por 10"   # Claude: necesita ANTHROPIC_API_KEY
    python calculadora.py --offline                                        # modelo falso, sin red

Diferencias con el quickstart de docs.langchain.com (verificado el 2026-11-09):
- Sin `temperature=0`: los modelos Claude 5.x rechazan sampling no por defecto (langchain-anthropic lanza
  ValueError en Sonnet 5.5 y Fable; la API responde 400 en Opus 5.5).
- Modelo desde MODELO_CLAUDE (por defecto claude-opus-5-5) y streaming con `stream_events(version="v3")`.
"""
from __future__ import annotations

import operator
import os
import sys
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from langchain.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

sys.stdout.reconfigure(encoding="utf-8")


@tool
def sumar(a: int, b: int) -> int:
    """Suma a y b."""
    return a + b


@tool
def multiplicar(a: int, b: int) -> int:
    """Multiplica a por b."""
    return a * b


TOOLS = {t.name: t for t in (sumar, multiplicar)}


class Estado(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]  # reducer: agrega mensajes en vez de reemplazar
    llamadas_llm: int


def construir(modelo: BaseChatModel, max_llamadas: int = 8):
    con_tools = modelo.bind_tools(list(TOOLS.values()))

    def llm(state: Estado) -> dict[str, Any]:
        r = con_tools.invoke([SystemMessage("Eres una calculadora. Usa las herramientas.")] + state["messages"])
        return {"messages": [r], "llamadas_llm": state.get("llamadas_llm", 0) + 1}

    def herramientas(state: Estado) -> dict[str, Any]:
        ultimo = state["messages"][-1]
        assert isinstance(ultimo, AIMessage)
        return {"messages": [ToolMessage(content=str(TOOLS[c["name"]].invoke(c["args"])), tool_call_id=c["id"])
                             for c in ultimo.tool_calls]}

    def seguir(state: Estado) -> Literal["herramientas", "__end__"]:
        ultimo = state["messages"][-1]
        # Presupuesto explícito además del recursion_limit de LangGraph (que por defecto lanza un error)
        if isinstance(ultimo, AIMessage) and ultimo.tool_calls and state["llamadas_llm"] < max_llamadas:
            return "herramientas"
        return END

    g = StateGraph(Estado)
    g.add_node("llm", llm)
    g.add_node("herramientas", herramientas)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", seguir, ["herramientas", END])
    g.add_edge("herramientas", "llm")
    return g.compile()


class ModeloFalso(BaseChatModel):
    """Devuelve respuestas guionadas; solo para probar el grafo sin red."""

    guion: list[AIMessage]

    @property
    def _llm_type(self) -> str:
        return "falso"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ModeloFalso":
        return self

    def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        from langchain_core.outputs import ChatGeneration, ChatResult
        return ChatResult(generations=[ChatGeneration(message=self.guion.pop(0))])


def modelo_offline() -> ModeloFalso:
    return ModeloFalso(guion=[
        AIMessage("", tool_calls=[{"name": "sumar", "args": {"a": 3, "b": 4}, "id": "t1"}]),
        AIMessage("", tool_calls=[{"name": "multiplicar", "args": {"a": 7, "b": 10}, "id": "t2"}]),
        AIMessage("El resultado es 70."),
    ])


def main() -> None:
    offline = "--offline" in sys.argv
    pregunta = next((a for a in sys.argv[1:] if not a.startswith("--")),
                    "Suma 3 y 4, y multiplica el resultado por 10")
    if offline:
        modelo: BaseChatModel = modelo_offline()
    else:
        from langchain_anthropic import ChatAnthropic
        modelo = ChatAnthropic(model=os.environ.get("MODELO_CLAUDE", "claude-opus-5-5"),
                               max_tokens=16000, timeout=120, max_retries=2)
    agente = construir(modelo)
    stream = agente.stream_events({"messages": [HumanMessage(pregunta)], "llamadas_llm": 0}, version="v3")
    for mensaje in stream.messages:  # tokens a medida que llegan (el modelo falso no emite deltas)
        print(str(mensaje.text), end="", flush=True)
    final = stream.output
    print()
    for m in final["messages"]:
        m.pretty_print()
    if offline:
        assert final["messages"][-1].content == "El resultado es 70." and final["llamadas_llm"] == 3
        assert [m.content for m in final["messages"] if isinstance(m, ToolMessage)] == ["7", "70"]
        print("OK  loop llm <-> herramientas con stream_events v3")


if __name__ == "__main__":
    main()
