"""QA_datamatch subprocess adapter, Azure adapter (no network) and circuit breaker."""

import subprocess
from pathlib import Path
from typing import Any, Self

import pytest
import yaml

from cleaning_agent.adapters import azure_storage
from cleaning_agent.adapters.brand import BUNDLED_ASSETS_DIR, KinBrand
from cleaning_agent.adapters.qa_datamatch import (
    BRAND_RUNNER,
    QADatamatchError,
    QADatamatchSubprocess,
)
from cleaning_agent.adapters.resilience import CircuitBreaker, CircuitOpenError
from cleaning_agent.domain.models import DatamatchInputs
from cleaning_agent.domain.storage_errors import BlobExistsError

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
    return QADatamatchSubprocess(
        tmp_path, qa_project, tmp_path / "runs", BRAND, timeout_s=5
    )


BRAND = KinBrand(BUNDLED_ASSETS_DIR)
QA_PAGE = "<html><head><style></style></head><body><h1>Datamatch</h1></body></html>"


def _gold(tmp_path: Path) -> Path:
    return tmp_path / "data/gold/ko/mx/femsa/dataplor/20261111"


def _fake_cli(
    outputs: list[str], returncode: int = 0, calls: list[list[str]] | None = None
) -> Any:
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(list(args))
        config = yaml.safe_load(Path(args[-1]).read_text(encoding="utf-8"))
        out = Path(config["paths"]["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        tag = f"{config['project']['client']}_{config['project']['run_date']}"
        for name in outputs:
            body = QA_PAGE if name.endswith(".html") else "x"
            (out / name.format(tag=tag)).write_text(body, encoding="utf-8")
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr="boom")

    return run


def test_explore_writes_a_run_config_without_touching_the_qa_project(
    tmp_path, qa_project, monkeypatch
):
    monkeypatch.setattr(subprocess, "run", _fake_cli(["threshold_report_{tag}.html"]))

    result = _adapter(tmp_path, qa_project).explore(INPUTS, "t1", _gold(tmp_path))

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

    result = _adapter(tmp_path, qa_project).run(
        INPUTS, "t1", 0.75, 0.85, _gold(tmp_path)
    )

    config = yaml.safe_load(
        (tmp_path / "runs/t1/datamatch_qa/qa_config.yaml").read_text()
    )
    assert config["thresholds"] == {"match": 0.75, "super_match": 0.85}
    assert [Path(f).name.split("_")[0] for f in result.files] == ["Datamatch", "match"]


def test_cli_failure_and_timeout_raise_qa_errors(tmp_path, qa_project, monkeypatch):
    adapter = _adapter(tmp_path, qa_project)
    monkeypatch.setattr(subprocess, "run", _fake_cli([], returncode=1))
    with pytest.raises(QADatamatchError, match="failed:\nboom"):
        adapter.run(INPUTS, "t1", 0.7, 0.8, _gold(tmp_path))

    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("uv", 5)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(QADatamatchError, match="exceeded 5 s"):
        adapter.explore(INPUTS, "t1", _gold(tmp_path))


def test_missing_qa_project_is_reported(tmp_path):
    adapter = QADatamatchSubprocess(
        tmp_path, tmp_path / "nope", tmp_path / "runs", BRAND
    )

    with pytest.raises(QADatamatchError, match="config not found"):
        adapter.explore(INPUTS, "t1", _gold(tmp_path))


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


class _Props:
    def __init__(self, size: int, md5: bytes | None) -> None:
        self.size = size
        self.content_settings = type("CS", (), {"content_md5": md5})()


class _FakeBlob:
    """In-memory blob: remembers what was uploaded so size/MD5 can be verified."""

    def __init__(
        self, store: dict[str, tuple[int, bytes | None]], name: str, corrupt: bool
    ) -> None:
        self.store, self.name, self.corrupt = store, name, corrupt

    def get_blob_properties(self, timeout: int) -> _Props:
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.store:
            raise ResourceNotFoundError("missing")
        return _Props(*self.store[self.name])

    def upload_blob(
        self, data: Any, overwrite: bool, timeout: int, content_settings: Any
    ) -> None:
        if self.name in self.store and not overwrite:
            raise AssertionError("would overwrite without permission")
        body = data.read()
        md5 = bytes(content_settings.content_md5)
        self.store[self.name] = (len(body) + (1 if self.corrupt else 0), md5)


def _fake_azure(
    monkeypatch: Any, storage: Any, store: dict[str, Any], corrupt: bool = False
) -> None:
    class FakeContainer:
        def get_blob_client(self, name: str) -> _FakeBlob:
            return _FakeBlob(store, name, corrupt)

    class FakeService:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def get_container_client(self, container: str) -> FakeContainer:
            return FakeContainer()

    monkeypatch.setattr(storage, "_client", lambda: FakeService())


def test_azure_upload_verifies_size_and_md5(tmp_path, monkeypatch):
    file = tmp_path / "final.csv"
    file.write_text("a,b\n", encoding="utf-8")
    store: dict[str, Any] = {}
    storage = azure_storage.AzureBlobStorage()
    _fake_azure(monkeypatch, storage, store)

    result = storage.upload([str(file)], "prospecting-data", "/bronze/ko/ar/")

    assert result.uploaded == ["prospecting-data/bronze/ko/ar/final.csv"]
    assert store["bronze/ko/ar/final.csv"][0] == file.stat().st_size


def test_azure_skips_identical_and_refuses_different_blobs(tmp_path, monkeypatch):
    file = tmp_path / "final.csv"
    file.write_text("a,b\n", encoding="utf-8")
    store: dict[str, Any] = {}
    storage = azure_storage.AzureBlobStorage()
    _fake_azure(monkeypatch, storage, store)
    storage.upload([str(file)], "c1", "p")

    again = storage.upload([str(file)], "c1", "p")
    assert again.uploaded == [] and again.skipped == ["c1/p/final.csv"]

    file.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(BlobExistsError):
        storage.upload([str(file)], "c1", "p")
    replaced = storage.upload([str(file)], "c1", "p", replace=True)
    assert replaced.uploaded == ["c1/p/final.csv"]


def test_azure_upload_fails_when_verification_differs(tmp_path, monkeypatch):
    file = tmp_path / "final.csv"
    file.write_text("a,b\n", encoding="utf-8")
    storage = azure_storage.AzureBlobStorage()
    _fake_azure(monkeypatch, storage, {}, corrupt=True)

    with pytest.raises(RuntimeError, match="Verification failed"):
        storage.upload([str(file)], "c1", "p")


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


def test_explore_runs_branded_and_writes_the_report_to_gold(
    tmp_path, qa_project, monkeypatch
):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", _fake_cli(["threshold_report_{tag}.html"], calls=calls)
    )

    result = _adapter(tmp_path, qa_project).explore(INPUTS, "t1", _gold(tmp_path))

    report = Path(result.report_html)
    assert report.parent == _gold(tmp_path)
    assert str(BRAND_RUNNER) in calls[0] and "explore" in calls[0]
    theme = yaml.safe_load(
        Path(calls[0][calls[0].index(str(BRAND_RUNNER)) + 1]).read_text()
    )
    assert theme["colors"]["series_1"] == BRAND.color("ka-color-yellow")
    page = report.read_text(encoding="utf-8")
    assert "<style></style>" not in page and "--ka-color-yellow" in page
    assert page.count('class="ka-site"') == 2 and 'class="page"' in page
