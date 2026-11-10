# legacy (solo referencia, no se ejecuta)

Código anterior a la arquitectura hexagonal, guardado como referencia:

- `main.py`: el orquestador original del pipeline (versión del último commit). Sus imports
  (`src.*`, `config.*`) ya no existen: la lógica vive en `cleaning_agent/`.
- `report.ipynb`: el notebook del reporte ejecutivo, portado a
  `cleaning_agent/adapters/executive_report_builder.py`.

El flujo actual se corre con `uv run python -m cleaning_agent interactive` o `/limpiar-dataplor`.
