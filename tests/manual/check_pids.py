from __future__ import annotations

from pathlib import Path
import sys

import psutil


pid_file = Path(sys.argv[1])
if not pid_file.exists():
    raise SystemExit(f"PID file not found: {pid_file}")

pids = [int(line) for line in pid_file.read_text(encoding="utf-8").splitlines()]
alive = []
for pid in pids:
    if not psutil.pid_exists(pid):
        continue
    process = psutil.Process(pid)
    if process.status() != psutil.STATUS_ZOMBIE:
        alive.append(pid)

print(f"recorded={pids} live={alive}")
raise SystemExit(1 if alive else 0)
