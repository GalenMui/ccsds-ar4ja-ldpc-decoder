"""Deterministic hardware correctness vectors for the LDPC decoder.

Each vector is a fully determined :class:`channel.Frame` plus metadata.  The
correctness campaign feeds every vector to both the hardware and the
bit-accurate software model and compares status, iteration count and every
decoded bit.  ``expect_success`` is an informational hint (``None`` when the
outcome is intentionally undetermined); the authoritative expectation is always
the software model run on the identical quantized LLRs.

Categories are chosen to cover the guardrail list: fixed payload patterns at
zero noise, deterministic random frames, controlled LLR perturbations, frames
that require iterations, near-boundary and expected-fail frames, and int8
saturation extremes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:  # flat layout on the board
    import channel
except ImportError:  # package layout in the repository
    from software.pynq_z2 import channel


@dataclass(frozen=True)
class Vector:
    name: str
    category: str
    frame: "channel.Frame"
    notes: str
    expect_success: bool | None = None
    repeat: int = 1


def _saturation_frame(index: int, seed: int, sign: int, scale: float) -> "channel.Frame":
    """Zero payload with every transmitted LLR forced to the int8 extreme."""

    tx_sign = np.where(channel.build_frame(
        index=index, seed=seed, ebn0_db=None, pattern="zeros", llr_scale=scale
    ).tx_codeword == 0, 1, -1)
    extreme = (sign * 127) * tx_sign
    return channel.build_frame(
        index=index, seed=seed, ebn0_db=None, pattern="zeros",
        llr_scale=scale, quantized_llr=extreme,
    )


def correctness_vectors(
    *,
    llr_scale: float = channel.DEFAULT_LLR_SCALE,
    seed: int = 20260715,
    random_count: int = 4,
) -> list[Vector]:
    """Return the ordered deterministic correctness-suite vectors."""

    vectors: list[Vector] = []
    idx = 0

    for pattern in ("zeros", "ones", "alternating"):
        vectors.append(Vector(
            name=f"noiseless_{pattern}",
            category="fixed_pattern_zero_noise",
            frame=channel.build_frame(index=idx, seed=seed + idx, ebn0_db=None,
                                      pattern=pattern, llr_scale=llr_scale),
            notes="high-confidence LLRs, expect zero-iteration success",
            expect_success=True,
        ))
        idx += 1

    for r in range(random_count):
        vectors.append(Vector(
            name=f"noiseless_random_{r}",
            category="random_zero_noise",
            frame=channel.build_frame(index=idx, seed=seed + 100 + r, ebn0_db=None,
                                      pattern="random", llr_scale=llr_scale),
            notes="deterministic random payload, high-confidence LLRs",
            expect_success=True,
        ))
        idx += 1

    # Controlled perturbation: a clean frame with a handful of flipped-sign LLRs
    # the decoder should still correct.
    base = channel.build_frame(index=idx, seed=seed + 200, ebn0_db=None,
                               pattern="random", llr_scale=llr_scale)
    perturbed = base.quantized_llr.astype(np.int16).copy()
    for pos in (3, 101, 777, 1500):
        perturbed[pos] = -np.sign(perturbed[pos] if perturbed[pos] != 0 else 1) * 8
    vectors.append(Vector(
        name="perturbed_few_flips",
        category="controlled_perturbation",
        frame=channel.build_frame(index=idx, seed=seed + 200, ebn0_db=None,
                                  pattern="random", llr_scale=llr_scale,
                                  payload=base.payload, quantized_llr=perturbed),
        notes="four weakened/flipped input LLRs; expect >0 iterations",
        expect_success=None,
    ))
    idx += 1

    # Frames that should require iterations: moderate-noise operating points.
    for ebn0 in (2.5, 2.0):
        vectors.append(Vector(
            name=f"noisy_ebn0_{ebn0:g}",
            category="requires_iterations",
            frame=channel.build_frame(index=idx, seed=seed + 300 + int(ebn0 * 10),
                                      ebn0_db=ebn0, pattern="random", llr_scale=llr_scale),
            notes="operating point above the software waterfall",
            expect_success=None,
        ))
        idx += 1

    # Near / beyond the decode boundary.
    vectors.append(Vector(
        name="near_boundary_ebn0_1.5",
        category="near_boundary",
        frame=channel.build_frame(index=idx, seed=seed + 400, ebn0_db=1.5,
                                  pattern="random", llr_scale=llr_scale),
        notes="near the transition region",
        expect_success=None,
    ))
    idx += 1
    vectors.append(Vector(
        name="expected_fail_ebn0_-1.0",
        category="expected_fail",
        frame=channel.build_frame(index=idx, seed=seed + 500, ebn0_db=-1.0,
                                  pattern="random", llr_scale=llr_scale),
        notes="well below the waterfall; decoder should declare failure",
        expect_success=False,
    ))
    idx += 1

    # int8 saturation extremes (consistent, so still a valid codeword direction).
    vectors.append(Vector(
        name="saturated_max_positive",
        category="saturation_extreme",
        frame=_saturation_frame(idx, seed + 600, sign=1, scale=llr_scale),
        notes="every LLR at the int8 extreme matching the zero codeword",
        expect_success=True,
    ))
    idx += 1

    # Repeated identical frame to detect nondeterminism.
    vectors.append(Vector(
        name="repeat_zero_noise",
        category="repeatability",
        frame=channel.build_frame(index=idx, seed=seed + 700, ebn0_db=None,
                                  pattern="random", llr_scale=llr_scale),
        notes="same frame run several times; every run must match",
        expect_success=True,
        repeat=5,
    ))
    idx += 1

    return vectors
