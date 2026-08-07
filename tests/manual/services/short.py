from __future__ import annotations

import os
import time


print(f"short task started pid={os.getpid()}", flush=True)
time.sleep(0.3)
print("short task exits with code 7", flush=True)
raise SystemExit(7)
