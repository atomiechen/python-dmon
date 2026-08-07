from __future__ import annotations

import os
import signal
import time


running = True


def stop(signum: int, _frame: object) -> None:
    global running
    print(f"heartbeat received signal {signum}", flush=True)
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

print(f"heartbeat started pid={os.getpid()}", flush=True)
counter = 0
while running:
    print(f"tick {counter}", flush=True)
    counter += 1
    time.sleep(0.5)
print("heartbeat stopped cleanly", flush=True)
