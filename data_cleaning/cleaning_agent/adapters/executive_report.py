"""ExecutiveReportPort adapter: the executive report formerly built by report.ipynb."""

from pathlib import Path

from cleaning_agent.adapters.executive_report_builder import generate_executive_report
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.domain.models import ExecutiveReportOutcome

# Premise answered in the intake -> channel label used by the report and its file names
PREMISE_CHANNEL = {
    "on_premise": "On Premise",
    "off_premise": "Off Premise",
    "ambos": None,
}


class FileExecutiveReport:
    def __init__(
        self, project_root: Path, dropped_dir: Path, out_dir: Path, name_template: str
    ) -> None:
        self.project_root = project_root
        self.dropped_dir = dropped_dir
        self.out_dir = out_dir
        self.name_template = name_template

    def generate(
        self,
        raw_csv: str,
        output_csv: str,
        country: str,
        bottler: str,
        premise: str,
        correlation_id: str,
    ) -> ExecutiveReportOutcome:
        result = generate_executive_report(
            resolve(self.project_root, raw_csv),
            resolve(self.project_root, output_csv),
            self.dropped_dir,
            self.out_dir,
            country=country,
            bottler=bottler,
            channel=PREMISE_CHANNEL.get(premise),
            name_template=self.name_template,
            correlation_id=correlation_id,
        )
        return ExecutiveReportOutcome(
            files=[str(f) for f in result.files], summary=result.summary
        )
