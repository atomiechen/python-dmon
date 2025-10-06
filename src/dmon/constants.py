from pathlib import Path
import re


DEFAULT_META_DIR = Path(".dmon")
DEFAULT_LOG_DIR = Path("logs")

META_SUFFIX = ".meta.json"

META_PATH_TEMPLATE = str(DEFAULT_META_DIR / ("{name}" + META_SUFFIX))
LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{name}.log")

DEFAULT_RUN_NAME = "default_run"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
