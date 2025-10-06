from pathlib import Path


DEFAULT_META_DIR = Path(".dmon")
DEFAULT_LOG_DIR = Path("logs")

META_SUFFIX = ".meta.json"

META_PATH_TEMPLATE = str(DEFAULT_META_DIR / ("{name}" + META_SUFFIX))
LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{name}.log")
ROTATE_LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{name}.rotate.log")


DEFAULT_RUN_NAME = "default_run"
