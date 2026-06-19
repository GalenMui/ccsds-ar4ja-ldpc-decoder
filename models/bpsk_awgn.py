"""BPSK over AWGN channel model consistent with the LLR sign convention."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .llr_quant import LLR_WIDTH_DEFAULT, quantize_llr


@dataclass(frozen=True)
class ChannelResult:
    bits: np.ndarray
    symbols: np.ndarray
    noisy_symbols: np.ndarray
    llr: np.ndarray
    quantized_llr: np.ndarray
    noise_sigma: float


def bits_to_bpsk(bits: Sequence[int] | np.ndarray) -> np.ndarray:
    """Map bit 0 to +1 and bit 1 to -1."""

    arr = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if np.any((arr != 0) & (arr != 1)):
        raise ValueError("bits must contain only 0 and 1")
    return np.where(arr == 0, 1.0, -1.0)


def awgn_noise_sigma(snr_db: float) -> float:
    """Return sigma for unit-energy BPSK at the requested Es/N0 in dB."""

    snr_linear = 10.0 ** (snr_db / 10.0)
    return float(np.sqrt(1.0 / (2.0 * snr_linear)))


def add_awgn(
    symbols: Sequence[float] | np.ndarray,
    *,
    snr_db: float,
    seed: int,
) -> tuple[np.ndarray, float]:
    sigma = awgn_noise_sigma(snr_db)
    rng = np.random.default_rng(seed)
    sym = np.asarray(symbols, dtype=float).reshape(-1)
    return sym + rng.normal(0.0, sigma, size=sym.shape), sigma


def llr_from_awgn_symbols(noisy_symbols: Sequence[float] | np.ndarray, noise_sigma: float) -> np.ndarray:
    """Compute floating LLRs for BPSK/AWGN with bit 0 mapped to +1."""

    if noise_sigma <= 0:
        raise ValueError("noise_sigma must be positive")
    y = np.asarray(noisy_symbols, dtype=float).reshape(-1)
    return 2.0 * y / (noise_sigma * noise_sigma)


def transmit_bpsk_awgn(
    bits: Sequence[int] | np.ndarray,
    *,
    snr_db: float,
    seed: int,
    llr_width: int = LLR_WIDTH_DEFAULT,
    llr_scale: float = 1.0,
) -> ChannelResult:
    bit_arr = np.asarray(bits, dtype=np.uint8).reshape(-1)
    symbols = bits_to_bpsk(bit_arr)
    noisy, sigma = add_awgn(symbols, snr_db=snr_db, seed=seed)
    llr = llr_from_awgn_symbols(noisy, sigma)
    q_llr = quantize_llr(llr, width=llr_width, scale=llr_scale)
    return ChannelResult(bit_arr, symbols, noisy, llr, q_llr, sigma)


def noiseless_llr(
    bits: Sequence[int] | np.ndarray,
    *,
    magnitude: float = 32.0,
    llr_width: int = LLR_WIDTH_DEFAULT,
) -> np.ndarray:
    """Return high-confidence quantized LLRs with no channel noise."""

    if magnitude <= 0:
        raise ValueError("magnitude must be positive")
    symbols = bits_to_bpsk(bits)
    return quantize_llr(symbols * magnitude, width=llr_width)

