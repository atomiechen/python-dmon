from __future__ import annotations

import os
import time


print(f"delayed failure started pid={os.getpid()}", flush=True)
time.sleep(1)
print("delayed failure exits with code 9", flush=True)
raise SystemExit(9)
