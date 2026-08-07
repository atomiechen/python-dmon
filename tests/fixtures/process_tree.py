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
parser.add_argument("--ignore-term", action="store_true")
args = parser.parse_args()


def stop(_signum: int, _frame: object) -> None:
    raise SystemExit(0)


signal.signal(signal.SIGTERM, signal.SIG_IGN if args.ignore_term else stop)
signal.signal(signal.SIGINT, stop)

if not args.child:
    child_command = [sys.executable, __file__, "--child"]
    if args.ignore_term:
        child_command.append("--ignore-term")
    child = subprocess.Popen(child_command)
    assert args.child_pid_file is not None
    args.child_pid_file.write_text(str(child.pid), encoding="utf-8")
    print(f"parent={os.getpid()} child={child.pid}", flush=True)

while True:
    time.sleep(0.05)
