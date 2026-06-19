#!/usr/bin/env python3
"""Inspect one deterministic decoder vector generated from the Python model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_decoder_vectors import build_vectors


def _bit_preview(bits: np.ndarray, count: int = 64) -> str:
    return "".join("1" if int(bit) else "0" for bit in bits[:count])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", nargs="?", type=int, default=0)
    parser.add_argument("--list", action="store_true", help="list available vector indices")
    args = parser.parse_args()

    vectors = build_vectors()
    if args.list:
        for index, vector in enumerate(vectors):
            print(f"{index:2d} {vector.name}")
        return 0

    if args.index < 0 or args.index >= len(vectors):
        print(f"index {args.index} is out of range 0..{len(vectors) - 1}", file=sys.stderr)
        return 1

    vector = vectors[args.index]
    print(f"index={args.index}")
    print(f"name={vector.name}")
    print(f"payload_weight={int(vector.payload.sum())}")
    print(f"llr_min={int(vector.llr.min())}")
    print(f"llr_max={int(vector.llr.max())}")
    print(f"llr_zero_count={int(np.count_nonzero(vector.llr == 0))}")
    print(f"decoder_success={vector.decoder_success}")
    print(f"decoder_fail={vector.decoder_fail}")
    print(f"syndrome_pass={vector.syndrome_pass}")
    print(f"iterations_used={vector.iterations_used}")
    print(f"saturation_count={vector.saturation_count}")
    print(f"cycle_bounds={vector.cycle_min}..{vector.cycle_max}")
    print(f"payload_first64={_bit_preview(vector.payload)}")
    print(f"expected_payload_first64={_bit_preview(vector.expect_payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
