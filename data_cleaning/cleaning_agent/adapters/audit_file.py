"""Tracked-items audit trail (data/audit/*.txt)."""

import logging
import time
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def init_audit_file(data_dir: Path, items_to_track: list[str]) -> Path | None:
    """
    Creates the audit directory and the base file if there are items to track.
    Returns the file path or None if auditing is disabled.
    """
    if not items_to_track:
        return None

    audit_dir = data_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    audit_file = audit_dir / f"audit_report_{timestamp}.txt"

    with open(audit_file, "w", encoding="utf-8") as f:
        f.write("====================================================\n")
        f.write(f"🚀 AUDIT REPORT STARTED: {timestamp}\n")
        f.write(f"🎯 Tracked items: {items_to_track}\n")
        f.write("====================================================\n\n")

    logger.info(f"Audit activated. File created at: {audit_file}")
    return audit_file


def write_audit_step(audit_file: Path, module_name: str, report_text: str) -> None:
    """
    Appends the report of a specific module to the audit file.
    """
    if audit_file and report_text:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- {module_name} ---\n{report_text}\n")


def finalize_audit_report(
    audit_file: Path, final_df: pl.DataFrame, items_to_track: list[str]
) -> None:
    """
    Evaluates the final DataFrame against the tracked items and writes the verdict.
    """
    if not audit_file or not items_to_track:
        return

    with open(audit_file, "a", encoding="utf-8") as f:
        f.write("\n====================================================\n")
        f.write("🏁 FINAL SUMMARY: DID IT REACH THE END OR WAS IT DROPPED?\n")
        f.write("====================================================\n")

        for text in items_to_track:
            # Filter the final DF to see if the item survived
            survivors = final_df.filter(
                pl.col("name_normalized")
                .str.to_lowercase()
                .str.contains(text.lower(), literal=True)
            )

            if len(survivors) > 0:
                f.write(
                    f"✅ '{text}': REACHED THE END ({len(survivors)} intact records).\n"
                )
            else:
                f.write(f"❌ '{text}': COMPLETELY DROPPED in some pipeline step.\n")

    logger.info("Final audit summary saved successfully.")
