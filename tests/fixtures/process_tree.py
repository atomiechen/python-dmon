from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


parser = argparse.ArgumentParser()
parser.add_argument("--child", action="store_true")
parser.add_argument("--child-pid-file", type=Path)
args = parser.parse_args()


def stop(_signum: int, _frame: object) -> None:
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

if not args.child:
    child = subprocess.Popen([sys.executable, __file__, "--child"])
    assert args.child_pid_file is not None
    args.child_pid_file.write_text(str(child.pid), encoding="utf-8")
    print(f"parent={os.getpid()} child={child.pid}", flush=True)

while True:
    time.sleep(0.05)
