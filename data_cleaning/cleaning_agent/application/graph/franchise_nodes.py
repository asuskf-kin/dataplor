"""Franchise review after the Pipeline Data clean (user rule).

Claude Code reviews the remaining names at an interrupt (OXXO, Costco and the
best-known franchises must not remain): it never happens through an API call.
The person then decides whether the marked rows are removed. Marks are columns
(es_franquicia / franquicia_marca), as the marcar-franquicias skill does.

    prepare_franchise_review -> franchise_review* -> [confirm_franchises*] -> approve_output
"""

from collections import Counter

import polars as pl
from langgraph.types import interrupt

from cleaning_agent.application.graph.nodes import (
    Dependencies,
    NodeFn,
    Update,
    _logger,
    _ok,
    _retry,
    _validate,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.franchises import NAME_COLUMNS, mark_franchises, name_column
from cleaning_agent.domain.models import FranchiseDecision, FranchiseReview

CANDIDATES_FILE = "franchise_candidates.csv"


def make_prepare_franchise_review(deps: Dependencies) -> NodeFn:
    def prepare_franchise_review(state: CleaningState) -> Update:
        """Done when the list of distinct names (with counts) is ready for the review."""
        df = deps.datasets.load_step(str(state["current_path"]))
        column = name_column(df)
        candidates = (
            df.group_by(column)
            .agg(pl.len().alias("registros"))
            .sort("registros", descending=True)
        )
        path = deps.runs_dir / state["run_id"] / CANDIDATES_FILE
        written = deps.datasets.publish(candidates, str(path))
        return {
            "franchises": {
                "candidates_file": written,
                "names": candidates.height,
                "rows": df.height,
                "column": column,
            }
        }

    return prepare_franchise_review


def _flags_from_answer(deps: Dependencies, review: FranchiseReview) -> dict[str, str]:
    flags = {f.name.strip(): f.marca.strip() for f in review.flagged}
    if review.flagged_file:
        table = deps.datasets.load_input(review.flagged_file)
        name = next((c for c in (*NAME_COLUMNS, "nombre") if c in table.columns), None)
        brand = next(
            (c for c in ("franquicia_marca", "marca", "brand") if c in table.columns),
            None,
        )
        if name is None or brand is None:
            raise ValueError(
                "flagged_file needs a name column (name_normalized/name) and a brand "
                "column (franquicia_marca/marca)"
            )
        for row in table.select(name, brand).iter_rows():
            if row[0] and row[1]:
                flags[str(row[0]).strip()] = str(row[1]).strip()
    return flags


def make_franchise_review(deps: Dependencies) -> NodeFn:
    def franchise_review(state: CleaningState) -> Update:
        """HITL (Claude Code). Done when the franchise marks are known (possibly none)."""
        info = state.get("franchises") or {}
        answer = interrupt(
            {
                "kind": "franchise_review",
                "question": (
                    "Review de franquicias: revisa que no quede ninguna (OXXO, Costco y las "
                    "franquicias más reconocidas del país)."
                ),
                "country": state.get("country"),
                "candidates_file": info.get("candidates_file"),
                "names": info.get("names"),
                "instructions": (
                    "Claude Code: lee candidates_file (nombre + registros), identifica las cadenas y "
                    "franquicias reconocidas que quedaron y responde con flagged "
                    '[{"name": "<nombre exacto>", "marca": "<marca>"}] o con flagged_file '
                    "(CSV name_normalized,franquicia_marca). Si no hay, flagged: []."
                ),
                "answer_format": {
                    "flagged": [{"name": "OXXO CENTRO", "marca": "OXXO"}]
                },
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(FranchiseReview, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        try:
            flags = _flags_from_answer(deps, parsed)
        except (ValueError, OSError, KeyError) as exc:
            return _retry(state, [f"flagged_file: {exc}"])
        df = deps.datasets.load_step(str(state["current_path"]))
        marked = mark_franchises(df, flags).filter(pl.col("es_franquicia") == "Sí")
        by_brand = Counter(str(b) for b in marked["franquicia_marca"].to_list())
        _logger(state).info("Franchise review: %s rows marked", marked.height)
        return {
            "franchises": {
                **info,
                "flags": flags,
                "marked_rows": marked.height,
                "by_brand": dict(by_brand.most_common()),
                "remove": False,
            },
            **_ok(),
        }

    return franchise_review


def confirm_franchises(state: CleaningState) -> Update:
    """HITL. Done when the person decided whether the marked franchises are removed."""
    info = state.get("franchises") or {}
    answer = interrupt(
        {
            "kind": "confirm_franchises",
            "question": (
                f"Marqué {info.get('marked_rows', 0):,} registros como franquicia. "
                "¿Los elimino del resultado?"
            ),
            "by_brand": info.get("by_brand"),
            "answer_format": {"remove": True, "note": None},
            "errors": state.get("errors", []),
        }
    )
    parsed = _validate(FranchiseDecision, answer)
    if isinstance(parsed, list):
        return _retry(state, parsed)
    return {
        "franchises": {**info, "remove": parsed.remove, "note": parsed.note},
        **_ok(),
    }


def after_franchise_review(state: CleaningState) -> str:
    return "confirm" if (state.get("franchises") or {}).get("marked_rows") else "skip"
