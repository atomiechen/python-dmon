from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dmon.config import (
    check_name_in_config,
    get_stack_config,
    get_task_config,
    load_config,
    validate_task,
)


class ConfigTest(unittest.TestCase):
    def write_config(self, root: Path, text: str) -> Path:
        path = root / "dmon.yaml"
        path.write_text(text, encoding="utf-8")
        return path

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

    def test_environment_files_accept_one_path_or_an_ordered_list(self) -> None:
        single = validate_task({"cmd": ["app"], "env_file": ".env"}, "app")
        multiple = validate_task(
            {"cmd": ["app"], "env_file": ["base.env", "local.env"]}, "app"
        )

        self.assertEqual(single.env_files, [".env"])
        self.assertEqual(multiple.env_files, ["base.env", "local.env"])
        for value in ("", [], ["ok.env", ""], [1], True):
            with self.subTest(value=value), self.assertRaisesRegex(
                TypeError, "env_file"
            ):
                validate_task({"cmd": ["app"], "env_file": value}, "app")

    def test_yaml_merge_keys_can_reuse_task_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                "defaults: &defaults\n"
                "  env_file: .env\n"
                "  cwd: services\n"
                "tasks:\n"
                "  api:\n"
                "    <<: *defaults\n"
                "    cmd: [python, api.py]\n",
            )

            names, configs, _ = get_task_config(["api"], str(path))

            self.assertEqual(names, ["api"])
            self.assertEqual(configs[0].env_files, [".env"])
            self.assertEqual(configs[0].cwd, "services")

    def test_stack_orders_dependencies_before_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                """
tasks:
  api:
    cmd: [python, api.py]
    depends_on: [DATABASE]
  database: [python, database.py]
  worker:
    cmd: [python, worker.py]
    depends_on: [api]
stacks:
  DEV: [worker]
""",
            )
            name, configs, returned_path = get_stack_config("DEV", str(path))
            self.assertEqual(name, "dev")
            self.assertEqual(
                [config.task for config in configs], ["database", "api", "worker"]
            )
            self.assertEqual(returned_path, path.resolve())

    def test_stack_rejects_dependency_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                """
tasks:
  first:
    cmd: echo first
    depends_on: [second]
  second:
    cmd: echo second
    depends_on: [first]
stacks:
  broken: [first]
""",
            )
            with self.assertRaisesRegex(ValueError, "first -> second -> first"):
                get_stack_config("broken", str(path))

    def test_stack_rejects_missing_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                """
tasks:
  api:
    cmd: echo api
    depends_on: [database]
stacks:
  broken: [api]
""",
            )
            with self.assertRaisesRegex(ValueError, "database.*not defined"):
                get_stack_config("broken", str(path))

    def test_stack_does_not_validate_unrelated_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                """
tasks:
  app: [python, app.py]
  unrelated:
    invalid: true
stacks:
  dev: [app]
""",
            )
            _, configs, _ = get_stack_config("dev", str(path))
            self.assertEqual([config.task for config in configs], ["app"])

    def test_ready_probe_requires_exactly_one_supported_probe(self) -> None:
        for ready in ({}, {"http": "http://localhost", "command": ["true"]}):
            with self.subTest(ready=ready), self.assertRaisesRegex(
                TypeError, "exactly one"
            ):
                validate_task({"cmd": ["app"], "ready": ready}, "app")

    def test_http_ready_probe_requires_an_http_url(self) -> None:
        for url in ("", "localhost:8000", "file:///tmp/ready", "http://:bad"):
            with self.subTest(url=url), self.assertRaisesRegex(TypeError, "URL"):
                validate_task({"cmd": ["app"], "ready": {"http": url}}, "app")

        config = validate_task(
            {"cmd": ["app"], "ready": {"http": "https://localhost/health"}},
            "app",
        )
        self.assertEqual(config.ready["http"], "https://localhost/health")

    def test_ready_probe_validates_tcp_shape_and_timing(self) -> None:
        for ready in (
            {"tcp": {"host": "127.0.0.1", "port": 70000}},
            {"tcp": {"host": "127.0.0.1", "port": True}},
            {"command": ["true"], "timeout": True},
            {"command": ["true"], "timeout": float("nan")},
            {"command": ["true"], "interval": float("inf")},
            {"command": []},
        ):
            with self.subTest(ready=ready), self.assertRaises(TypeError):
                validate_task({"cmd": ["app"], "ready": ready}, "app")


if __name__ == "__main__":
    unittest.main()
