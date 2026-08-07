from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from dmon.runner import rotate_file, timestamped_backups


class RunnerTest(unittest.TestCase):
    def run_burst(self, root: Path, *retention_args: str):
        log_path = root / "burst.log"
        rotate_log_path = root / "burst.rotate.log"
        command = [
            sys.executable,
            "-m",
            "dmon.runner",
            "--log-path",
            str(log_path),
            "--max-log-size",
            "0.001",
            "--rotate-log-path",
            str(rotate_log_path),
            "--max-rotate-log-size",
            "0.0002",
            *retention_args,
            "--",
            sys.executable,
            "-c",
            "for i in range(400): print(f'{i:04d}:' + 'x' * 80, flush=True)",
        ]
        result = subprocess.run(command, check=False, timeout=10)
        self.assertEqual(result.returncode, 0)

        files = list(root.iterdir())
        task_backups = [
            path
            for path in files
            if re.fullmatch(r"burst\.log\.\d{8}-\d{6}(?:\.\d+)?", path.name)
        ]
        runner_backups = [
            path
            for path in files
            if re.fullmatch(r"burst\.rotate\.log\.\d{8}-\d{6}(?:\.\d+)?", path.name)
        ]
        self.assertEqual(
            {path.name for path in files if path not in task_backups + runner_backups},
            {"burst.log", "burst.rotate.log"},
        )
        return task_backups, runner_backups

    def test_same_second_collision_uses_counter_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            timestamp = "20260807-142106"
            old_backup = Path(f"{log_path}.{timestamp}")
            old_backup.write_text("old", encoding="utf-8")
            log_path.write_text("new", encoding="utf-8")

            backup = rotate_file(log_path, timestamp)

            self.assertEqual(backup.name, "task.log.20260807-142106.1")
            self.assertEqual(backup.read_text(encoding="utf-8"), "new")
            self.assertTrue(old_backup.exists())

    def test_same_second_collision_counter_grows_beyond_two_digits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            timestamp = "20260807-142106"
            Path(f"{log_path}.{timestamp}").touch()
            for counter in range(1, 100):
                Path(f"{log_path}.{timestamp}.{counter}").touch()
            log_path.write_text("new", encoding="utf-8")

            backup = rotate_file(log_path, timestamp)

            self.assertEqual(backup.name, "task.log.20260807-142106.100")
            self.assertEqual(len(list(Path(temporary).iterdir())), 101)

    def test_archive_discovery_accepts_legacy_counter_padding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            names = {
                "task.log.20260807-142106",
                "task.log.20260807-142106.1",
                "task.log.20260807-142106.01",
                "task.log.20260807-142106.001",
            }
            for name in names:
                (Path(temporary) / name).touch()
            (Path(temporary) / "task.log.not-an-archive").touch()

            self.assertEqual(
                {path.name for path in timestamped_backups(log_path)}, names
            )

    @unittest.skipIf(os.name == "nt", "legacy ':' filenames cannot exist on Windows")
    def test_archive_discovery_accepts_legacy_runner_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            legacy = Path(temporary) / "task.log.20260807-14:21:06.0001"
            legacy.touch()

            self.assertEqual(timestamped_backups(log_path), [legacy])

    def test_configured_backup_count_prunes_oldest_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            for timestamp in (
                "20260807-142106",
                "20260807-142107",
                "20260807-142108",
            ):
                log_path.write_text(timestamp, encoding="utf-8")
                rotate_file(log_path, timestamp, backup_count=2)

            self.assertEqual(
                sorted(path.name for path in Path(temporary).iterdir()),
                ["task.log.20260807-142107", "task.log.20260807-142108"],
            )

    @unittest.skipIf(os.name == "nt", "legacy ':' filenames cannot exist on Windows")
    def test_configured_backup_count_recognizes_legacy_runner_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.rotate.log"
            legacy = Path(f"{log_path}.20260807-14:21:06")
            legacy.write_text("legacy", encoding="utf-8")
            log_path.write_text("current", encoding="utf-8")
            os.utime(legacy, ns=(1, 1))
            os.utime(log_path, ns=(2, 2))

            rotate_file(log_path, "20260807-142107", backup_count=1)

            self.assertFalse(legacy.exists())
            self.assertTrue(Path(f"{log_path}.20260807-142107").exists())

    def test_rotation_honors_explicit_backup_count_for_each_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log_path = root / "burst.log"
            rotate_log_path = root / "burst.rotate.log"
            task_backups, runner_backups = self.run_burst(
                root,
                "--log-backup-count",
                "1",
                "--rotate-log-backup-count",
                "1",
            )
            self.assertEqual(len(task_backups), 1)
            self.assertEqual(len(runner_backups), 1)
            self.assertLessEqual(log_path.stat().st_size, 1200)
            self.assertLessEqual(task_backups[0].stat().st_size, 1200)
            self.assertLessEqual(rotate_log_path.stat().st_size, 500)
            self.assertLessEqual(runner_backups[0].stat().st_size, 500)

    def test_rotation_retains_all_archives_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            task_backups, runner_backups = self.run_burst(Path(temporary))

            self.assertGreater(len(task_backups), 1)
            self.assertGreater(len(runner_backups), 1)


if __name__ == "__main__":
    unittest.main()
