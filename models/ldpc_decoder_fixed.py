"""Deterministic layered fixed-point normalized min-sum LDPC decoder model."""

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
    """Decode with row-serial layered integer normalized min-sum.

    This model is intentionally bit-exact with the RTL baseline:

    * transmitted LLRs initialize variables 0..2047;
    * punctured variables 2048..2559 initialize to neutral zero;
    * each check row is processed in ascending row order;
    * q_mj = L_j - R_mj_old is kept only for the active row;
    * the first equal minimum keeps the min1 index, later equal minima may
      become min2;
    * normalization is truncating floor(selected_min * 3 / 4);
    * zero LLRs are hard bit 0.
    """

    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    if alpha_num <= 0 or alpha_den <= 0:
        raise ValueError("normalization ratio must be positive")

    raw_channel = _full_llr(llr)
    channel = clip_signed(raw_channel, llr_width)
    lo, hi = signed_limits(message_width)
    saturation_count = int(np.count_nonzero(channel.astype(np.int64) != raw_channel.astype(np.int64)))
    if alpha_num != 3 or alpha_den != 4:
        raise ValueError("the RTL-equivalent model currently supports only 3/4 normalization")

    h = ar4ja.build_h_full_sparse()
    row_to_cols = h.row_to_cols
    check_messages = [
        [0 for _ in cols]
        for cols in row_to_cols
    ]
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
            old_messages = check_messages[row]
            q_values = [int(posterior[col]) - int(old_messages[idx]) for idx, col in enumerate(cols)]
            sign_bits = [1 if value < 0 else 0 for value in q_values]
            abs_values = [abs(value) for value in q_values]
            sign_xor = 0
            for sign in sign_bits:
                sign_xor ^= sign

            min1 = 1 << 30
            min2 = 1 << 30
            min1_idx = 0
            for idx, abs_value in enumerate(abs_values):
                if abs_value < min1:
                    min2 = min1
                    min1 = abs_value
                    min1_idx = idx
                elif abs_value < min2:
                    min2 = abs_value

            new_messages: list[int] = []
            for idx, col in enumerate(cols):
                selected_min = min2 if idx == min1_idx else min1
                scaled = selected_min * 3 // 4
                value = -scaled if (sign_xor ^ sign_bits[idx]) else scaled
                clipped, clipped_count = _clip_with_count(value, lo, hi)
                saturation_count += clipped_count
                new_messages.append(clipped)

            for idx, col in enumerate(cols):
                total = q_values[idx] + new_messages[idx]
                clipped_total, clipped_count = _clip_with_count(total, lo, hi)
                saturation_count += clipped_count
                posterior[col] = clipped_total
                hard[col] = 1 if clipped_total < 0 else 0

            check_messages[row] = new_messages

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
