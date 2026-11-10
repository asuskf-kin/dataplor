"""QA_datamatch subprocess adapter, Azure adapter (no network) and circuit breaker."""

import subprocess
from pathlib import Path
from typing import Any, Self

import pytest
import yaml

from cleaning_agent.adapters import azure_storage
from cleaning_agent.adapters.qa_datamatch import QADatamatchError, QADatamatchSubprocess
from cleaning_agent.adapters.resilience import CircuitBreaker, CircuitOpenError
from cleaning_agent.domain.models import DatamatchInputs

INPUTS = DatamatchInputs(
    datamatch_file="front/final_output.csv",
    clients_file="raw/clientes.csv",
    client_name="Femsa",
    country="mx",
)


@pytest.fixture
def qa_project(tmp_path: Path) -> Path:
    project = tmp_path / "QA_datamatch"
    (project / "config").mkdir(parents=True)
    (project / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "project": {"client": "Old", "country": "Mexico", "run_date": None},
                "paths": {
                    "datamatch": "a.csv",
                    "clients": "b.csv",
                    "output_dir": "out",
                },
                "thresholds": {"match": 0.71, "super_match": 0.8},
            }
        ),
        encoding="utf-8",
    )
    return project


def _adapter(tmp_path: Path, qa_project: Path) -> QADatamatchSubprocess:
    return QADatamatchSubprocess(tmp_path, qa_project, tmp_path / "runs", timeout_s=5)


def _fake_cli(outputs: list[str], returncode: int = 0) -> Any:
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        config = yaml.safe_load(Path(args[-1]).read_text(encoding="utf-8"))
        out = Path(config["paths"]["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        tag = f"{config['project']['client']}_{config['project']['run_date']}"
        for name in outputs:
            (out / name.format(tag=tag)).write_text("x", encoding="utf-8")
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr="boom")

    return run


def test_explore_writes_a_run_config_without_touching_the_qa_project(
    tmp_path, qa_project, monkeypatch
):
    monkeypatch.setattr(subprocess, "run", _fake_cli(["threshold_report_{tag}.html"]))

    result = _adapter(tmp_path, qa_project).explore(INPUTS, "t1")

    config = yaml.safe_load(
        (tmp_path / "runs/t1/datamatch_qa/qa_config.yaml").read_text()
    )
    assert (
        config["project"]["client"] == "Femsa" and config["project"]["country"] == "mx"
    )
    assert config["paths"]["datamatch"] == str(tmp_path / "front/final_output.csv")
    assert config["thresholds"]["match"] == 0.71
    assert Path(result.report_html).is_file()
    assert "Old" in (qa_project / "config/config.yaml").read_text()


def test_run_passes_thresholds_and_collects_csvs(tmp_path, qa_project, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_cli(
            ["Datamatch_Final_{tag}.csv", "match_{tag}.csv", "review_sample_{tag}.csv"]
        ),
    )

    result = _adapter(tmp_path, qa_project).run(INPUTS, "t1", 0.75, 0.85)

    config = yaml.safe_load(
        (tmp_path / "runs/t1/datamatch_qa/qa_config.yaml").read_text()
    )
    assert config["thresholds"] == {"match": 0.75, "super_match": 0.85}
    assert [Path(f).name.split("_")[0] for f in result.files] == ["Datamatch", "match"]


def test_cli_failure_and_timeout_raise_qa_errors(tmp_path, qa_project, monkeypatch):
    adapter = _adapter(tmp_path, qa_project)
    monkeypatch.setattr(subprocess, "run", _fake_cli([], returncode=1))
    with pytest.raises(QADatamatchError, match="failed:\nboom"):
        adapter.run(INPUTS, "t1", 0.7, 0.8)

    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("uv", 5)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(QADatamatchError, match="exceeded 5 s"):
        adapter.explore(INPUTS, "t1")


def test_missing_qa_project_is_reported(tmp_path):
    adapter = QADatamatchSubprocess(tmp_path, tmp_path / "nope", tmp_path / "runs")

    with pytest.raises(QADatamatchError, match="config not found"):
        adapter.explore(INPUTS, "t1")


def test_azure_reads_credentials_only_from_the_environment(monkeypatch):
    monkeypatch.delenv(azure_storage.ACCOUNT_URL_ENV, raising=False)
    monkeypatch.delenv(azure_storage.CONNECTION_STRING_ENV, raising=False)
    storage = azure_storage.AzureBlobStorage()
    assert not storage.is_configured()
    with pytest.raises(azure_storage.StorageNotConfiguredError):
        storage.upload(["x.csv"], "c", "p")

    monkeypatch.setenv(azure_storage.ACCOUNT_URL_ENV, "http://insecure.example")
    assert storage.is_configured()
    with pytest.raises(azure_storage.StorageNotConfiguredError, match="https"):
        storage.upload(["x.csv"], "c", "p")


def test_azure_upload_names_blobs_under_the_prefix(tmp_path, monkeypatch):
    file = tmp_path / "final.csv"
    file.write_text("a,b\n", encoding="utf-8")
    sent: list[tuple[str, bool]] = []

    class FakeContainer:
        def upload_blob(
            self, name: str, data: Any, overwrite: bool, timeout: int
        ) -> None:
            sent.append((name, overwrite))

    class FakeService:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def get_container_client(self, container: str) -> FakeContainer:
            return FakeContainer()

    storage = azure_storage.AzureBlobStorage()
    monkeypatch.setattr(storage, "_client", lambda: FakeService())

    result = storage.upload([str(file)], "prospeccion", "/mx/femsa/")

    assert sent == [("mx/femsa/final.csv", True)]
    assert result.uploaded == ["prospeccion/mx/femsa/final.csv"]


def test_circuit_breaker_opens_and_half_opens():
    now = [0.0]
    breaker = CircuitBreaker(
        "svc", failure_threshold=2, reset_after_s=10, clock=lambda: now[0]
    )

    def fail() -> None:
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            breaker.call(fail)
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "never called")

    now[0] = 11
    assert breaker.call(lambda: "ok") == "ok"  # half-open lets one call through
    assert not breaker.is_open
