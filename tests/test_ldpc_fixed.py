import numpy as np

from models import ar4ja_matrix as ar4ja
from models import bpsk_awgn
from models import ldpc_encoder
from models import llr_quant
from models.ldpc_decoder_fixed import decode_normalized_min_sum_fixed
from models.ldpc_schedule import SUPPORTED_LANES


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


def test_layered_decoder_recovers_punctured_variables_for_noiseless_word():
    payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    payload[0] = 1
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0)

    result = decode_normalized_min_sum_fixed(llr, iterations=1)
    full_expected = ldpc_encoder.encode_full(payload)

    assert result.converged
    assert result.iterations == 1
    assert result.saturation_count == 0
    assert np.array_equal(result.hard_full, full_expected)


def test_low_confidence_failure_runs_to_max_iterations():
    rng = np.random.default_rng(0)
    llr = rng.integers(-2, 3, ar4ja.TX_N, dtype=np.int16)

    result = decode_normalized_min_sum_fixed(llr, iterations=8)

    assert not result.converged
    assert result.decoder_fail
    assert result.iterations == 8


def test_parallel_schedules_match_row_serial_model():
    rng = np.random.default_rng(11)
    payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=24.0)

    baseline = decode_normalized_min_sum_fixed(llr, iterations=3, lanes=1)
    for lanes in SUPPORTED_LANES:
        result = decode_normalized_min_sum_fixed(llr, iterations=3, lanes=lanes)
        assert result.iterations == baseline.iterations
        assert result.converged == baseline.converged
        assert result.saturation_count == baseline.saturation_count
        assert np.array_equal(result.hard_full, baseline.hard_full)
        assert np.array_equal(result.posterior_llr, baseline.posterior_llr)


def test_parallel_trace_records_group_lane_and_edge_updates():
    payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    payload[0] = 1
    tx = ldpc_encoder.encode(payload)
    llr = bpsk_awgn.noiseless_llr(tx, magnitude=32.0)

    result = decode_normalized_min_sum_fixed(llr, iterations=1, lanes=8, trace=True)

    assert result.trace
    first = result.trace[0]
    assert first.iteration == 1
    assert first.group == 0
    assert first.lane == 0
    assert first.row == 0
    assert first.edge_slot == 0
    assert first.variable == ar4ja.row_to_cols()[0][0]
