"""Graph state. Only JSON-friendly values: the SQLite checkpointer stores it as-is.

Pydantic models validate data at the edges (human answers, adapter results) and
are stored here as ``model_dump()`` dicts.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

from cleaning_agent.application.graph.progress import merge_steps

Status = Literal[
    "asking",
    "planned",
    "cancelled",
    "failed",
    "running",
    "awaiting_approval",
    "rejected",
    "published",
    "uploaded",
    "kept_local",
    "prioritized",
]


class CleaningState(TypedDict, total=False):
    run_id: str
    run_date: str
    status: Status
    error: str | None

    # Run context (intake), asked first
    intake: dict[str, object] | None
    country: str
    bottler: str
    channel: str
    premise: str
    raw_local: str | None

    # Human answers (validated)
    mode: str | None
    inputs: dict[str, object] | None
    modules: list[int]
    plan_notes: list[str]
    note: str | None

    # Validation loop of the current question (reset after a valid answer)
    attempts: int
    errors: list[str]

    # Execution
    items_to_track: list[str]
    audit_file: str | None
    prefilter: dict[str, object] | None
    input_rows: int
    current_path: str | None
    cursor: int
    # Appended by run_module once per module: the reducer keeps the history
    metrics: Annotated[list[dict[str, object]], operator.add]
    report_path: str | None
    summary: dict[str, object] | None
    output_path: str | None

    # Delivery: Datamatch (Front) -> QA -> Azure
    run_datamatch: bool | None
    datamatch: dict[str, object] | None
    qa_report: str | None
    thresholds: dict[str, float] | None
    qa_outputs: list[str]
    upload_target: dict[str, str] | None
    uploaded: list[str]

    # Executive report, warehouse, priorización, lineage
    report_files: list[str]
    report_summary: dict[str, object] | None
    warehouse: list[dict[str, object]]
    priorizacion: dict[str, object] | None
    lineage_path: str | None
    # File set waiting for (or done with) a DWH layer upload approval
    pending_upload: dict[str, object] | None
    # Datamatch loop: one summary per step (overwritten as a whole, keyed by step)
    datamatch_history: list[dict[str, object]]
    datamatch_loop_done: bool
    qa_process_date: str
    # Front step after bronze: what the person gave back and its local mirror copies
    front: dict[str, object] | None
    front_local: dict[str, str] | None
    # Country chain patterns: status, last update and whether they were refreshed
    patterns: dict[str, object] | None
    # Franchise review (Claude Code) and the person's decision
    franchises: dict[str, Any] | None
    priorizacion_outputs: list[str]
    # Appended by every stage: lineage records, their sidecar files and things to check
    lineage: Annotated[list[dict[str, object]], operator.add]
    sidecars: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    # Harness: status of every step (see progress.py); latest record per step wins
    step_status: Annotated[dict[str, dict[str, object]], merge_steps]
