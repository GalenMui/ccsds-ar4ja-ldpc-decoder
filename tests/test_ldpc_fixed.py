import numpy as np

from models import ar4ja_matrix as ar4ja
from models import bpsk_awgn
from models import ldpc_encoder
from models import llr_quant
from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed


def test_llr_hard_decision_sign_and_zero_tie():
    assert int(llr_quant.hard_decision_from_llr(9)) == 0
    assert int(llr_quant.hard_decision_from_llr(-1)) == 1
    assert int(llr_quant.hard_decision_from_llr(0)) == llr_quant.ZERO_LLR_HARD_DECISION


def test_llr_saturation_at_signed_limits():
    q = llr_quant.quantize_llr(np.array([-1000.0, -128.0, 0.0, 127.0, 1000.0]))
    assert q.tolist() == [-128, -128, 0, 127, 127]


def test_awgn_generation_is_deterministic_for_fixed_seed():
    bits = np.array([0, 1, 0, 1, 1, 0], dtype=np.uint8)
    first = bpsk_awgn.transmit_bpsk_awgn(bits, snr_db=4.5, seed=123)
    second = bpsk_awgn.transmit_bpsk_awgn(bits, snr_db=4.5, seed=123)
    assert np.array_equal(first.bits, second.bits)
    assert np.allclose(first.noisy_symbols, second.noisy_symbols)
    assert np.allclose(first.llr, second.llr)
    assert np.array_equal(first.quantized_llr, second.quantized_llr)


def test_noiseless_high_confidence_llrs_match_transmitted_bits():
    rng = np.random.default_rng(5)
    payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0)
    hard = llr_quant.hard_decision_from_llr(llr)
    assert np.array_equal(hard, tx)

    result = decode_normalized_min_sum_fixed(llr, iterations=0)
    assert np.array_equal(result.hard_transmitted, tx)

