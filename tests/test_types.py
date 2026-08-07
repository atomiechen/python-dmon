from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from dmon.types import DmonMeta


class DmonMetaTest(unittest.TestCase):
    def test_exclusive_dump_reserves_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(task="first").dump(path, exclusive=True)
            with self.assertRaises(FileExistsError):
                DmonMeta(task="second").dump(path, exclusive=True)
            self.assertEqual(DmonMeta.load(path).task, "first")

    def test_regular_dump_atomically_replaces_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "task.meta.json"
            DmonMeta(task="first").dump(path, exclusive=True)
            DmonMeta(task="second", pid=42).dump(path)
            loaded = DmonMeta.load(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual((loaded.task, loaded.pid), ("second", 42))
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
