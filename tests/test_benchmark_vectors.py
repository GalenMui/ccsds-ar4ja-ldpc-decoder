"""Tests for the deterministic correctness-vector set (construction only)."""

import numpy as np

from software.pynq_z2 import channel, vectors


def test_correctness_vectors_are_deterministic_and_well_formed():
    a = vectors.correctness_vectors(seed=123)
    b = vectors.correctness_vectors(seed=123)
    assert len(a) == len(b) and len(a) > 8
    names = {v.name for v in a}
    categories = {v.category for v in a}
    # every guardrail category is represented
    for cat in ("fixed_pattern_zero_noise", "random_zero_noise",
                "controlled_perturbation", "requires_iterations",
                "near_boundary", "expected_fail", "saturation_extreme",
                "repeatability"):
        assert cat in categories
    assert len(names) == len(a)  # unique names
    for va, vb in zip(a, b):
        assert va.frame.llr_sha256 == vb.frame.llr_sha256
        assert va.frame.quantized_llr.size == channel.TX_N
        assert va.frame.quantized_llr.min() >= -128
        assert va.frame.quantized_llr.max() <= 127


def test_saturation_vector_uses_int8_extremes():
    vecs = {v.name: v for v in vectors.correctness_vectors(seed=1)}
    sat = vecs["saturated_max_positive"].frame.quantized_llr
    assert set(np.unique(np.abs(sat)).tolist()) <= {127}


def test_repeat_vector_requests_multiple_runs():
    vecs = {v.name: v for v in vectors.correctness_vectors(seed=1)}
    assert vecs["repeat_zero_noise"].repeat >= 2
