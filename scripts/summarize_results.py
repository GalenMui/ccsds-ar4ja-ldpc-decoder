#!/usr/bin/env python3
"""Summarize generated BER/FER and simulation results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_BER = Path("results/reports/ber_fer.csv")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ber-fer", type=Path, default=DEFAULT_BER)
    args = parser.parse_args()

    if not args.ber_fer.exists():
        print(f"No BER/FER CSV found at {args.ber_fer}")
        return 1

    with args.ber_fer.open(newline="", encoding="ascii") as handle:
        rows = list(csv.DictReader(handle))

    print("BER/FER summary")
    print("Eb/N0  frames  pre_BER  post_BER  FER  avg_iter  fail_rate")
    for row in rows:
        print(
            f"{float(row['ebn0_db']):5.2f}  {int(row['frames']):6d}  "
            f"{float(row['pre_ber']):.4e}  {float(row['post_ber']):.4e}  "
            f"{float(row['fer']):.4e}  {float(row['avg_iterations']):8.3f}  "
            f"{float(row['decoder_failure_rate']):.4e}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

