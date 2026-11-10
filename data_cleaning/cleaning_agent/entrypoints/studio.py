"""Entry point for `langgraph dev` / LangGraph Studio (see langgraph.json).

The Agent Server supplies persistence, so the graph is compiled without one here.
"""

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.wiring import default_dependencies

graph = build_graph(default_dependencies()).compile()
