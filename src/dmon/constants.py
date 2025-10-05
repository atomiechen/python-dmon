from pathlib import Path


DEFAULT_META_DIR = Path(".dmon")
DEFAULT_LOG_DIR = Path("logs")

META_PATH_TEMPLATE = str(DEFAULT_META_DIR / "{name}.meta.json")
LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{name}.log")
