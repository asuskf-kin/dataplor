"""PrefilterPort adapters: territory (GeoJSON) and bottler-client proximity."""

from pathlib import Path

from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.adapters.streaming.client_proximity import (
    ClientProximityConfig,
    filter_dataplor_by_client_proximity,
)
from cleaning_agent.adapters.streaming.territory import (
    TerritoryFilterConfig,
    filter_dataplor_by_territory,
    resolve_parquet_files,
)
from cleaning_agent.domain.models import (
    ClientInputs,
    GeojsonInputs,
    OutputPaths,
    PrefilterResult,
)
from cleaning_agent.observability import get_logger

OUTSIDE_FILE = "territory_outside.parquet"


def _expect[T: OutputPaths](inputs: OutputPaths, model: type[T]) -> T:
    if not isinstance(inputs, model):
        raise TypeError(f"Expected {model.__name__}, got {type(inputs).__name__}")
    return inputs


class TerritoryPrefilter:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run(self, inputs: OutputPaths, correlation_id: str) -> PrefilterResult:
        geo = _expect(inputs, GeojsonInputs)
        output_csv = resolve(self.project_root, geo.raw_csv)
        outside = (
            resolve(self.project_root, geo.output_csv).parent / OUTSIDE_FILE
            if geo.save_outside
            else None
        )
        counts = filter_dataplor_by_territory(
            TerritoryFilterConfig(
                parquet_files=resolve_parquet_files(
                    resolve(self.project_root, geo.parquet)
                ),
                geojson_path=resolve(self.project_root, geo.geojson),
                output_csv=output_csv,
                # Same convention as report.ipynb: data/raw/<country>/<bottler>/file.csv
                bottler=geo.bottler or output_csv.parent.name,
                territory_columns=geo.territory_columns,
                only_active_open=geo.only_active_open,
                batch_size=geo.batch_size,
                max_batches=geo.max_batches,
                outside_output=outside,
            ),
            get_logger(correlation_id),
        )
        return PrefilterResult(
            output_csv=str(output_csv),
            counts=counts,
            extra_outputs=[str(outside)] if outside else [],
        )


class ClientProximityPrefilter:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run(self, inputs: OutputPaths, correlation_id: str) -> PrefilterResult:
        cli = _expect(inputs, ClientInputs)
        output_csv = resolve(self.project_root, cli.raw_csv)
        counts = filter_dataplor_by_client_proximity(
            ClientProximityConfig(
                parquet_files=resolve_parquet_files(
                    resolve(self.project_root, cli.parquet)
                ),
                clients_csv=resolve(self.project_root, cli.clients_csv),
                output_csv=output_csv,
                radius_m=cli.radius_m,
                client_lat_col=cli.client_lat_col,
                client_lon_col=cli.client_lon_col,
                only_active_open=cli.only_active_open,
                batch_size=cli.batch_size,
                max_batches=cli.max_batches,
            ),
            get_logger(correlation_id),
        )
        return PrefilterResult(output_csv=str(output_csv), counts=counts)
