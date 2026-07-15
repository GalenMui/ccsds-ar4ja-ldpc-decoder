"""Deterministic host-side communications pipeline for the LDPC benchmark.

Pipeline stage order:

    payload bits
    -> CCSDS AR4JA rate-1/2 systematic encoder (models.ldpc_encoder)
    -> BPSK modulation (bit 0 -> +1, bit 1 -> -1)
    -> AWGN channel (deterministic numpy Generator)
    -> floating channel LLRs (L = 2*y / sigma^2)
    -> signed int8 quantization (models.llr_quant)
    -> 512 x uint32 DMA input words (models/software.pynq_z2 packing)

This module deliberately reuses the repository's CCSDS encoder, BPSK/AWGN
channel and fixed-point decoder rather than substituting a generic LDPC
library, so hardware and software share one graph and one LLR format.

SNR / Es/N0 / Eb/N0 conventions
-------------------------------
* BPSK symbols have unit energy, so Es = 1.
* The transmitted code rate is R = k / n = 1024 / 2048 = 1/2.  This is the
  *transmitted* rate (the 512 punctured parity symbols are never sent), which
  is what the AWGN channel sees.
* Es/N0 and Eb/N0 differ by the code rate:

      Es/N0 [dB] = Eb/N0 [dB] + 10*log10(R)

* The AWGN noise variance for unit-energy BPSK is

      sigma^2 = N0 / 2 = 1 / (2 * (Es/N0)_linear)
              = 1 / (2 * R * (Eb/N0)_linear)

  `models.bpsk_awgn.awgn_noise_sigma` takes an Es/N0 argument, so callers must
  convert Eb/N0 to Es/N0 with :func:`ebn0_db_to_esn0_db` first.  Passing an
  Eb/N0 value straight into a symbol-SNR channel would silently overstate the
  operating point by 10*log10(1/R) = 3.01 dB.

LLR quantization scale
----------------------
The floating channel LLR magnitude is roughly ``2/sigma^2`` for a clean symbol
and grows as SNR increases.  ``llr_scale`` multiplies the floating LLR before
signed int8 rounding/saturation.  It is a *host preprocessing* choice: hardware
and the software reference decoder both receive the identical quantized int8
LLRs, so hardware/software agreement is independent of the scale.  The scale
only shapes the achievable BER/FER curve and the saturation rate, and should be
characterised on hardware.  ``DEFAULT_LLR_SCALE`` is a documented default, not a
tuned optimum.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from models import ar4ja_matrix as ar4ja
from models import bpsk_awgn, ldpc_encoder, llr_quant

INFO_N = ar4ja.INFO_N          # 1024 information bits
TX_N = ar4ja.TX_N              # 2048 transmitted coded bits
CODE_RATE = INFO_N / TX_N      # 1/2 transmitted rate
LLR_WIDTH = llr_quant.LLR_WIDTH_DEFAULT  # signed 8-bit
# Documented default, not a tuned optimum.  A short software-reference sweep
# (8-iteration LANES=8 fixed-point model) places the rate-1/2 k=1024 waterfall
# near ~2 dB Eb/N0 with scale 2.0 and no int8 input saturation; scale 1.0 is
# markedly more pessimistic.  Characterise the final value on hardware.
DEFAULT_LLR_SCALE = 2.0

PAYLOAD_PATTERNS = ("zeros", "ones", "alternating", "sparse", "dense", "random")


def ebn0_db_to_esn0_db(ebn0_db: float, code_rate: float = CODE_RATE) -> float:
    """Convert an Eb/N0 point (dB) to the equivalent symbol Es/N0 (dB)."""

    if code_rate <= 0.0:
        raise ValueError("code_rate must be positive")
    return float(ebn0_db) + 10.0 * float(np.log10(code_rate))


def esn0_db_to_ebn0_db(esn0_db: float, code_rate: float = CODE_RATE) -> float:
    """Inverse of :func:`ebn0_db_to_esn0_db`."""

    if code_rate <= 0.0:
        raise ValueError("code_rate must be positive")
    return float(esn0_db) - 10.0 * float(np.log10(code_rate))


def noise_sigma_for_ebn0(ebn0_db: float, code_rate: float = CODE_RATE) -> float:
    """AWGN sigma for a unit-energy BPSK symbol at the given Eb/N0."""

    return bpsk_awgn.awgn_noise_sigma(ebn0_db_to_esn0_db(ebn0_db, code_rate))


def array_sha256(values: np.ndarray) -> str:
    """Stable SHA-256 of an array's raw bytes (row-major, contiguous)."""

    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def make_payload(pattern: str, rng: np.random.Generator | None = None) -> np.ndarray:
    """Return a deterministic 1024-bit payload for a named pattern.

    ``random``, ``sparse`` and ``dense`` require an explicit ``rng`` so callers
    control seeding; the fixed patterns ignore it.
    """

    if pattern == "zeros":
        return np.zeros(INFO_N, dtype=np.uint8)
    if pattern == "ones":
        return np.ones(INFO_N, dtype=np.uint8)
    if pattern == "alternating":
        bits = np.zeros(INFO_N, dtype=np.uint8)
        bits[1::2] = 1
        return bits
    if pattern in ("random", "sparse", "dense"):
        if rng is None:
            raise ValueError(f"pattern {pattern!r} requires an explicit rng")
        if pattern == "random":
            return rng.integers(0, 2, INFO_N, dtype=np.uint8)
        density = 0.05 if pattern == "sparse" else 0.95
        return (rng.random(INFO_N) < density).astype(np.uint8)
    raise ValueError(f"unknown payload pattern {pattern!r}; expected {PAYLOAD_PATTERNS}")


@dataclass(frozen=True)
class Frame:
    """One deterministic transmitted frame and its quantized channel LLRs.

    Large floating arrays (symbols/noisy/float LLR) are optional and only
    retained when ``keep_arrays`` is set on :func:`build_frame`.
    """

    index: int
    seed: int
    ebn0_db: float | None
    esn0_db: float | None
    noise_sigma: float | None
    llr_scale: float
    pattern: str
    payload: np.ndarray            # (1024,) uint8
    tx_codeword: np.ndarray        # (2048,) uint8
    quantized_llr: np.ndarray      # (2048,) int16 holding signed int8 values
    saturated_inputs: int          # LLRs clipped by int8 saturation
    payload_sha256: str
    codeword_sha256: str
    llr_sha256: str
    float_llr: np.ndarray | None = None
    noisy_symbols: np.ndarray | None = None

    @property
    def channel_hard_errors(self) -> int:
        """Raw uncoded bit errors in the hard-sliced quantized LLR."""

        hard = llr_quant.hard_decision_from_llr(self.quantized_llr)
        return int(np.count_nonzero(hard != self.tx_codeword))


def _count_saturated(float_llr: np.ndarray, scale: float, width: int) -> int:
    lo, hi = llr_quant.signed_limits(width)
    scaled = float_llr * scale
    rounded = np.where(scaled >= 0, np.floor(scaled + 0.5), np.ceil(scaled - 0.5))
    return int(np.count_nonzero((rounded < lo) | (rounded > hi)))


def build_frame(
    *,
    index: int,
    seed: int,
    ebn0_db: float | None,
    pattern: str = "random",
    llr_scale: float = DEFAULT_LLR_SCALE,
    code_rate: float = CODE_RATE,
    llr_width: int = LLR_WIDTH,
    payload: Sequence[int] | np.ndarray | None = None,
    quantized_llr: Sequence[int] | np.ndarray | None = None,
    keep_arrays: bool = False,
) -> Frame:
    """Build one deterministic :class:`Frame`.

    Randomness comes from a single ``numpy.random.default_rng(seed)`` used for
    both the payload (when generated) and the AWGN realisation, so a given
    ``seed`` fully determines the frame.  ``ebn0_db=None`` selects the noiseless
    high-confidence LLR path (used for correctness vectors).  ``payload`` and
    ``quantized_llr`` overrides allow injecting hand-built pathological frames.
    """

    if llr_scale <= 0.0:
        raise ValueError("llr_scale must be positive")
    rng = np.random.default_rng(seed)

    if payload is None:
        payload_arr = make_payload(pattern, rng)
    else:
        payload_arr = np.asarray(payload, dtype=np.uint8).reshape(-1)
        if payload_arr.size != INFO_N:
            raise ValueError(f"payload must have {INFO_N} bits, got {payload_arr.size}")

    tx = ldpc_encoder.encode(payload_arr)

    esn0_db: float | None = None
    sigma: float | None = None
    float_llr: np.ndarray | None = None
    noisy: np.ndarray | None = None
    saturated = 0

    if quantized_llr is not None:
        q_llr = llr_quant.clip_signed(np.asarray(quantized_llr, dtype=np.int64), llr_width)
        if q_llr.size != TX_N:
            raise ValueError(f"quantized_llr must have {TX_N} entries, got {q_llr.size}")
    elif ebn0_db is None:
        q_llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0, llr_width=llr_width)
    else:
        esn0_db = ebn0_db_to_esn0_db(ebn0_db, code_rate)
        symbols = bpsk_awgn.bits_to_bpsk(tx)
        sigma = bpsk_awgn.awgn_noise_sigma(esn0_db)
        noisy = symbols + rng.normal(0.0, sigma, size=symbols.shape)
        float_llr = bpsk_awgn.llr_from_awgn_symbols(noisy, sigma)
        saturated = _count_saturated(float_llr, llr_scale, llr_width)
        q_llr = llr_quant.quantize_llr(float_llr, width=llr_width, scale=llr_scale)

    q_llr = np.asarray(q_llr, dtype=np.int16)

    return Frame(
        index=index,
        seed=seed,
        ebn0_db=ebn0_db,
        esn0_db=esn0_db,
        noise_sigma=sigma,
        llr_scale=llr_scale,
        pattern=pattern if payload is None else "explicit",
        payload=payload_arr,
        tx_codeword=tx,
        quantized_llr=q_llr,
        saturated_inputs=saturated,
        payload_sha256=array_sha256(payload_arr),
        codeword_sha256=array_sha256(tx),
        llr_sha256=array_sha256(q_llr.astype(np.int8)),
        float_llr=float_llr if keep_arrays else None,
        noisy_symbols=noisy if keep_arrays else None,
    )
