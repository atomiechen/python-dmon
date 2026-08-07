from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from dmon.cli import main
from dmon.types import DmonTaskConfig


class CliTest(unittest.TestCase):
    def test_run_preserves_child_options_with_or_without_separator(self) -> None:
        for separator in ([], ["--"]):
            with self.subTest(
                separator=separator
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(
                    sys,
                    "argv",
                    [
                        "dmon",
                        "run",
                        "--name",
                        "adhoc",
                        "--meta-file",
                        str(root / "adhoc.json"),
                        *separator,
                        sys.executable,
                        "-c",
                        "print('ok')",
                    ],
                ), patch("dmon.cli.check_name_in_config", return_value=False), patch(
                    "dmon.cli.start", return_value=0
                ) as mocked_start:
                    with self.assertRaises(SystemExit) as result:
                        main()

                self.assertEqual(result.exception.code, 0)
                config = mocked_start.call_args.args[0][0]
                self.assertEqual(config.cmd, [sys.executable, "-c", "print('ok')"])

    def test_stop_with_config_resolves_metadata_from_config_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                root = Path(temporary)
                config = root / "project" / "dmon.yaml"
                config.parent.mkdir()
                config.write_text("tasks:\n  app: [python, app.py]\n", encoding="utf-8")
                invocation_dir = root / "elsewhere"
                invocation_dir.mkdir()
                os.chdir(invocation_dir)
                with patch.object(
                    sys,
                    "argv",
                    ["dmon", "stop", "-c", str(config), "APP"],
                ), patch("dmon.cli.stop", return_value=0) as mocked_stop:
                    with self.assertRaises(SystemExit) as result:
                        main()
                self.assertEqual(result.exception.code, 0)
                mocked_stop.assert_called_once_with(
                    [(config.parent / ".dmon" / "app.meta.json").resolve()]
                )
            finally:
                os.chdir(original_cwd)

    def test_up_loads_stack_from_config_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                root = Path(temporary)
                config_path = root / "project" / "dmon.yaml"
                config_path.parent.mkdir()
                task = DmonTaskConfig(task="api", cmd=["python", "api.py"])
                with patch.object(
                    sys,
                    "argv",
                    ["dmon", "up", "dev", "-c", str(config_path)],
                ), patch(
                    "dmon.cli.get_stack_config",
                    return_value=("dev", [task], config_path),
                ), patch("dmon.cli.up", return_value=0) as mocked_up:
                    with self.assertRaises(SystemExit) as result:
                        main()

                self.assertEqual(result.exception.code, 0)
                self.assertTrue(Path.cwd().samefile(config_path.parent))
                mocked_up.assert_called_once_with([task], abort_on_exit=False)
                self.assertEqual(Path(task.meta_path), Path(".dmon/api.meta.json"))
                self.assertEqual(Path(task.log_path), Path("logs/api.log"))
            finally:
                os.chdir(original_cwd)

    def test_logs_loads_stack_paths_without_process_control(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                root = Path(temporary)
                config_path = root / "project" / "dmon.yaml"
                config_path.parent.mkdir()
                task = DmonTaskConfig(task="api", cmd=["python", "api.py"])
                with patch.object(
                    sys,
                    "argv",
                    ["dmon", "logs", "dev", "--tail", "12", "-f"],
                ), patch(
                    "dmon.cli.get_stack_config",
                    return_value=("dev", [task], config_path),
                ), patch("dmon.cli.show_stack_logs", return_value=0) as mocked_logs:
                    with self.assertRaises(SystemExit) as result:
                        main()

                self.assertEqual(result.exception.code, 0)
                self.assertTrue(Path.cwd().samefile(config_path.parent))
                mocked_logs.assert_called_once_with([task], tail=12, follow=True)
                self.assertEqual(Path(task.log_path), Path("logs/api.log"))
            finally:
                os.chdir(original_cwd)

    def test_up_reports_unexpected_errors_without_a_traceback(self) -> None:
        task = DmonTaskConfig(task="api", cmd=["python", "api.py"])
        config_path = Path.cwd() / "dmon.yaml"
        output = StringIO()
        with patch.object(sys, "argv", ["dmon", "up", "dev"]), patch(
            "dmon.cli.get_stack_config",
            return_value=("dev", [task], config_path),
        ), patch("dmon.cli.up", side_effect=RuntimeError("simulated failure")):
            with redirect_stderr(output), self.assertRaises(SystemExit) as result:
                main()

        self.assertEqual(result.exception.code, 1)
        self.assertIn("Stack supervision failed: simulated failure", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
