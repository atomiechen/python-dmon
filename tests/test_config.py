from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dmon.config import (
    check_name_in_config,
    get_task_config,
    load_config,
    validate_task,
)


class ConfigTest(unittest.TestCase):
    def test_empty_yaml_is_an_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dmon.yaml"
            path.write_text("", encoding="utf-8")
            config, returned_path = load_config(str(path))
            self.assertEqual(config, {})
            self.assertEqual(returned_path, path.resolve())

    def test_task_names_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dmon.yaml"
            path.write_text("tasks:\n  app: [python, app.py]\n", encoding="utf-8")
            names, configs, _ = get_task_config(["APP"], str(path))
            self.assertEqual(names, ["app"])
            self.assertEqual(configs[0].task, "app")

    def test_ad_hoc_name_check_does_not_require_a_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "dmon.config.Path.cwd", return_value=Path(temporary)
        ):
            self.assertFalse(check_name_in_config("adhoc"))

    def test_log_backup_counts_must_be_positive_integers(self) -> None:
        for field in ("log_backup_count", "rotate_log_backup_count"):
            for value in (0, -1, 1.5, True, "2"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(
                    TypeError, "positive integer"
                ):
                    validate_task({"cmd": ["app"], field: value}, "app")

            with self.subTest(field=field):
                config = validate_task({"cmd": ["app"], field: 2}, "app")
                self.assertEqual(getattr(config, field), 2)


if __name__ == "__main__":
    unittest.main()
