"""Paso 1 bottler en el flujo: ¿validar clientes? -> bronze clients -> Datamatch (fakes)."""

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from cleaning_agent.application.graph.builder import build_graph
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.domain.models import ClientValidationResult
from cleaning_agent.entrypoints.cli import run_resume as cli_resume
from tests.fakes import (
    CLIENTS_FILE,
    RAW,
    FakeDatasets,
    FakeStorage,
    answer_layer_and_front,
    begin,
    make_deps,
    sample_df,
)


@dataclass
class FakeClientValidation:
    countries: tuple[str, ...] = ("mx",)
    error: Exception | None = None
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def supports(self, country: str) -> bool:
        return country.lower() in self.countries

    def validate(
        self,
        src: str,
        country: str,
        bottler: str,
        canal: str,
        fecha: str,
        run_id: str,
        territory: str | None = None,
    ) -> ClientValidationResult:
        self.calls.append((src, country, bottler, canal, fecha, territory or ""))
        if self.error:
            raise self.error
        prefix = f"bronze/ko/{country}/{bottler.lower()}/clients/{fecha}"
        name = "clientes_todos_validos"
        return ClientValidationResult(
            csv=f"data/{prefix}/{name}.csv",
            metadata=f"data/{prefix}/{name}_metadata.json",
            qa=f"data/{prefix}/{name}_qa.html",
            blob_prefix=prefix,
            rows_read=10,
            rows_valid=8,
            qa_ok=True,
            summary={"filas_leidas": 10, "filas_validas": 8},
        )


TERRITORY = "data/raw/mx/femsa/territorio.geojson"


def validate_and_upload(app: Any, thread_id: str = "t1") -> dict[str, Any]:
    """Mandatory paso 1: answer with the territory and approve the bronze upload."""
    view = cli_resume(app, thread_id, {"territorio_geojson": TERRITORY})
    assert _kind(view) == "confirm_layer_upload", view
    return cli_resume(app, thread_id, {"approved": True})


def _kind(view: dict[str, Any]) -> str | None:
    return (view.get("interrupt") or {}).get("kind")


def run_resume(app: Any, thread_id: str, answer: Any) -> dict[str, Any]:
    return answer_layer_and_front(
        cli_resume, app, thread_id, cli_resume(app, thread_id, answer)
    )


def _to_client_question(
    validator: FakeClientValidation | None, storage: FakeStorage | None = None
) -> tuple[Any, Dependencies, dict[str, Any]]:
    deps, datasets, *_ = make_deps(storage=storage)
    deps = dataclasses.replace(deps, client_validation=validator)
    assert isinstance(datasets, FakeDatasets)
    datasets.inputs[RAW] = sample_df()
    app = build_graph(deps).compile(checkpointer=InMemorySaver())
    begin(app, "t1", "ninguno")
    run_resume(app, "t1", {})
    run_resume(app, "t1", {"approved": True})
    view = run_resume(app, "t1", {"approved": True})  # silver + gold -> clients
    return app, deps, view


def test_client_validation_is_asked_before_the_first_datamatch_step() -> None:
    _, _, view = _to_client_question(FakeClientValidation())
    assert _kind(view) == "validate_clients", view
    assert view["interrupt"]["defaults"]["clients_file"] == CLIENTS_FILE
    assert view["interrupt"]["defaults"]["canal"] == "todos"


def test_validated_base_goes_to_bronze_and_feeds_datamatch() -> None:
    validator, storage = FakeClientValidation(), FakeStorage()
    app, _, _ = _to_client_question(validator, storage)

    view = cli_resume(
        app,
        "t1",
        {"validate_clients": True, "canal": "tradicional", "territorio_geojson": TERRITORY},
    )
    assert _kind(view) == "confirm_layer_upload"
    pending = view["interrupt"]
    assert pending["layer"] == "bronze"
    prefix = pending["defaults"]["blob_prefix"]
    assert prefix.startswith("bronze/ko/mx/") and "/clients/" in prefix
    assert any(f.endswith("_qa.html") for f in pending["files"])
    assert validator.calls[0][0] == CLIENTS_FILE and validator.calls[0][3] == "tradicional"
    assert validator.calls[0][5] == TERRITORY

    view = cli_resume(app, "t1", {"approved": True})
    assert _kind(view) == "front_datamatch", view
    assert storage.uploads[-1][2] == prefix
    # the validated CSV is now the client base offered for Datamatch step 1
    assert view["interrupt"]["defaults"]["clients_file"] == (
        f"prospecting-data/{prefix}/clientes_todos_validos.csv"
    )
    steps = {s["step"]: s["status"] for s in view["steps"]}
    assert steps["validate_clients"] == steps["upload_clients"] == "done"


def test_validation_cannot_be_skipped() -> None:
    validator = FakeClientValidation()
    app, _, _ = _to_client_question(validator)
    view = cli_resume(
        app, "t1", {"validate_clients": False, "territorio_geojson": TERRITORY}
    )
    assert _kind(view) == "validate_clients"
    assert any("obligatoria" in e for e in view["interrupt"]["errors"])
    assert validator.calls == []


def test_territory_is_required_and_found_in_the_dwh() -> None:
    storage = FakeStorage(
        blobs=["global_geojson/Mexico_Femsa.geojson", "global_geojson/Argentina_Andina.geojson"]
    )
    app, _, view = _to_client_question(FakeClientValidation(), storage)
    assert view["interrupt"]["territory_candidates"] == [
        "prospection-datacleaning/global_geojson/Mexico_Femsa.geojson"
    ]
    assert view["interrupt"]["defaults"]["territorio_geojson"].endswith("Mexico_Femsa.geojson")
    _, _, view = _to_client_question(FakeClientValidation())
    assert view["interrupt"]["defaults"]["territorio_geojson"] == ""
    app, _, _ = _to_client_question(FakeClientValidation())
    view = cli_resume(app, "t1", {"canal": "todos"})
    assert _kind(view) == "validate_clients"
    assert any("territorio_geojson" in e for e in view["interrupt"]["errors"])


def test_without_a_validator_for_the_country_the_question_is_not_asked() -> None:
    _, _, view = _to_client_question(FakeClientValidation(countries=("ar",)))
    assert _kind(view) == "front_datamatch"
    _, _, view = _to_client_question(None)
    assert _kind(view) == "front_datamatch"


def test_invalid_answer_is_asked_again() -> None:
    app, _, _ = _to_client_question(FakeClientValidation())
    view = cli_resume(
        app, "t1", {"clients_file": "x.txt", "territorio_geojson": TERRITORY}
    )
    assert _kind(view) == "validate_clients"
    assert view["interrupt"]["errors"]


def test_missing_client_file_is_asked_again() -> None:
    app, _, _ = _to_client_question(FakeClientValidation())
    view = cli_resume(
        app, "t1", {"clients_file": "nada.csv", "territorio_geojson": TERRITORY}
    )
    assert _kind(view) == "validate_clients"
    assert any("clients_file" in e for e in view["interrupt"]["errors"])


def test_failed_qa_stops_the_run() -> None:
    app, _, _ = _to_client_question(
        FakeClientValidation(error=AssertionError("QA: la base validada no cuadra"))
    )
    view = cli_resume(app, "t1", {"territorio_geojson": TERRITORY})
    assert view["status"] == "failed"
    assert "QA" in view["error"]


def test_redo_before_datamatch_starts_a_new_cycle() -> None:
    from cleaning_agent.application.graph.delivery_nodes import datamatch_cycle_reset

    old: Any = {
        "datamatch": {"client_name": "andina", "clients_file": "x.csv"},
        "datamatch_history": [{"paso": "paso1"}],
        "datamatch_loop_done": True,
        "qa_process_date": "20261111",
    }
    reset = datamatch_cycle_reset("upload_gold", old)
    assert reset["datamatch"] == {"client_name": "andina"}
    assert reset["datamatch_history"] == [] and reset["datamatch_loop_done"] is False
    assert reset["qa_process_date"] == ""
    # redoing a step inside or after the loop keeps the cycle
    assert datamatch_cycle_reset("stage_datamatch_step", old) == {}
    assert datamatch_cycle_reset("stage_gold_package", old) == {}


def test_redo_from_gold_asks_validation_then_a_fresh_datamatch() -> None:
    from cleaning_agent.entrypoints.cli import run_redo
    from tests.fakes import DATAMATCH_FILE

    app, _, _ = _to_client_question(FakeClientValidation())
    validate_and_upload(app)
    view = run_resume(
        app, "t1", {"datamatch_file": DATAMATCH_FILE, "clients_file": CLIENTS_FILE}
    )
    assert _kind(view) == "confirm_layer_upload"  # paso 1 of the first cycle

    view = run_redo(app, "t1", "upload_gold")
    assert _kind(view) == "validate_clients"
    view = validate_and_upload(app)
    assert _kind(view) == "front_datamatch"
    values = app.get_state({"configurable": {"thread_id": "t1"}}).values
    assert values["datamatch_history"] == []
