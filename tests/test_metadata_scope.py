from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import psutil
import yaml

from dmon.control import check_running
from dmon.types import DmonMeta, DmonStackMeta


class MetadataScopeTest(unittest.TestCase):
    def run_dmon(self, root, *args):
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )

    @contextmanager
    def running(self, root, *, stack):
        root.mkdir()
        (root / "dmon.yaml").write_text(
            yaml.safe_dump(
                {
                    "tasks": {
                        "api": {
                            "cmd": [
                                sys.executable,
                                "-c",
                                "import time; time.sleep(60)",
                            ],
                            "ready": {
                                "command": [sys.executable, "-c", "raise SystemExit(0)"]
                            },
                        }
                    },
                    "stacks": {"dev": ["api"]},
                }
            ),
            encoding="utf-8",
        )
        records = []
        try:
            result = self.run_dmon(
                root, *(["stack", "up", "-d", "dev"] if stack else ["start", "api"])
            )
            # Capture only this test's identities, also on a failed assertion.
            for path in (root / ".dmon").glob("*.json"):
                records.append(json.loads(path.read_text()))
            self.assertEqual(result.returncode, 0, result.stderr)
            yield json.loads((root / ".dmon/api.meta.json").read_text())
        finally:
            for record in records:
                if check_running(record["pid"], record["create_time"]):
                    psutil.Process(record["pid"]).kill()
            deadline = time.monotonic() + 5
            while any(
                check_running(record["pid"], record["create_time"])
                for record in records
            ):
                if time.monotonic() >= deadline:
                    self.fail("fixture cleanup did not finish")
                time.sleep(0.02)

    def test_copied_or_moved_records_cannot_control_original_processes(self):
        for scenario in ("task", "stack", "orphaned", "legacy", "moved"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                if scenario == "moved" and sys.platform == "win32":
                    self.skipTest("Windows may lock a running process's cwd")
                origin, copy = Path(tmp) / "origin", Path(tmp) / "copy"
                stack = scenario != "task"
                with self.running(origin, stack=stack) as task:
                    if scenario in ("orphaned", "legacy"):
                        path = origin / ".dmon/dev.stack.json"
                        record = json.loads(path.read_text())
                        psutil.Process(record["pid"]).kill()
                        deadline = time.monotonic() + 5
                        while check_running(record["pid"], record["create_time"]):
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.02)
                        if scenario == "legacy":
                            record.pop("meta_path")
                            path.write_text(json.dumps(record), encoding="utf-8")
                    if scenario == "moved":
                        origin.rename(copy)
                    else:
                        shutil.copytree(origin, copy)
                    path = (
                        copy
                        / ".dmon"
                        / ("dev.stack.json" if stack else "api.meta.json")
                    )
                    original = path.read_bytes()
                    commands = (
                        (
                            ["stack", "status", "dev", "--format", "json"],
                            ["wait", "api", "--format", "json"],
                            ["stack", "down", "dev"],
                            ["stack", "up", "-d", "dev"],
                        )
                        if stack
                        else (
                            ["status", "api", "--format", "json"],
                            ["wait", "api", "--format", "json"],
                            ["stop", "api"],
                            ["start", "api"],
                        )
                    )
                    for command in commands:
                        result = self.run_dmon(copy, *command)
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertIn(
                            "metadata-location-mismatch", result.stderr + result.stdout
                        )
                        self.assertEqual(path.read_bytes(), original)
                        self.assertTrue(check_running(task["pid"], task["create_time"]))
                    self.assertFalse((copy / ".dmon/dev.stack.json.stop").exists())
                    if scenario == "moved":
                        copy.rename(origin)
                    stopped = self.run_dmon(
                        origin,
                        *(["stack", "down", "dev"] if stack else ["stop", "api"]),
                    )
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)
                    self.assertFalse(check_running(task["pid"], task["create_time"]))

    def test_invalid_identity_or_unknown_format_preserves_record_and_process(self):
        for stack in (False, True):
            with self.subTest(stack=stack), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "project"
                with self.running(root, stack=stack) as task:
                    path = (
                        root
                        / ".dmon"
                        / ("dev.stack.json" if stack else "api.meta.json")
                    )
                    original = json.loads(path.read_text())
                    if stack:
                        # Freeze the record before testing corruption; the task lives.
                        psutil.Process(original["pid"]).kill()
                        deadline = time.monotonic() + 5
                        while check_running(original["pid"], original["create_time"]):
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.02)
                    mutations = [
                        ("missing birth", lambda d: d.pop("create_time")),
                        ("missing pid", lambda d: d.pop("pid")),
                        ("string pid", lambda d: d.update(pid=str(d["pid"]))),
                        ("null birth", lambda d: d.update(create_time=None)),
                        ("nan birth", lambda d: d.update(create_time=float("nan"))),
                        ("boolean pid", lambda d: d.update(pid=True)),
                        ("future format", lambda d: d.update(schema_version=999)),
                    ]
                    if stack:
                        mutations.append(
                            (
                                "invalid owned identity",
                                lambda d: d["tasks"][0].update(pid="bad"),
                            )
                        )
                    for name, mutate in mutations:
                        with self.subTest(case=name):
                            data = json.loads(json.dumps(original))
                            mutate(data)
                            path.write_text(json.dumps(data), encoding="utf-8")
                            before = path.read_bytes()
                            commands = (
                                (
                                    ["stack", "status", "dev", "--format", "json"],
                                    ["stack", "down", "dev"],
                                    ["stack", "up", "-d", "dev"],
                                )
                                if stack
                                else (
                                    ["status", "api", "--format", "json"],
                                    ["stop", "api"],
                                    ["start", "api"],
                                )
                            )
                            for command in commands:
                                result = self.run_dmon(root, *command)
                                self.assertNotEqual(result.returncode, 0)
                                self.assertNotIn("Traceback", result.stderr)
                                self.assertEqual(path.read_bytes(), before)
                                self.assertTrue(
                                    check_running(task["pid"], task["create_time"])
                                )
                    path.write_text(json.dumps(original), encoding="utf-8")
                    stopped = self.run_dmon(
                        root, *(["stack", "down", "dev"] if stack else ["stop", "api"])
                    )
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)

    def test_config_drift_does_not_change_the_processes_owned_by_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            with self.running(root, stack=True) as task:
                # This command must not be launched or substituted for the saved task.
                (root / "dmon.yaml").write_text(
                    "tasks:\n  api: [a-nonexistent-executable]\nstacks:\n  dev: [api]\n",
                    encoding="utf-8",
                )
                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertFalse(check_running(task["pid"], task["create_time"]))

    def test_legacy_records_without_new_optional_fields_remain_manageable(self):
        for stack in (False, True):
            with self.subTest(stack=stack), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "project"
                with self.running(root, stack=stack) as task:
                    if stack:
                        path = root / ".dmon/dev.stack.json"
                        record = json.loads(path.read_text())
                        psutil.Process(record["pid"]).kill()
                        deadline = time.monotonic() + 5
                        while check_running(record["pid"], record["create_time"]):
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.02)
                        record.pop("meta_path")
                        for owned in record["tasks"]:
                            owned.pop("descendants")
                            owned.pop("new_session")
                        path.write_text(json.dumps(record), encoding="utf-8")
                    path = root / ".dmon/api.meta.json"
                    record = json.loads(path.read_text())
                    record.pop("descendants")
                    path.write_text(json.dumps(record), encoding="utf-8")
                    result = self.run_dmon(
                        root, *(["stack", "down", "dev"] if stack else ["stop", "api"])
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(check_running(task["pid"], task["create_time"]))

    def test_symlink_alias_resolves_to_the_same_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, alias = root / "task.json", root / "alias.json"
            meta = DmonMeta(task="api", meta_path=str(path.resolve()))
            meta.dump(path)
            try:
                alias.symlink_to(path)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            self.assertEqual(DmonMeta.load(alias), meta)

    def test_malformed_legacy_scope_reports_a_metadata_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stack.json"
            path.write_text('{"config_path": "/some/project/dmon.yaml"}')
            with self.assertRaisesRegex(TypeError, "stack name"):
                DmonStackMeta.load(path)


if __name__ == "__main__":
    unittest.main()
