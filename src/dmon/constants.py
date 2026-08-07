from pathlib import Path
import sys


DEFAULT_META_DIR = Path(".dmon")
DEFAULT_LOG_DIR = Path("logs")

META_SUFFIX = ".meta.json"
STACK_META_SUFFIX = ".stack.json"

META_PATH_TEMPLATE = str(DEFAULT_META_DIR / ("{task}" + META_SUFFIX))
LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{task}.log")
ROTATE_LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{task}.rotate.log")
STACK_META_PATH_TEMPLATE = str(DEFAULT_META_DIR / ("{stack}" + STACK_META_SUFFIX))
STACK_LOG_PATH_TEMPLATE = str(DEFAULT_LOG_DIR / "{stack}.stack.log")


DEFAULT_RUN_NAME = "default_run"

ON_WINDOWS = sys.platform.startswith("win")
