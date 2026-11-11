"""Domain contracts (Pydantic). They validate every human answer at the boundary.

The graph state stores only JSON-friendly ``model_dump()`` output: the SQLite
checkpointer and the ``interrupt`` payloads must stay serialisable.
"""

import re
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

MAX_PATH_LENGTH = 1024
# Azure container rules: 3-63 chars, lowercase letters, digits and single hyphens
AZURE_CONTAINER = r"^(?!-)(?!.*--)[a-z0-9-]{3,63}(?<!-)$"
MAX_NOTE_LENGTH = 2000


class CleaningMode(StrEnum):
    """How the raw Dataplor export is narrowed before the cleaning modules."""

    GEOJSON = "geojson"
    CLIENTES_BOTTLER = "clientes_bottler"
    NINGUNO = "ninguno"


MODE_LABELS: dict[CleaningMode, str] = {
    CleaningMode.GEOJSON: "GeoJSON: cruzar Dataplor con el territorio del embotellador",
    CleaningMode.CLIENTES_BOTTLER: "Clientes bottler: Dataplor cerca de los clientes del embotellador",
    CleaningMode.NINGUNO: "Ninguno: usar un CSV de Dataplor ya preparado",
}


class _Answer(BaseModel):
    # Unknown fields are rejected: a typo in a key must not be silently ignored
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ModeAnswer(_Answer):
    mode: CleaningMode


class Channel(StrEnum):
    TRADICIONAL = "tradicional"
    MODERNO = "moderno"


class Premise(StrEnum):
    OFF_PREMISE = "off_premise"
    ON_PREMISE = "on_premise"
    AMBOS = "ambos"


class IntakeAnswer(_Answer):
    """First questions of every run, in the order the user asked for."""

    country: str = Field(
        pattern=r"^[A-Za-z]{2}$", description="País, ISO 2 (mx, pe, br...)"
    )
    bottler: str = Field(pattern=r"^[A-Za-z0-9 _-]{1,60}$", description="Embotellador")
    channel: Channel = Field(description="tradicional | moderno")
    premise: Premise = Field(description="off_premise | on_premise | ambos")
    dataplor_raw: str = Field(
        description="Dataplor raw: .parquet (or glob part-*.parquet) or .csv"
    )

    @field_validator("country")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()

    @field_validator("dataplor_raw")
    @classmethod
    def _raw(cls, value: str) -> str:
        return _check_path(value, (".parquet", ".csv"))


def raw_blob_location(path: str, raw_container: str) -> tuple[str, str] | None:
    """``dataplorraw/<blob>`` -> (container, blob). Only the raw Dataplor uses this default.

    Anything else (an existing local file, a path in another container) returns None
    and is treated as a local path.
    """
    normalized = path.replace("\\", "/").strip()
    for prefix in (f"{raw_container}/", f"az://{raw_container}/"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            return raw_container, normalized[len(prefix) :]
    return None


def blob_location(path: str) -> tuple[str, str] | None:
    """``<container>/<blob>`` -> (container, blob) when the first segment is a valid
    Azure container name. Callers check the local disk first: a local path wins."""
    normalized = path.replace("\\", "/").strip().removeprefix("az://")
    container, _, blob = normalized.partition("/")
    if blob and re.fullmatch(AZURE_CONTAINER, container):
        return container, blob
    return None


class CleaningType(StrEnum):
    DISTANCIA = "distancia"  # GeoJSON of the bottler territory
    CLIENT_BOTTLER = "client_bottler"  # bottler client base


class CleaningChoice(_Answer):
    """¿Va a limpiar el Dataplor? and, if so, how."""

    clean: bool
    type: CleaningType | None = None

    @model_validator(mode="after")
    def _type_when_cleaning(self) -> Self:
        if self.clean and self.type is None:
            raise ValueError(
                "type is required when clean is true (distancia | client_bottler)"
            )
        return self

    @property
    def mode(self) -> CleaningMode:
        if not self.clean:
            return CleaningMode.NINGUNO
        if self.type == CleaningType.DISTANCIA:
            return CleaningMode.GEOJSON
        return CleaningMode.CLIENTES_BOTTLER


def _check_path(value: str, suffixes: tuple[str, ...]) -> str:
    if not value or len(value) > MAX_PATH_LENGTH:
        raise ValueError(f"path must have 1-{MAX_PATH_LENGTH} characters")
    if "\x00" in value:
        raise ValueError("path contains a null byte")
    if not value.lower().endswith(suffixes):
        raise ValueError(f"path must end with {' or '.join(suffixes)}")
    return value


class OutputPaths(_Answer):
    """Where the cleaning input CSV lives (or is written) and where the result goes."""

    raw_csv: str = Field(description="CSV that the cleaning modules read")
    output_csv: str = Field(description="Final cleaned CSV")

    # Which files may feed the cleaning modules (subclasses widen it)
    RAW_SUFFIXES: ClassVar[tuple[str, ...]] = (".csv",)

    @field_validator("raw_csv", "output_csv")
    @classmethod
    def _csv(cls, value: str, info: ValidationInfo) -> str:
        suffixes = cls.RAW_SUFFIXES if info.field_name == "raw_csv" else (".csv",)
        return _check_path(value, suffixes)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if Path(self.raw_csv) == Path(self.output_csv):
            raise ValueError("raw_csv and output_csv must be different files")
        return self


class _ParquetSource(_Answer):
    parquet: str = Field(
        description="Raw Dataplor Parquet path or glob (part-*.parquet)"
    )
    only_active_open: bool = True
    batch_size: PositiveInt = Field(200_000, le=2_000_000)
    max_batches: PositiveInt | None = Field(None, description="null = whole file")

    @field_validator("parquet")
    @classmethod
    def _parquet(cls, value: str) -> str:
        return _check_path(value, (".parquet",))


class GeojsonInputs(OutputPaths, _ParquetSource):
    geojson: str
    bottler: str = Field("", max_length=100, description="Empty = folder of raw_csv")
    territory_columns: list[str] = Field(default_factory=list, max_length=20)
    save_outside: bool = False

    @field_validator("geojson")
    @classmethod
    def _geojson(cls, value: str) -> str:
        return _check_path(value, (".geojson", ".json"))


class ClientInputs(OutputPaths, _ParquetSource):
    clients_csv: str
    client_lat_col: str = Field("Coord_Y", min_length=1, max_length=100)
    client_lon_col: str = Field("Coord_X", min_length=1, max_length=100)
    radius_m: float = Field(900, gt=0, le=50_000)

    @field_validator("clients_csv")
    @classmethod
    def _clients(cls, value: str) -> str:
        return _check_path(value, (".csv",))


class NoPrefilterInputs(OutputPaths):
    """Mode 'ninguno': the raw Dataplor goes straight to the cleaning modules."""

    RAW_SUFFIXES: ClassVar[tuple[str, ...]] = (".csv", ".parquet")


INPUT_MODELS: dict[CleaningMode, type[OutputPaths]] = {
    CleaningMode.GEOJSON: GeojsonInputs,
    CleaningMode.CLIENTES_BOTTLER: ClientInputs,
    CleaningMode.NINGUNO: NoPrefilterInputs,
}


class PlanDecision(_Answer):
    """Answer to the plan review: approve, and optionally change the module list."""

    approved: bool
    modules: list[int] | None = Field(None, max_length=10)
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)


class OutputDecision(_Answer):
    """Answer to the final review: publish the cleaned CSV or discard it."""

    approved: bool
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)


class PrefilterResult(BaseModel):
    """What a pre-filter adapter reports back to the graph."""

    output_csv: str
    counts: dict[str, int]
    extra_outputs: list[str] = Field(default_factory=list)


class StepMetric(BaseModel):
    """Rows dropped by one cleaning module (feeds the HTML report and the review)."""

    module_id: int
    step_name: str
    rows_before: int
    rows_after: int
    top_dropped: list[tuple[str, int]] = Field(default_factory=list)

    @property
    def dropped(self) -> int:
        return self.rows_before - self.rows_after


# --- Datamatch (Front) + QA + Azure -------------------------------------------------
SAFE_NAME = r"^[A-Za-z0-9_-]{1,60}$"


class DatamatchChoice(_Answer):
    run_datamatch: bool


class DatamatchInputs(_Answer):
    """Files coming back from the Front (Datamatch is run in the Kin web app)."""

    datamatch_file: str = Field(description="Matcher output downloaded from the Front")
    clients_file: str = Field(description="Bottler POS client base")
    client_name: str = Field(pattern=SAFE_NAME, description="Used in the QA file names")
    # JSON of the Front step (parameters of that Datamatch run); its file name names
    # the step folder in silver (paso1.json -> .../qa_process/<fecha>/paso1/)
    step_json: str = Field("", description="Front JSON of this Datamatch step")
    # Filled from the run context, not asked again
    country: str = Field("", max_length=2)

    @field_validator("step_json")
    @classmethod
    def _step_json(cls, value: str) -> str:
        return _check_path(value, (".json",)) if value else value

    @field_validator("datamatch_file")
    @classmethod
    def _datamatch(cls, value: str) -> str:
        return _check_path(value, (".csv", ".xlsx", ".parquet"))

    @field_validator("clients_file")
    @classmethod
    def _clients(cls, value: str) -> str:
        return _check_path(value, (".csv", ".xlsx"))


class ThresholdDecision(_Answer):
    """Thresholds chosen after reading the QA explore report."""

    match: float = Field(ge=0, le=1)
    super_match: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.super_match < self.match:
            raise ValueError("super_match cannot be lower than match")
        return self


class UploadDecision(_Answer):
    """Explicit approval before anything leaves the machine."""

    approved: bool
    container: str = Field("", max_length=63)
    blob_prefix: str = Field("", max_length=MAX_PATH_LENGTH)
    # Guideline: existing blobs are never replaced unless the person says so explicitly
    replace: bool = False
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)

    @model_validator(mode="after")
    def _target(self) -> Self:
        if not self.approved:
            return self
        if not re.fullmatch(AZURE_CONTAINER, self.container):
            raise ValueError(
                "container: 3-63 lowercase letters, digits or single hyphens"
            )
        parts = self.blob_prefix.strip("/").split("/")
        if not self.blob_prefix.strip("/") or any(p in {"", ".", ".."} for p in parts):
            raise ValueError("blob_prefix: non-empty, no empty, '.' or '..' segments")
        return self


class QAExploreResult(BaseModel):
    report_html: str
    output_dir: str


class QARunResult(BaseModel):
    files: list[str]
    output_dir: str


class DatamatchStepResult(BaseModel):
    """One Datamatch step: the reduced client base, the matches and the Excel report."""

    files: list[str]
    clients_file: str
    summary: dict[str, Any]


class ProspectsResult(BaseModel):
    """Cleaned Dataplor minus the points the bottler already has as clients."""

    file: str
    known_ids: int
    known_in_file: int
    rows_in: int
    rows_out: int


class DatamatchLoopDecision(_Answer):
    """After each step: run another Datamatch step, or the loop is done."""

    done: bool
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)


class UploadResult(BaseModel):
    uploaded: list[str]
    # Already in the blob with the same size and MD5: not uploaded again (guideline)
    skipped: list[str] = Field(default_factory=list)


# --- Priorización ---------------------------------------------------------------------
class PriorizacionDecision(_Answer):
    """Whether to run priorización and with which base run YAML of that repo."""

    run: bool
    base_config: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,80}\.ya?ml$")
    period: str | None = Field(
        None, pattern=r"^20\d{2}(0[1-9]|1[0-2])$", description="AAAAMM"
    )
    # Cleaned CSV in Azure (<container>/<blob>) and the folder for the outputs
    input_blob: str | None = Field(None, max_length=MAX_PATH_LENGTH)
    output_dir: str = Field("", max_length=MAX_PATH_LENGTH)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.run and (self.base_config is None or self.period is None):
            raise ValueError("base_config and period are required to run priorización")
        return self


class PriorizacionRun(BaseModel):
    """What a priorización run reads and writes (resolved before building its YAML)."""

    input_blob: str
    input_container: str
    output_container: str
    output_dir: str
    step1_name: str
    step2_name: str
    geodata_prefix: str
    run_name: str


class ClientColumns(BaseModel):
    """Columns of the bottler's client base the gold package reads."""

    id: str = "pos_id"
    latitude: str = "pos_latitude"
    longitude: str = "pos_longitude"
    city: str = "pos_city"
    # Nearest-client columns of the BOTTLER version (ref_<column>_cercano)
    reference: list[str] = Field(
        default_factory=lambda: ["pos_id", "pos_gerencia", "pos_name", "pos_jefatura"]
    )


class GoldPackageRequest(BaseModel):
    """One gold delivery package (KO / BOTTLER results, Excel, maps, deck)."""

    scored_file: str
    clients_file: str
    territory_geojson: str = ""
    out_dir: Path
    bottler: str
    bottler_label: str
    # How the client is named on the deck (e.g. "Coca-Cola Andina")
    client_label: str
    country: str
    country_name: str
    country_label: str
    period: str
    period_label: str
    clients_total: int
    dataplor_total: int
    matched: int
    run_name: str
    contacts: list[str] = Field(default_factory=list)
    client_columns: ClientColumns = Field(default_factory=ClientColumns)

    def names(self) -> dict[str, str]:
        base = f"{self.bottler}_{self.country}_{self.period}"
        return {
            "xlsx": f"{self.bottler}_{self.country_name}_analisis_oportunidad_on_premise_{self.period}.xlsx",
            "deck": f"prospecting_{self.bottler}_{self.country_name}_{self.period}.pptx",
            "ko_csv": f"dataplor_on_premise_priority_{base}_ko.csv",
            "bottler_csv": f"dataplor_on_premise_priority_{base}_bottler.csv",
            "ko_map": f"prospection_map_{self.bottler}_ko.html",
            "bottler_map": f"prospection_map_{self.bottler}_bottler.html",
        }


class GoldPackageResult(BaseModel):
    root: list[str]
    ko: list[str]
    bottler: list[str]
    rows: int
    ko_rows: int
    bottler_rows: int
    ko_column_names: list[str]
    bottler_columns: int
    prioritized: int
    # The client base had latitude/longitude in each other's column (fixed, flagged)
    client_coordinates_swapped: bool = False
    figures: dict[str, Any]


class PriorizacionResult(BaseModel):
    config_path: str
    outputs: list[str]  # container/blob paths written by priorización


class ExecutiveReportOutcome(BaseModel):
    files: list[str]
    summary: dict[str, int | float | str]


class FrontResult(_Answer):
    """Result of the Front step after bronze: the file to clean and its JSON (blobs or local)."""

    result_file: str = Field(description="Result of the Front step (.csv or .parquet)")
    metadata_json: str = Field(description="JSON of that step")

    @field_validator("result_file")
    @classmethod
    def _result(cls, value: str) -> str:
        return _check_path(value, (".csv", ".parquet"))

    @field_validator("metadata_json")
    @classmethod
    def _json(cls, value: str) -> str:
        return _check_path(value, (".json",))


class PatternsDecision(_Answer):
    """OK to the created/updated country patterns (after seeing the diff)."""

    approved: bool
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)


class FranchiseFlag(_Answer):
    name: str = Field(min_length=1, max_length=200)
    marca: str = Field(min_length=1, max_length=100)


class FranchiseReview(_Answer):
    """Claude Code's review: franchises still present (exact names) or a CSV with them."""

    flagged: list[FranchiseFlag] = Field(default_factory=list, max_length=20_000)
    flagged_file: str | None = None

    @field_validator("flagged_file")
    @classmethod
    def _csv_file(cls, value: str | None) -> str | None:
        return None if value is None else _check_path(value, (".csv",))


class FranchiseDecision(_Answer):
    remove: bool
    note: str | None = Field(None, max_length=MAX_NOTE_LENGTH)
