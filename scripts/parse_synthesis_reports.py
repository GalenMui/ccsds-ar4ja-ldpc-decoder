#!/usr/bin/env python3
"""Parse synthesis reports when real synthesis reports are available.

The repository includes synthesis templates, but this script still documents
missing report input instead of inventing resource numbers.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_paths", nargs="*", type=Path)
    args = parser.parse_args()

    existing = [path for path in args.report_paths if path.exists()]
    if not existing:
        print("No synthesis reports provided. Resource/timing data is unavailable.")
        print("Add a synthesis flow and pass report paths to this script to parse real numbers.")
        return 0

    print("Synthesis report parsing is not specialized yet; provided reports:")
    for path in existing:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
