"""Data lineage: one record per stage, merged at the end of the run.

Same idea as potential-customer-workflow (a ``_metadata.json`` next to each artifact
and an ordered ``linaje`` in a final document), plus what that repo lacks: run id,
code version, per-stage timestamps and input/output hashes inside the JSON. The
final document only merges the records of THIS run (they travel in the graph
state), never older runs found on disk.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

LINEAGE_FILE = "dataplor_pipeline_metadata.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ArtifactRef(BaseModel):
    """A file a stage read or wrote. Remote-only artifacts have no hash or size."""

    path: str
    rows: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    blob: str | None = None


class StageRecord(BaseModel):
    run_id: str
    stage: str
    name: str
    started_at: str
    finished_at: str
    code_version: str
    inputs: list[ArtifactRef] = Field(default_factory=list)
    outputs: list[ArtifactRef] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


def build_lineage_document(
    records: list[StageRecord], run: dict[str, Any], to_verify: list[str]
) -> dict[str, Any]:
    """The final lineage JSON (gold). Pure: no I/O, easy to test."""
    ordered = sorted(records, key=lambda r: r.started_at)
    return {
        "leeme": (
            "Linaje de la corrida del agente de limpieza Dataplor. 'linaje' lista las etapas en "
            "orden con sus entradas y salidas (ruta, filas, bytes, sha256, blob)."
        ),
        "corrida": run,
        "linaje": [
            {
                "paso": position,
                "etapa": record.stage,
                "nombre": record.name,
                "inicio": record.started_at,
                "fin": record.finished_at,
                "entrada": [a.model_dump(exclude_none=True) for a in record.inputs],
                "salida": [a.model_dump(exclude_none=True) for a in record.outputs],
                "resultado": record.metrics,
            }
            for position, record in enumerate(ordered, start=1)
        ],
        "por_verificar": to_verify,
    }
