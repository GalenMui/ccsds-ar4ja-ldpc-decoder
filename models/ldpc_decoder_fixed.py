"""Deterministic fixed-point normalized min-sum LDPC decoder model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from . import ar4ja_matrix as ar4ja
from .llr_quant import LLR_WIDTH_DEFAULT, clip_signed, hard_decision_from_llr, signed_limits


@dataclass(frozen=True)
class FixedDecodeResult:
    hard_full: np.ndarray
    hard_transmitted: np.ndarray
    posterior_llr: np.ndarray
    iterations: int
    syndrome: np.ndarray
    converged: bool
    saturation_count: int = 0
    decoder_success: bool = False
    decoder_fail: bool = False


def _full_llr(llr: Sequence[int] | np.ndarray) -> np.ndarray:
    arr = np.asarray(llr, dtype=np.int16).reshape(-1)
    if arr.size == ar4ja.TX_N:
        full = np.zeros(ar4ja.FULL_N, dtype=np.int16)
        full[: ar4ja.TX_N] = arr
        return full
    if arr.size == ar4ja.FULL_N:
        return arr.copy()
    raise ValueError(f"expected {ar4ja.TX_N} or {ar4ja.FULL_N} LLRs, got {arr.size}")


def _norm_scale(value: int, numerator: int, denominator: int) -> int:
    scaled = abs(value) * numerator // denominator
    return scaled if value >= 0 else -scaled


def _clip_with_count(value: int, lo: int, hi: int) -> tuple[int, int]:
    clipped = max(lo, min(hi, value))
    return clipped, int(clipped != value)


def decode_normalized_min_sum_fixed(
    llr: Sequence[int] | np.ndarray,
    *,
    iterations: int = 10,
    alpha_num: int = 3,
    alpha_den: int = 4,
    llr_width: int = LLR_WIDTH_DEFAULT,
    message_width: int = 8,
) -> FixedDecodeResult:
    """Decode with integer normalized min-sum and saturating messages."""

    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    if alpha_num <= 0 or alpha_den <= 0:
        raise ValueError("normalization ratio must be positive")

    raw_channel = _full_llr(llr)
    channel = clip_signed(raw_channel, llr_width)
    lo, hi = signed_limits(message_width)
    saturation_count = int(np.count_nonzero(channel.astype(np.int64) != raw_channel.astype(np.int64)))
    h = ar4ja.build_h_full_sparse()
    row_to_cols = h.row_to_cols
    col_to_rows = h.col_to_rows

    v_to_c = {(r, c): int(channel[c]) for r, cols in enumerate(row_to_cols) for c in cols}
    c_to_v = {(r, c): 0 for r, cols in enumerate(row_to_cols) for c in cols}
    posterior = channel.astype(np.int16).copy()
    hard = hard_decision_from_llr(posterior)
    syndrome = ar4ja.syndrome_full(hard)
    if int(syndrome.sum()) == 0 or iterations == 0:
        converged = int(syndrome.sum()) == 0
        return FixedDecodeResult(
            hard,
            hard[: ar4ja.TX_N].copy(),
            posterior,
            0,
            syndrome,
            converged,
            saturation_count,
            converged,
            not converged,
        )

    used_iterations = 0
    for iteration in range(1, iterations + 1):
        used_iterations = iteration
        for row, cols in enumerate(row_to_cols):
            values = [v_to_c[(row, col)] for col in cols]
            signs = [1 if value >= 0 else -1 for value in values]
            abs_values = [abs(value) for value in values]
            sign_product = 1
            for sign in signs:
                sign_product *= sign
            for idx, col in enumerate(cols):
                if len(abs_values) == 1:
                    min_abs = 0
                else:
                    min_abs = min(abs_values[:idx] + abs_values[idx + 1 :])
                value = sign_product * signs[idx] * min_abs
                value = _norm_scale(value, alpha_num, alpha_den)
                clipped, clipped_count = _clip_with_count(value, lo, hi)
                c_to_v[(row, col)] = clipped
                saturation_count += clipped_count

        for col, rows in enumerate(col_to_rows):
            total = int(channel[col])
            for row in rows:
                total += c_to_v[(row, col)]
            clipped_total, clipped_count = _clip_with_count(total, lo, hi)
            saturation_count += clipped_count
            posterior[col] = clipped_total
            for row in rows:
                msg = clipped_total - c_to_v[(row, col)]
                clipped_msg, clipped_count = _clip_with_count(msg, lo, hi)
                v_to_c[(row, col)] = clipped_msg
                saturation_count += clipped_count

        hard = hard_decision_from_llr(posterior)
        syndrome = ar4ja.syndrome_full(hard)
        if int(syndrome.sum()) == 0:
            break

    converged = int(syndrome.sum()) == 0
    return FixedDecodeResult(
        hard_full=hard,
        hard_transmitted=hard[: ar4ja.TX_N].copy(),
        posterior_llr=posterior,
        iterations=used_iterations,
        syndrome=syndrome,
        converged=converged,
        saturation_count=saturation_count,
        decoder_success=converged,
        decoder_fail=not converged,
    )
