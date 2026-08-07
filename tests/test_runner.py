from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from dmon.runner import loop_to_log


class RunnerTest(unittest.TestCase):
    def test_rotation_keeps_only_one_bounded_backup(self) -> None:
        line = b"x" * 99 + b"\n"
        limit = 1000
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "task.log"
            loop_to_log(BytesIO(line * 100), str(log_path), limit)

            backup_path = Path(f"{log_path}.1")
            self.assertTrue(backup_path.exists())
            self.assertLessEqual(log_path.stat().st_size, limit)
            self.assertLessEqual(backup_path.stat().st_size, limit)
            self.assertEqual(
                sorted(path.name for path in log_path.parent.iterdir()),
                ["task.log", "task.log.1"],
            )


if __name__ == "__main__":
    unittest.main()
