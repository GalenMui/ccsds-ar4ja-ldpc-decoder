#!/usr/bin/env python3
"""Lightweight decoder vector consistency checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_decoder_vectors import build_vectors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    vectors = build_vectors()
    failures = [vector for vector in vectors if vector.decoder_fail]
    successes = [vector for vector in vectors if vector.decoder_success]
    print(f"decoder vectors: {len(vectors)} total, {len(successes)} success, {len(failures)} failure")
    return 0 if vectors and successes and failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

