"""Keep a child alive after a test-controlled parent exit."""

from pathlib import Path
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
while not Path(sys.argv[2]).exists():
    time.sleep(0.02)
