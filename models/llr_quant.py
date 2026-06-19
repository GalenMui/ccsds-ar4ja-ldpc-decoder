"""Fixed-point LLR quantization helpers.

Sign convention:

* positive LLR means hard decision bit 0
* negative LLR means hard decision bit 1
* exactly zero is a tie and is resolved to bit 0

Quantized LLRs are signed two's-complement integers with saturation at the
configured width.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

LLR_WIDTH_DEFAULT = 8
ZERO_LLR_HARD_DECISION = 0


def signed_limits(width: int = LLR_WIDTH_DEFAULT) -> tuple[int, int]:
    if width < 2:
        raise ValueError("LLR width must be at least 2 bits")
    return -(1 << (width - 1)), (1 << (width - 1)) - 1


def saturate(value: int | np.ndarray, width: int = LLR_WIDTH_DEFAULT):
    lo, hi = signed_limits(width)
    return np.clip(value, lo, hi)


def _round_half_away_from_zero(values: np.ndarray) -> np.ndarray:
    return np.where(values >= 0, np.floor(values + 0.5), np.ceil(values - 0.5))


def quantize_llr(
    llr: float | Sequence[float] | np.ndarray,
    *,
    width: int = LLR_WIDTH_DEFAULT,
    scale: float = 1.0,
) -> np.ndarray:
    """Quantize floating-point LLRs to signed two's-complement integers."""

    if scale <= 0:
        raise ValueError("scale must be positive")
    values = np.asarray(llr, dtype=float) * scale
    rounded = _round_half_away_from_zero(values)
    return saturate(rounded, width).astype(np.int16)


def hard_decision_from_llr(llr: int | float | Sequence[int] | np.ndarray) -> np.ndarray:
    """Return 0 for non-negative LLRs and 1 for negative LLRs."""

    values = np.asarray(llr)
    return np.where(values < 0, 1, ZERO_LLR_HARD_DECISION).astype(np.uint8)


def clip_signed(values: Sequence[int] | np.ndarray, width: int = LLR_WIDTH_DEFAULT) -> np.ndarray:
    return saturate(np.asarray(values, dtype=np.int64), width).astype(np.int16)

