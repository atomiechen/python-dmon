"""Build and test the clean Git commit; collect evidence in .local/validation."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.13", choices=["3.8", "3.13"])
    args = parser.parse_args()
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv is required; see docs/windows-validation.md")

    def git(*arguments):
        return subprocess.check_output(
            ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()

    if git("status", "--porcelain"):
        parser.error(
            "Commit intended changes first; validation requires a clean checkout"
        )
    commit = git("rev-parse", "HEAD")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = ROOT / ".local" / "validation" / (stamp + "-" + args.python)
    out = root / "evidence"
    out.mkdir(parents=True)
    source = root / "source"
    archive = root / "source.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "--output", str(archive), commit],
        cwd=ROOT,
        check=True,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(source)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONUTF8="1")
    env.setdefault("UV_PYTHON_INSTALL_DIR", str(ROOT / ".local" / "python"))
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".local" / "uv-cache"))
    report = {
        "commit": commit,
        "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "native_windows": sys.platform == "win32",
        "requested_python": args.python,
        "commands": [],
        "manual_checks": "pending; see docs/windows-validation.md",
        "cleanup_review": "pending; review test-owned process identities",
        "note": "Unreleased checkout build; package version alone is not its identity",
    }

    def save():
        (out / "results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    def run(name, arguments, cwd=source, required=True, timeout=600):
        print("Running " + name, flush=True)
        entry = {"name": name, "argv": [str(x) for x in arguments], "cwd": str(cwd)}
        report["commands"].append(entry)
        with (out / (name + ".log")).open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    entry["argv"],
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
                entry["exit_code"] = result.returncode
            except subprocess.TimeoutExpired:
                entry["timed_out"] = True
                save()
                raise RuntimeError(name + " timed out; inspect test-owned children")
        save()
        if required and result.returncode:
            raise RuntimeError(name + " failed; see its log")
        return result.returncode

    try:
        run("uv-version", [uv, "--version"])
        venv = root / "venv"
        run("create-env", [uv, "venv", "--python", args.python, venv])
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirements = root / "requirements.txt"
        run(
            "export-runtime",
            [
                uv,
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                requirements,
            ],
        )
        run(
            "dependencies",
            [
                uv,
                "pip",
                "install",
                "--python",
                python,
                "--require-hashes",
                "-r",
                requirements,
            ],
        )
        wheels = root / "wheels"
        run("build", [uv, "build", "--wheel", "--python", python, "--out-dir", wheels])
        (wheel,) = wheels.glob("*.whl")
        report["wheel"] = {
            "name": wheel.name,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }
        # Verify packaged Python bytes against the exact committed source.
        with zipfile.ZipFile(wheel) as bundle:
            for file in (source / "src/dmon").rglob("*.py"):
                assert (
                    bundle.read(file.relative_to(source / "src").as_posix())
                    == file.read_bytes()
                )
        report["wheel_source_matches_commit"] = True
        run(
            "install-wheel",
            [uv, "pip", "install", "--python", python, "--no-deps", wheel],
        )
        run(
            "import-identity",
            [
                python,
                "-c",
                "import dmon,sys,pathlib,importlib.metadata as m; "
                "p=pathlib.Path(dmon.__file__).resolve(); "
                "print(sys.version, m.version('python-dmon'), p); "
                "assert pathlib.Path(sys.prefix).resolve() in p.parents",
            ],
            cwd=root,
        )
        run(
            "unittest",
            [python, "-m", "unittest", "discover", "-s", source / "tests", "-v"],
            cwd=root,
            required=False,
        )
        run(
            "export-dev",
            [
                uv,
                "export",
                "--locked",
                "--no-emit-project",
                "--output-file",
                requirements,
            ],
        )
        if (
            run(
                "dev-dependencies",
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    python,
                    "--require-hashes",
                    "-r",
                    requirements,
                ],
                required=False,
                timeout=180,
            )
            == 0
        ):
            run(
                "ruff-check",
                [python, "-m", "ruff", "check", "src", "tests", "scripts"],
                required=False,
            )
            run(
                "ruff-format",
                [python, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
                required=False,
            )
        report["automated_checks_passed"] = all(
            item.get("exit_code") == 0 for item in report["commands"]
        )
    except Exception:
        report["error"] = traceback.format_exc()
        report["automated_checks_passed"] = False
        print(report["error"], file=sys.stderr)
    finally:
        save()
        evidence_zip = root / "evidence.zip"
        with zipfile.ZipFile(evidence_zip, "w", zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted(out.iterdir()):
                bundle.write(file, file.name)
        print("Evidence: " + str(evidence_zip), flush=True)
        print("Native terminal checks and cleanup review remain separate.")
    return 0 if report.get("automated_checks_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
