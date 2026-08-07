from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import time


signal_file = Path(sys.argv[1])


def stop(signum: int, _frame: object) -> None:
    with signal_file.open("a", encoding="utf-8") as output:
        output.write(f"{signum}\n")
    time.sleep(0.2)
    raise SystemExit(0)


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
print(os.getpid(), flush=True)

while True:
    time.sleep(0.05)
