from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)

if "--leaf" in sys.argv:
    print(f"stubborn leaf pid={os.getpid()} ppid={os.getppid()}", flush=True)
else:
    pid_file = Path(sys.argv[1])
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([sys.executable, __file__, "--leaf"])
    pid_file.write_text(f"{os.getpid()}\n{child.pid}\n", encoding="utf-8")
    print(f"stubborn parent pid={os.getpid()} child={child.pid}", flush=True)

while True:
    time.sleep(0.1)
