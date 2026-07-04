import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["db_path"] = str(ROOT / cfg["db_path"])
    cfg["raw_dir"] = str(ROOT / cfg["raw_dir"])
    cfg["telegram"]["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    cfg["healthchecks_url"] = os.environ.get("HEALTHCHECKS_URL", "")
    return cfg
