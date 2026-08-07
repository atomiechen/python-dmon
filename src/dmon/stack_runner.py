from __future__ import annotations

import argparse
from pathlib import Path

from .supervisor import run_detached_stack


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal detached stack supervisor")
    parser.add_argument("meta_path")
    parser.add_argument("run_id")
    args = parser.parse_args()
    parser.exit(run_detached_stack(Path(args.meta_path), args.run_id))


if __name__ == "__main__":
    main()
