"""Simple floating-point normalized min-sum LDPC decoder model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from . import ar4ja_matrix as ar4ja
from .llr_quant import hard_decision_from_llr


@dataclass(frozen=True)
class FloatDecodeResult:
    hard_full: np.ndarray
    hard_transmitted: np.ndarray
    posterior_llr: np.ndarray
    iterations: int
    syndrome: np.ndarray
    converged: bool


def _full_llr(llr: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(llr, dtype=float).reshape(-1)
    if arr.size == ar4ja.TX_N:
        full = np.zeros(ar4ja.FULL_N, dtype=float)
        full[: ar4ja.TX_N] = arr
        return full
    if arr.size == ar4ja.FULL_N:
        return arr.copy()
    raise ValueError(f"expected {ar4ja.TX_N} or {ar4ja.FULL_N} LLRs, got {arr.size}")


def decode_normalized_min_sum(
    llr: Sequence[float] | np.ndarray,
    *,
    iterations: int = 10,
    alpha: float = 0.75,
) -> FloatDecodeResult:
    """Decode using a clear, deterministic normalized min-sum schedule."""

    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    if alpha <= 0:
        raise ValueError("alpha must be positive")

    channel = _full_llr(llr)
    h = ar4ja.build_h_full_sparse()
    row_to_cols = h.row_to_cols
    col_to_rows = h.col_to_rows

    v_to_c = {(r, c): channel[c] for r, cols in enumerate(row_to_cols) for c in cols}
    c_to_v = {(r, c): 0.0 for r, cols in enumerate(row_to_cols) for c in cols}
    posterior = channel.copy()
    hard = hard_decision_from_llr(posterior)
    syndrome = ar4ja.syndrome_full(hard)
    if int(syndrome.sum()) == 0 or iterations == 0:
        return FloatDecodeResult(hard, hard[: ar4ja.TX_N].copy(), posterior, 0, syndrome, int(syndrome.sum()) == 0)

    used_iterations = 0
    for iteration in range(1, iterations + 1):
        used_iterations = iteration
        for row, cols in enumerate(row_to_cols):
            values = [v_to_c[(row, col)] for col in cols]
            signs = [1.0 if value >= 0.0 else -1.0 for value in values]
            abs_values = [abs(value) for value in values]
            sign_product = float(np.prod(signs)) if signs else 1.0
            for idx, col in enumerate(cols):
                if len(abs_values) == 1:
                    min_abs = 0.0
                else:
                    min_abs = min(abs_values[:idx] + abs_values[idx + 1 :])
                c_to_v[(row, col)] = alpha * sign_product * signs[idx] * min_abs

        for col, rows in enumerate(col_to_rows):
            total = channel[col]
            for row in rows:
                total += c_to_v[(row, col)]
            posterior[col] = total
            for row in rows:
                v_to_c[(row, col)] = total - c_to_v[(row, col)]

        hard = hard_decision_from_llr(posterior)
        syndrome = ar4ja.syndrome_full(hard)
        if int(syndrome.sum()) == 0:
            break

    return FloatDecodeResult(
        hard_full=hard,
        hard_transmitted=hard[: ar4ja.TX_N].copy(),
        posterior_llr=posterior,
        iterations=used_iterations,
        syndrome=syndrome,
        converged=int(syndrome.sum()) == 0,
    )

