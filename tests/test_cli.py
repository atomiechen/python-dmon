from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from dmon.cli import main


class CliTest(unittest.TestCase):
    def test_run_preserves_child_options_after_separator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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
                    "--",
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


if __name__ == "__main__":
    unittest.main()
