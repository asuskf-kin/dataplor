"""StoragePort adapter: Azure Blob Storage.

Credentials come ONLY from the environment (see .env.example):
- ``AZURE_STORAGE_ACCOUNT_URL`` (preferred): authenticated with DefaultAzureCredential
  (``az login``, managed identity...), so no secret is stored anywhere.
- ``AZURE_STORAGE_CONNECTION_STRING``: fallback for environments without Azure AD.

Never copy the key-in-code helpers (``azure_utils.py``) from other repositories.
"""

import fnmatch
import hashlib
import logging
import os
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings, ExponentialRetry

from cleaning_agent.adapters.resilience import CircuitBreaker
from cleaning_agent.domain.models import UploadResult
from cleaning_agent.domain.storage_errors import BlobExistsError

logger = logging.getLogger(__name__)

ACCOUNT_URL_ENV = "AZURE_STORAGE_ACCOUNT_URL"
CONNECTION_STRING_ENV = "AZURE_STORAGE_CONNECTION_STRING"


class StorageNotConfiguredError(RuntimeError):
    pass


def _md5(path: Path) -> bytes:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.digest()


def _properties(blob: Any, timeout_s: float) -> tuple[int, bytes | None] | None:
    """(size, MD5) of a blob, or None when it does not exist."""
    try:
        props = blob.get_blob_properties(timeout=int(timeout_s))
    except ResourceNotFoundError:
        return None
    md5 = props.content_settings.content_md5
    return int(props.size), bytes(md5) if md5 else None


class AzureBlobStorage:
    def __init__(
        self,
        timeout_s: float = 120,
        max_attempts: int = 3,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.breaker = breaker or CircuitBreaker("azure-blob", failure_threshold=3)

    def is_configured(self) -> bool:
        return bool(
            os.environ.get(ACCOUNT_URL_ENV) or os.environ.get(CONNECTION_STRING_ENV)
        )

    def _client(self) -> BlobServiceClient:
        retry = ExponentialRetry(retry_total=self.max_attempts, initial_backoff=2)
        timeout = int(self.timeout_s)
        account_url = os.environ.get(ACCOUNT_URL_ENV, "").strip()
        if account_url:
            if not account_url.startswith("https://"):
                raise StorageNotConfiguredError(
                    f"{ACCOUNT_URL_ENV} must start with https://"
                )
            return BlobServiceClient(
                account_url,
                credential=DefaultAzureCredential(),
                retry_policy=retry,
                connection_timeout=timeout,
                read_timeout=timeout,
            )
        connection_string = os.environ.get(CONNECTION_STRING_ENV, "").strip()
        if connection_string:
            return BlobServiceClient.from_connection_string(
                connection_string,
                retry_policy=retry,
                connection_timeout=timeout,
                read_timeout=timeout,
            )
        raise StorageNotConfiguredError(
            f"Set {ACCOUNT_URL_ENV} (recommended) or {CONNECTION_STRING_ENV} to upload to Azure"
        )

    def upload(
        self, files: list[str], container: str, prefix: str, replace: bool = False
    ) -> UploadResult:
        """Uploads following the DWH guideline (Lineamientos Blob CP v1.1).

        - A blob that already exists with the same size and MD5 is skipped.
        - A different existing blob is only replaced with ``replace=True``.
        - After each upload, size and MD5 are verified against the local file.
        """
        uploaded: list[str] = []
        skipped: list[str] = []
        with self._client() as service:
            container_client = service.get_container_client(container)
            for file in files:
                path = Path(file)
                blob_name = f"{prefix.strip('/')}/{path.name}"
                blob = container_client.get_blob_client(blob_name)
                local_md5 = _md5(path)
                size = path.stat().st_size
                try:
                    remote = self.breaker.call(
                        partial(_properties, blob, self.timeout_s)
                    )
                except AzureError as exc:
                    raise RuntimeError(
                        f"Checking {blob_name} failed: {exc.__class__.__name__}"
                    ) from exc
                if remote is not None:
                    if remote == (size, local_md5):
                        logger.info(
                            "Already in %s/%s (same size and MD5): skipped",
                            container,
                            blob_name,
                        )
                        skipped.append(f"{container}/{blob_name}")
                        continue
                    if not replace:
                        raise BlobExistsError(f"{container}/{blob_name}")

                def send(
                    path: Path = path, blob: Any = blob, md5: bytes = local_md5
                ) -> None:
                    with path.open("rb") as data:
                        blob.upload_blob(
                            data,
                            overwrite=replace,
                            timeout=int(self.timeout_s),
                            content_settings=ContentSettings(
                                content_md5=bytearray(md5)
                            ),
                        )

                try:
                    self.breaker.call(send)
                    after = self.breaker.call(
                        partial(_properties, blob, self.timeout_s)
                    )
                except AzureError as exc:
                    raise RuntimeError(
                        f"Upload of {path.name} failed: {exc.__class__.__name__}"
                    ) from exc
                if after != (size, local_md5):
                    raise RuntimeError(
                        f"Verification failed for {container}/{blob_name}: size/MD5 differ from local"
                    )
                logger.info(
                    "Uploaded and verified %s -> %s/%s", path.name, container, blob_name
                )
                uploaded.append(f"{container}/{blob_name}")
        return UploadResult(uploaded=uploaded, skipped=skipped)

    def _match(self, names: list[str], pattern: str) -> list[str]:
        if "*" in pattern or "?" in pattern:
            return [n for n in names if fnmatch.fnmatchcase(n, pattern)]
        folder = pattern.rstrip("/") + "/"
        exact = [n for n in names if n == pattern]
        # A Spark output folder (".../2026-10-15_ar.csv.parquet/") means all its part files
        return exact or [n for n in names if n.startswith(folder)]

    def list_blobs(self, container: str, pattern: str) -> list[str]:
        prefix = pattern.split("*", 1)[0].split("?", 1)[0]
        with self._client() as service:
            container_client = service.get_container_client(container)
            try:
                names = self.breaker.call(
                    lambda: [
                        b.name
                        for b in container_client.list_blobs(name_starts_with=prefix)
                    ]
                )
            except AzureError as exc:
                raise RuntimeError(
                    f"Listing {container}/{prefix} failed: {exc.__class__.__name__}"
                ) from exc
        # Spark markers (_SUCCESS, _committed_*) and folders are not data
        return [
            n
            for n in self._match(names, pattern)
            if not PurePosixPath(n).name.startswith("_") and not n.endswith("/")
        ]

    def download(
        self,
        container: str,
        pattern: str,
        local_dir: Path,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[str]:
        names = self.list_blobs(container, pattern)
        if not names:
            raise FileNotFoundError(f"No blob matches {container}/{pattern}")
        local_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        with self._client() as service:
            container_client = service.get_container_client(container)
            for name in names:
                target = local_dir / PurePosixPath(name).name
                blob = container_client.get_blob_client(name)

                def fetch(
                    target: Path = target, blob: Any = blob, name: str = name
                ) -> None:
                    size = blob.get_blob_properties(timeout=int(self.timeout_s)).size
                    if target.is_file() and target.stat().st_size == size:
                        return  # already downloaded: re-running the step is cheap

                    def hook(done: int, total: int | None) -> None:
                        if progress is not None:
                            progress(name, done, total or size)

                    partial = target.with_suffix(target.suffix + ".part")
                    with partial.open("wb") as handle:
                        blob.download_blob(
                            timeout=int(self.timeout_s), progress_hook=hook
                        ).readinto(handle)
                    partial.replace(target)

                try:
                    self.breaker.call(fetch)
                except AzureError as exc:
                    raise RuntimeError(
                        f"Download of {name} failed: {exc.__class__.__name__}"
                    ) from exc
                logger.info("Downloaded %s/%s -> %s", container, name, target)
                files.append(str(target))
        return files
