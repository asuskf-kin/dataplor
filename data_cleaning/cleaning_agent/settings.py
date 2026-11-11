# config/settings.py
from pathlib import Path
from typing import Any

import yaml

# 1. Automatically define the project root directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 2. Define the exact path to the YAML configuration file.
YAML_PATH = PROJECT_ROOT / "config.yaml"

# 3. Read and parse the YAML file safely.
with open(YAML_PATH, "r", encoding="utf-8") as file:
    config_data = yaml.safe_load(file)

# 4. The country, bottler and paths are chosen per run by the agent (intake).

# Module 0 (nightlife filter) options. It runs only if 0 is in modules_to_run.
NIGHTLIFE_SETTINGS = {
    "include_probable": True,
    "include_night_hours": True,
    "night_close_hour": 21,
    "late_open_hour": 16,
    **(config_data.get("nightlife_filter") or {}),
}

# 5. Extract the path strings from the YAML.
_data_dir_path = config_data["paths"]["data_dir"]

# 6. Build exact, OS-independent file paths using pathlib.
DATA_DIR = PROJECT_ROOT / _data_dir_path

# Agent defaults (cleaning_agent). Validated by its Pydantic models, not here.
AGENT_SETTINGS = {
    "default_modules": [1, 2, 3, 4, 5, 6],
    "items_to_track": [],
    "checkpoints": "data/checkpoints.sqlite",
    "runs_dir": "data/runs",
    "max_input_attempts": 3,
    **(config_data.get("agent") or {}),
}
# Defaults proposed to the human for each cleaning mode
TERRITORY_SETTINGS = dict(config_data.get("territory_filter") or {})
CLIENT_SETTINGS = dict(config_data.get("client_filter") or {})
DATAMATCH_SETTINGS = {
    "front_url": "",
    "qa_project_dir": "../../QA_datamatch",
    "qa_timeout_s": 1800,
    "clients_file": "",
    "thresholds": {"match": 0.71, "super_match": 0.80},
    **(config_data.get("datamatch") or {}),
}
PRIORIZACION_SETTINGS = {
    "repo_dir": "../../Priorizacion_On_Premise",
    "timeout_s": 3600,
    **(config_data.get("priorizacion") or {}),
}
REPORT_SETTINGS = {
    "nombre": "reporte_ejecutivo_{pais}_{canal}_{bottler}_{fecha}",
    **(config_data.get("reporte") or {}),
}
RAW_SETTINGS = {
    "container": "dataplorraw",
    "local_dir": "data/raw",
    "front_container": "prospection-datacleaning",
    **(config_data.get("dataplor_raw") or {}),
}
DWH_SETTINGS = {
    "container": "prospecting-data",
    "path_template": "{layer}/ko/{pais}/{bottler}/dataplor/{fecha}",
    "mirror_dir": "data",
    **(config_data.get("dwh") or {}),
}
BRAND_SETTINGS = {
    # Skill brand-guidelines-kin: fonts, tokens and logos for every HTML deliverable
    "assets_dir": ".claude/skills/brand-guidelines-kin/assets",
    **(config_data.get("brand") or {}),
}
GOLD_PACKAGE_SETTINGS: dict[str, Any] = {
    # Approved Golfo deck with the client removed (scripts/build_prospecting_deck_template.py)
    "deck_template": "cleaning_agent/adapters/assets/prospecting_deck_template.pptx",
    "client_label": "Coca-Cola {bottler}",
    "contacts": [],
    "client_columns": {},
    **(config_data.get("gold_package") or {}),
}
AZURE_SETTINGS = {
    "container": "",
    "blob_prefix": "prospeccion/{country}/{bottler}/{date}",
    "timeout_s": 120,
    "max_attempts": 3,
    **(config_data.get("azure_storage") or {}),
}
