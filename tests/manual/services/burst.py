from __future__ import annotations

import os
import time


print(f"burst started pid={os.getpid()}", flush=True)
for index in range(4000):
    print(f"burst line {index:04d}: " + "x" * 80, flush=True)
time.sleep(30)
