"""Tests for metric aggregation, Wilson intervals, and throughput math."""

import math

import pytest

from software.pynq_z2 import metrics


def test_wilson_zero_errors_gives_nonzero_upper_bound():
    low, high = metrics.wilson_interval(0, 100)
    assert low == 0.0
    assert 0.03 < high < 0.05  # ~0.037 for n=100


def test_wilson_known_proportion():
    low, high = metrics.wilson_interval(5, 100)
    assert low == pytest.approx(0.0215, abs=0.003)
    assert high == pytest.approx(0.1119, abs=0.003)


def test_wilson_zero_trials():
    assert metrics.wilson_interval(0, 0) == (0.0, 1.0)


def test_percentile_interpolation():
    data = [1, 2, 3, 4]
    assert metrics.percentile(data, 50) == pytest.approx(2.5)
    assert metrics.percentile(data, 0) == 1
    assert metrics.percentile(data, 100) == 4
    assert math.isnan(metrics.percentile([], 50))


def test_ber_fer_definitions():
    acc = metrics.PointAccumulator(label="p")
    # 3 clean frames, 1 frame with 2 bit errors (frame error), 1 decoder failure
    for _ in range(3):
        acc.add(bit_errors=0, frame_error=False, decoder_failure=False,
                undetected_error=False, iterations=2, saturation=0, cycles=2625)
    acc.add(bit_errors=2, frame_error=True, decoder_failure=False,
            undetected_error=True, iterations=8, saturation=0, cycles=31200)
    acc.add(bit_errors=0, frame_error=True, decoder_failure=True,
            undetected_error=False, iterations=8, saturation=1, cycles=31200)
    s = acc.summary(elapsed_s=1.0)
    assert s["frames_completed"] == 5
    assert s["info_bit_errors"] == 2
    assert s["ber"] == pytest.approx(2 / (5 * 1024))
    assert s["fer"] == pytest.approx(2 / 5)
    assert s["undetected_errors"] == 1
    assert s["decoder_failures"] == 1
    assert s["saturated_frames"] == 1


def test_infrastructure_failures_excluded_from_fer():
    acc = metrics.PointAccumulator(label="p")
    acc.add(bit_errors=0, frame_error=False, decoder_failure=False,
            undetected_error=False, iterations=1, saturation=0)
    acc.add_infrastructure_failure(timeout=True)
    acc.add_infrastructure_failure(dma_error=True)
    s = acc.summary()
    assert s["frames_attempted"] == 3
    assert s["frames_completed"] == 1
    assert s["fer"] == 0.0  # infra failures not counted as frame errors
    assert s["infrastructure_failures"] == 2
    assert s["timeouts"] == 1
    assert s["dma_errors"] == 1


def test_throughput_math():
    acc = metrics.PointAccumulator(label="p")
    for _ in range(100):
        acc.add(bit_errors=0, frame_error=False, decoder_failure=False,
                undetected_error=False, iterations=1, saturation=0, cycles=2625)
    s = acc.summary(elapsed_s=1.0)
    assert s["frames_per_second"] == pytest.approx(100.0)
    assert s["info_throughput_mbps"] == pytest.approx(100 * 1024 / 1e6)
    assert s["coded_throughput_mbps"] == pytest.approx(100 * 2048 / 1e6)
    assert s["core_latency_us_mean"] == pytest.approx(2625 / 100e6 * 1e6)


def test_normal_ppf_roundtrip():
    assert metrics.normal_ppf(0.975) == pytest.approx(1.959963985, abs=1e-4)
    assert metrics.normal_ppf(0.5) == pytest.approx(0.0, abs=1e-6)
