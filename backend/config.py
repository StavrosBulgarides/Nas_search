import logging
import os
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yml")
DB_PATH = os.environ.get("DB_PATH", "/app/data/nas_search.db")

_config = None


def load_config() -> dict:
    global _config
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.warning("Config file not found at %s, using defaults", CONFIG_PATH)
        _config = _defaults()
        return _config
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        _config = {**_defaults(), **raw}
        folders = _config.get("indexed_folders", {})
        extensions = _config.get("extensions", [])
        logger.info(
            "Config loaded: %d folder(s) configured, extensions=%s, schedule=%02d:%02d",
            len(folders), extensions,
            _config.get("schedule_hour", 2), _config.get("schedule_minute", 0),
        )
        for label, path in folders.items():
            logger.info("  Folder: %s -> %s", label, path)
        return _config
    except Exception:
        logger.exception("Failed to load config from %s, using defaults", CONFIG_PATH)
        _config = _defaults()
        return _config


def save_config(cfg: dict):
    global _config
    try:
        _config = cfg
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        logger.info("Config saved to %s", CONFIG_PATH)
        logger.info(
            "  Folders: %s, Extensions: %s, Schedule: %02d:%02d",
            list(cfg.get("indexed_folders", {}).keys()),
            cfg.get("extensions", []),
            cfg.get("schedule_hour", 2), cfg.get("schedule_minute", 0),
        )
    except Exception:
        logger.exception("Failed to save config to %s", CONFIG_PATH)
        raise


def get_config() -> dict:
    if _config is None:
        return load_config()
    return _config


def _defaults() -> dict:
    return {
        "indexed_folders": {},
        "extensions": ["epub", "pdf"],
        "max_results": 100,
        "fuzzy_threshold": 80,
        "schedule_hour": 2,
        "schedule_minute": 0,
        "host": "0.0.0.0",
        "port": 8080,
    }
