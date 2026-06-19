#!/usr/bin/env python3
"""Plot BER/FER sweep results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_INPUT = Path("results/reports/ber_fer.csv")
DEFAULT_OUTPUT_DIR = Path("results/plots")


def read_rows(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="ascii") as handle:
        return [{key: float(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print("matplotlib is not installed; install requirements.txt to generate plots")
        return 1

    rows = read_rows(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    x = [row["ebn0_db"] for row in rows]

    for field, ylabel, filename in (
        ("pre_ber", "Pre-decoder BER", "pre_ber.png"),
        ("post_ber", "Post-decoder BER", "post_ber.png"),
        ("fer", "Frame error rate", "fer.png"),
        ("avg_iterations", "Average iterations", "avg_iterations.png"),
    ):
        plt.figure()
        plt.plot(x, [row[field] for row in rows], marker="o")
        plt.xlabel("Eb/N0 (dB)")
        plt.ylabel(ylabel)
        if field != "avg_iterations":
            plt.yscale("log")
        plt.grid(True)
        path = args.output_dir / filename
        plt.savefig(path, bbox_inches="tight")
        print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

