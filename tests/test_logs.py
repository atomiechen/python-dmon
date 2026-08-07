from __future__ import annotations

from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dmon.logs import show_stack_logs
from dmon.types import DmonTaskConfig


class StackLogsTest(unittest.TestCase):
    def config(self, root: Path, task: str) -> DmonTaskConfig:
        return DmonTaskConfig(task=task, log_path=str(root / f"{task}.log"))

    def test_snapshot_tails_each_log_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = self.config(root, "api")
            worker = self.config(root, "worker")
            api_bytes = b"old\nrequest\nresponse\n"
            worker_bytes = "任务开始\n完成\n".encode()
            Path(api.log_path).write_bytes(api_bytes)
            Path(worker.log_path).write_bytes(worker_bytes)
            output = StringIO()

            with patch("dmon.logs.colored", side_effect=lambda text, **_kw: text):
                self.assertEqual(
                    show_stack_logs(
                        [api, worker], tail=2, stdout=output, stderr=StringIO()
                    ),
                    0,
                )

            rendered = output.getvalue()
            self.assertNotIn("old", rendered)
            self.assertIn("[api   ] request\n", rendered)
            self.assertIn("[api   ] response\n", rendered)
            self.assertIn("[worker] 任务开始\n", rendered)
            self.assertEqual(Path(api.log_path).read_bytes(), api_bytes)
            self.assertEqual(Path(worker.log_path).read_bytes(), worker_bytes)

    def test_follow_combines_partial_line_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = self.config(root, "api")
            Path(api.log_path).write_bytes(b"partial")
            output = StringIO()
            checks = 0

            def stop_requested() -> bool:
                nonlocal checks
                checks += 1
                return checks >= 2

            def append_line(_seconds: float) -> None:
                with Path(api.log_path).open("ab") as stream:
                    stream.write(b" line\n")

            with patch(
                "dmon.logs.colored", side_effect=lambda text, **_kw: text
            ), patch("dmon.logs.time.sleep", side_effect=append_line):
                self.assertEqual(
                    show_stack_logs(
                        [api],
                        tail=1,
                        follow=True,
                        stop_requested=stop_requested,
                        stdout=output,
                        stderr=StringIO(),
                    ),
                    0,
                )

            self.assertEqual(output.getvalue(), "[api] partial line\n")

    def test_follow_reopens_replaced_log_after_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = self.config(root, "api")
            path = Path(api.log_path)
            archive = root / "api.log.rotated"
            path.write_bytes(b"old\n")
            output = StringIO()
            checks = 0

            def stop_requested() -> bool:
                nonlocal checks
                checks += 1
                return checks >= 2

            def rotate(_seconds: float) -> None:
                with path.open("ab") as stream:
                    stream.write(b"late-old\n")
                path.replace(archive)
                path.write_bytes(b"new\n")

            with patch(
                "dmon.logs.colored", side_effect=lambda text, **_kw: text
            ), patch("dmon.logs.time.sleep", side_effect=rotate):
                self.assertEqual(
                    show_stack_logs(
                        [api],
                        tail=0,
                        follow=True,
                        stop_requested=stop_requested,
                        stdout=output,
                        stderr=StringIO(),
                    ),
                    0,
                )

            self.assertEqual(output.getvalue(), "[api] late-old\n[api] new\n")
            self.assertEqual(archive.read_bytes(), b"old\nlate-old\n")
            self.assertEqual(path.read_bytes(), b"new\n")

    def test_follow_waits_for_a_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = self.config(root, "api")
            output = StringIO()
            errors = StringIO()
            checks = 0

            def stop_requested() -> bool:
                nonlocal checks
                checks += 1
                return checks >= 2

            def create_log(_seconds: float) -> None:
                Path(api.log_path).write_bytes(b"started\n")

            with patch(
                "dmon.logs.colored", side_effect=lambda text, **_kw: text
            ), patch("dmon.logs.time.sleep", side_effect=create_log):
                self.assertEqual(
                    show_stack_logs(
                        [api],
                        follow=True,
                        stop_requested=stop_requested,
                        stdout=output,
                        stderr=errors,
                    ),
                    0,
                )

            self.assertIn("Log not found for task 'api'", errors.getvalue())
            self.assertEqual(output.getvalue(), "[api] started\n")

    def test_follow_ctrl_c_flushes_partial_line_and_changes_no_process_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = self.config(root, "api")
            path = Path(api.log_path)
            path.write_bytes(b"unfinished")
            before = path.read_bytes()
            output = StringIO()

            with patch(
                "dmon.logs.colored", side_effect=lambda text, **_kw: text
            ), patch("dmon.logs.time.sleep", side_effect=KeyboardInterrupt):
                self.assertEqual(
                    show_stack_logs(
                        [api],
                        tail=1,
                        follow=True,
                        stdout=output,
                        stderr=StringIO(),
                    ),
                    0,
                )

            self.assertEqual(output.getvalue(), "[api] unfinished\n")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
