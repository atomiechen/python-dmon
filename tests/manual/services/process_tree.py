from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


running = True


def stop(signum: int, _frame: object) -> None:
    global running
    print(f"pid={os.getpid()} received signal {signum}", flush=True)
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

if "--leaf" in sys.argv:
    print(f"leaf started pid={os.getpid()} ppid={os.getppid()}", flush=True)
else:
    pid_file = Path(sys.argv[1])
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([sys.executable, __file__, "--leaf"])
    pid_file.write_text(f"{os.getpid()}\n{child.pid}\n", encoding="utf-8")
    print(f"parent started pid={os.getpid()} child={child.pid}", flush=True)

while running:
    time.sleep(0.1)
