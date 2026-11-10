# main.py
import logging
import time

import pandas as pd
import polars as pl

from config.settings import ACTIVE_COUNTRY, DATA_DIR, INPUT_FILE, OUTPUT_FILE
from src.adv_filters import apply_hours_and_fuzzy_filters
from src.chain_removal import filter_chains_and_duplicates
from src.crowded_property import filter_crowded_same_property
from src.drop_tracker import save_dropped_records
from src.final_regex import final_keyword_exclusion
from src.geo_dedup import balltree_spatial_deduplication
from src.normalize import normalize_names
from src.report import analyze_step_drop, generate_html_report
from src.utils import (
    deduplicate_records_with_audit,
    finalize_audit_report,
    init_audit_file,
    log_row_reduction,
    write_audit_step,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# ==========================================
# Adapter to standardize outputs
# ==========================================
def _run_module_1(df, items_to_track):
    """Wraps Module 1 so it returns (df, items, report, dropped) just like the others."""
    df_norm, df_dropped = deduplicate_records_with_audit(
        df=normalize_names(df),
        subset=["name_normalized", "latitude", "longitude"],
    )
    return df_norm, items_to_track, None, df_dropped


# ==========================================
# Pipeline Configuration
# ==========================================
PIPELINE_STEPS = {
    1: {
        "name": "Module 1: Normalization",
        "file": "01_normalized_deduped.csv",
        "func": _run_module_1,
    },
    2: {
        "name": "Module 2: Chain Filter",
        "file": "02_chains_filtered.csv",
        "func": lambda df, items: filter_chains_and_duplicates(
            df, filter_duplicates=False, max_appearances=4, items_to_track=items
        ),
    },
    3: {
        "name": "Module 3: BallTree Dedup",
        "file": "03_geo_balltree_deduped.csv",
        "func": lambda df, items: balltree_spatial_deduplication(
            df, radius_meters=50, items_to_track=items
        ),
    },
    4: {
        "name": "Module 4: Hours & Fuzzy",
        "file": "04_hours_fuzzy_filtered.csv",
        "func": lambda df, items: apply_hours_and_fuzzy_filters(
            df,
            min_hours=20,
            night_start=19,
            fuzzy_thresh=80,
            dist_m=100,
            items_to_track=items,
            apply_hours_filter=False,
        ),
    },
    5: {
        "name": "Module 5: Final Regex",
        "file": "05_external_regex_excluded.csv",
        "func": lambda df, items: final_keyword_exclusion(df, items_to_track=items),
    },
    6: {
        "name": "Module 6: Crowded Property",
        "file": "06_crowded_properties_filtered.csv",
        "func": lambda df, items: filter_crowded_same_property(
            df, threshold=4, radius_m=100.0, items_to_track=items
        ),
    },
}


def run_pipeline(
    modules_to_run, save_tracking=True, save_drops=True, items_to_track=None
):
    start_time = time.time()

    logging.info(
        f"Starting pipeline. Modules: {modules_to_run} | Auditing items: {items_to_track}"
    )
    print("=" * 50)
    print(f"🚀 STARTING PIPELINE FOR COUNTRY: {ACTIVE_COUNTRY.upper()}")
    print("=" * 50)
    print(f"📁 Input file: {INPUT_FILE}")
    print(f"📁 Output file: {OUTPUT_FILE}\n")

    # 1. Initialize Audit File (.txt)
    audit_file = init_audit_file(DATA_DIR, items_to_track)
    report_metrics = []

    df = pd.read_csv(INPUT_FILE, low_memory=False, encoding="utf-8")
    current_df = pl.from_pandas(df)
    initial_data_ref = current_df

    logging.info(f"Initial records: {len(current_df)}")

    # ==========================================
    # Dynamic Module Execution
    # ==========================================
    for mod_id in modules_to_run:
        if mod_id not in PIPELINE_STEPS:
            continue

        step = PIPELINE_STEPS[mod_id]
        logging.info(f"Executing {step['name']}...")

        prev_df = current_df

        # Execute the module-specific function.
        # Modules may return a 4th element: the dropped rows with a 'drop_reason' column.
        result = step["func"](current_df, items_to_track)
        if len(result) == 4:
            current_df, items_to_track, mod_report, dropped_df = result
        else:
            current_df, items_to_track, mod_report = result
            dropped_df = None

        # 2. Write module report to .txt audit file
        if mod_report:
            write_audit_step(
                audit_file, f"MODULE {mod_id} ({step['name']})", mod_report
            )

        # 3. Collect metrics for HTML report
        try:
            report_metrics.append(analyze_step_drop(prev_df, current_df, step["name"]))
        except Exception as e:
            logging.warning(f"Could not generate metrics for {step['name']}: {e}")

        # Save files
        if save_tracking:
            current_df.write_csv(
                DATA_DIR / "processed" / step["file"], include_bom=True
            )

        if save_drops:
            try:
                save_dropped_records(
                    prev_df,
                    current_df,
                    DATA_DIR,
                    step["file"],
                    save_drops,
                    dropped_df=dropped_df,
                )
            except Exception as e:
                logging.warning(f"Could not save drops for {step['name']}: {e}")

        log_row_reduction(prev_df, current_df, f"Module {mod_id}")

    # 4. Finalize audit file .txt
    finalize_audit_report(audit_file, current_df, items_to_track)

    # 5. Generate HTML Drop Report
    if report_metrics:
        try:
            generate_html_report(report_metrics, DATA_DIR)
        except Exception as e:
            logging.warning(f"Could not generate HTML report: {e}")

    log_row_reduction(initial_data_ref, current_df, "Full Pipeline Process")
    current_df.write_csv(OUTPUT_FILE, include_bom=True)

    elapsed = time.time() - start_time
    logging.info(f"Done in {elapsed / 60:.2f} mins. Final file saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    modules_to_run = [1, 2, 3, 4, 5, 6]

    # --- BOOLEANS TO CONTROL THE FLOW ---
    save_intermediate_csvs = True
    save_dropped_csvs = True

    # Elements to track during the pipeline
    track_these_elements = ["CLUB DE NUTRICION HERBALIFE"]

    run_pipeline(
        modules_to_run=modules_to_run,
        save_tracking=save_intermediate_csvs,
        save_drops=save_dropped_csvs,
        items_to_track=track_these_elements,
    )
