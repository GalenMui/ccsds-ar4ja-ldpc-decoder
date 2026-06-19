#!/usr/bin/env python3
"""Print fixed-mode AR4JA matrix dimensions and sparse graph statistics."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ar4ja_matrix as ar4ja


def _histogram(values: list[int]) -> str:
    counts = Counter(values)
    return ", ".join(f"{key}:{counts[key]}" for key in sorted(counts))


def main() -> int:
    h = ar4ja.build_h_full_sparse()
    tx_view = ar4ja.build_h_transmitted_view()
    row_weights = [len(cols) for cols in h.row_to_cols]
    col_weights = [len(rows) for rows in h.col_to_rows]
    puncture_weights = [len(cols) for cols in tx_view.row_to_punctured_cols]

    print("CCSDS AR4JA fixed mode")
    print(f"  K={ar4ja.K}")
    print(f"  M={ar4ja.M}")
    print(f"  information bits={ar4ja.INFO_N}")
    print(f"  transmitted bits={ar4ja.TX_N}")
    print(f"  full internal bits={ar4ja.FULL_N}")
    print(f"  punctured bits={ar4ja.PUNCTURED_N}")
    print(f"  parity-check rows={ar4ja.CHECKS}")
    print(f"  puncture policy={ar4ja.PUNCTURE_SOLVE}")
    print()
    print("Sparse graph")
    print(f"  edges={sum(row_weights)}")
    print(f"  max row weight={max(row_weights)}")
    print(f"  row weight histogram={_histogram(row_weights)}")
    print(f"  max column weight={max(col_weights)}")
    print(f"  column weight histogram={_histogram(col_weights)}")
    print(f"  punctured-column count per row histogram={_histogram(puncture_weights)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
