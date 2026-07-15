"""Tests for the benchmark channel / LLR pipeline (no hardware required)."""

import numpy as np
import pytest

from software.pynq_z2 import channel
from models import llr_quant


def test_ebn0_to_esn0_uses_code_rate():
    # Es/N0 = Eb/N0 + 10log10(1/2) = Eb/N0 - 3.0103 dB
    assert channel.ebn0_db_to_esn0_db(0.0) == pytest.approx(-3.01029995, abs=1e-6)
    assert channel.ebn0_db_to_esn0_db(3.0103) == pytest.approx(0.0, abs=1e-4)
    # round trip
    assert channel.esn0_db_to_ebn0_db(channel.ebn0_db_to_esn0_db(2.5)) == pytest.approx(2.5)


def test_noise_sigma_matches_variance_formula():
    # sigma^2 = 1 / (2 * R * (Eb/N0)_linear)
    ebn0 = 2.0
    r = channel.CODE_RATE
    lin = 10 ** (ebn0 / 10)
    expected = np.sqrt(1.0 / (2.0 * r * lin))
    assert channel.noise_sigma_for_ebn0(ebn0) == pytest.approx(expected)


def test_bpsk_sign_convention_bit0_positive():
    from models import bpsk_awgn
    sym = bpsk_awgn.bits_to_bpsk([0, 1, 0, 1])
    assert list(sym) == [1.0, -1.0, 1.0, -1.0]


def test_quantization_saturation_and_rounding():
    # Round half away from zero, saturate to int8.
    q = llr_quant.quantize_llr([0.4, 0.5, -0.5, 200.0, -200.0])
    assert list(q) == [0, 1, -1, 127, -128]


def test_build_frame_is_deterministic_in_seed():
    a = channel.build_frame(index=0, seed=7, ebn0_db=2.0)
    b = channel.build_frame(index=0, seed=7, ebn0_db=2.0)
    c = channel.build_frame(index=0, seed=8, ebn0_db=2.0)
    assert a.llr_sha256 == b.llr_sha256
    assert np.array_equal(a.quantized_llr, b.quantized_llr)
    assert a.llr_sha256 != c.llr_sha256


def test_build_frame_encodes_valid_codeword():
    from models import ar4ja_matrix as ar4ja
    f = channel.build_frame(index=0, seed=1, ebn0_db=None, pattern="random")
    # transmitted-codeword syndrome must be all zero
    syn = ar4ja.syndrome_transmitted(f.tx_codeword)
    assert int(syn.sum()) == 0
    assert f.quantized_llr.size == channel.TX_N
    assert f.quantized_llr.min() >= -128 and f.quantized_llr.max() <= 127


def test_noiseless_frame_hard_matches_codeword():
    f = channel.build_frame(index=0, seed=3, ebn0_db=None, pattern="random")
    assert f.channel_hard_errors == 0
    assert f.saturated_inputs == 0


def test_payload_patterns():
    rng = np.random.default_rng(0)
    assert channel.make_payload("zeros").sum() == 0
    assert channel.make_payload("ones").sum() == channel.INFO_N
    alt = channel.make_payload("alternating")
    assert alt[0] == 0 and alt[1] == 1
    sparse = channel.make_payload("sparse", rng)
    dense = channel.make_payload("dense", np.random.default_rng(0))
    assert sparse.mean() < 0.2 < dense.mean()
    with pytest.raises(ValueError):
        channel.make_payload("random")  # needs rng


def test_explicit_quantized_llr_override():
    llr = np.full(channel.TX_N, 127, dtype=np.int16)
    f = channel.build_frame(index=0, seed=1, ebn0_db=None, quantized_llr=llr)
    assert np.array_equal(f.quantized_llr, llr)
