from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


root = Path(__file__).resolve().parent
meta_dir = root / ".dmon"
force = "--force" in sys.argv[1:]

if any(meta_dir.glob("*.meta.json")):
    result = subprocess.run(
        [sys.executable, "-m", "dmon", "stop", "--all"],
        cwd=root,
        check=False,
    )
    if result.returncode and not force:
        raise SystemExit(
            "dmon could not stop every recorded task; state was preserved. "
            "Inspect it, then use 'python reset.py --force' only when safe."
        )

for directory in (
    meta_dir,
    root / "logs",
    root / "state",
    root / "__pycache__",
    root / "services" / "__pycache__",
):
    if directory.exists():
        shutil.rmtree(directory)

print("Manual lab runtime state cleared." + (" (forced)" if force else ""))
