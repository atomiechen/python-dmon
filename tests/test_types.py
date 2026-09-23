from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dmon.types import DmonMeta, DmonStackMeta, DmonStackTask


class DmonMetaTest(unittest.TestCase):
    def test_load_retries_transient_windows_permission_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            for model in (DmonMeta, DmonStackMeta):
                with self.subTest(model=model):
                    names = {"stack": "dev"} if model is DmonStackMeta else {}
                    expected = model(
                        **names, pid=42, create_time=42.0, meta_path=str(path)
                    )
                    expected.dump(path)
                    original_open = Path.open
                    attempts = 0

                    def transient_open(target, *args, **kwargs):
                        nonlocal attempts
                        attempts += 1
                        if attempts < 3:
                            raise PermissionError("temporarily in use")
                        return original_open(target, *args, **kwargs)

                    with patch("dmon.types.ON_WINDOWS", True), patch.object(
                        Path, "open", transient_open
                    ), patch("dmon.types.time.sleep"):
                        self.assertEqual(model.load(path), expected)
                    self.assertEqual(attempts, 3)

    def test_load_permission_retry_is_bounded_and_preserves_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            for model in (DmonMeta, DmonStackMeta):
                with self.subTest(model=model):
                    names = {"stack": "dev"} if model is DmonStackMeta else {}
                    model(**names, pid=42, create_time=42.0).dump(path)
                    before = path.read_bytes()
                    with patch("dmon.types.ON_WINDOWS", True), patch.object(
                        Path, "open", side_effect=PermissionError("denied")
                    ), patch("dmon.types.time.monotonic", side_effect=[0, 0, 1]), patch(
                        "dmon.types.time.sleep"
                    ):
                        with self.assertRaises(PermissionError):
                            model.load(path)
                    self.assertEqual(path.read_bytes(), before)

    def test_load_retry_still_rejects_wrong_metadata_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            for model in (DmonMeta, DmonStackMeta):
                with self.subTest(model=model):
                    names = {"stack": "dev"} if model is DmonStackMeta else {}
                    model(
                        **names,
                        pid=42,
                        create_time=42.0,
                        meta_path=str(path.parent / "other.json"),
                    ).dump(path)
                    original_open = Path.open
                    attempts = 0

                    def transient_open(target, *args, **kwargs):
                        nonlocal attempts
                        attempts += 1
                        if attempts == 1:
                            raise PermissionError("temporarily in use")
                        return original_open(target, *args, **kwargs)

                    with patch("dmon.types.ON_WINDOWS", True), patch.object(
                        Path, "open", transient_open
                    ), patch("dmon.types.time.sleep"):
                        with self.assertRaisesRegex(
                            ValueError, "metadata-location-mismatch"
                        ):
                            model.load(path)
                    self.assertEqual(attempts, 2)

    def test_malformed_task_and_descendant_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.json"
            for value in (
                [],
                {"descendants": {}},
                {"descendants": [{"pid": 0, "create_time": 1}]},
            ):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(
                    (ValueError, TypeError)
                ):
                    DmonMeta.load(path)

    def test_stack_metadata_round_trip_preserves_owned_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dev.stack.json"
            expected = DmonStackMeta(
                stack="dev",
                run_id="run-123",
                abort_on_exit=True,
                state="running",
                pid=41,
                create_time=42.0,
                tasks=[DmonStackTask("api", 43, 44.0, ".dmon/api.meta.json")],
            )
            expected.dump(path, exclusive=True)
            self.assertEqual(DmonStackMeta.load(path), expected)

    def test_malformed_stack_metadata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dev.stack.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(TypeError, "JSON object"):
                DmonStackMeta.load(path)

    def test_stack_metadata_without_mode_remains_detached_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.stack.json"
            path.write_text(json.dumps({"stack": "legacy"}), encoding="utf-8")
            loaded = DmonStackMeta.load(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.mode, "detached")

    def test_exclusive_dump_reserves_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(task="first").dump(path, exclusive=True)
            with self.assertRaises(FileExistsError):
                DmonMeta(task="second").dump(path, exclusive=True)
            self.assertEqual(DmonMeta.load(path).task, "first")

    def test_exclusive_dump_publishes_only_complete_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            writing = threading.Event()
            release = threading.Event()
            original_dump = json.dump

            def delayed_dump(*args, **kwargs):
                writing.set()
                self.assertTrue(release.wait(timeout=5))
                return original_dump(*args, **kwargs)

            thread = threading.Thread(
                target=lambda: DmonMeta(task="complete").dump(path, exclusive=True)
            )
            with patch("dmon.types.json.dump", side_effect=delayed_dump):
                thread.start()
                self.assertTrue(writing.wait(timeout=5))
                self.assertFalse(path.exists())
                release.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertEqual(DmonMeta.load(path).task, "complete")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_regular_dump_atomically_replaces_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(task="first").dump(path, exclusive=True)
            DmonMeta(task="second", pid=42, create_time=42.0).dump(path)
            loaded = DmonMeta.load(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual((loaded.task, loaded.pid), ("second", 42))
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_task_metadata_never_persists_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(
                task="private",
                env={"SECRET_TOKEN": "do-not-store"},
                env_files=["private.env"],
            ).dump(path)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("env", data)
            self.assertNotIn("env_files", data)
            self.assertNotIn("do-not-store", path.read_text(encoding="utf-8"))
            loaded = DmonMeta.load(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.env, {})

    def test_regular_dump_retries_a_transient_replace_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(task="first").dump(path)
            original_replace = os.replace
            attempts = 0

            def transient_error(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("temporarily in use")
                return original_replace(source, target)

            with patch("dmon.types.os.replace", side_effect=transient_error), patch(
                "dmon.types.time.sleep"
            ):
                DmonMeta(task="second").dump(path)

            self.assertEqual(attempts, 3)
            self.assertEqual(DmonMeta.load(path).task, "second")


if __name__ == "__main__":
    unittest.main()
