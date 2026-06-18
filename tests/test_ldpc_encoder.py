import numpy as np

from models import ar4ja_matrix as ar4ja
from models import ldpc_encoder


def test_all_zero_payload_encodes_to_valid_codeword():
    payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
    full = ldpc_encoder.encode_full(payload)
    tx = ldpc_encoder.encode(payload)
    assert full.shape == (ar4ja.FULL_N,)
    assert tx.shape == (ar4ja.TX_N,)
    assert int(full.sum()) == 0
    assert int(ar4ja.syndrome_full(full).sum()) == 0
    assert int(ar4ja.syndrome_transmitted(tx, ar4ja.PUNCTURE_SOLVE).sum()) == 0


def test_random_payloads_encode_deterministically_and_satisfy_h():
    rng = np.random.default_rng(7)
    for _ in range(3):
        payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
        first = ldpc_encoder.encode_full(payload)
        second = ldpc_encoder.encode_full(payload)
        assert np.array_equal(first, second)
        assert int(ar4ja.syndrome_full(first).sum()) == 0
        assert np.array_equal(ldpc_encoder.encode(payload), first[: ar4ja.TX_N])


def test_single_bit_corruption_changes_transmitted_syndrome():
    rng = np.random.default_rng(11)
    payload = rng.integers(0, 2, ar4ja.INFO_N, dtype=np.uint8)
    tx = ldpc_encoder.encode(payload)
    assert int(ar4ja.syndrome_transmitted(tx, ar4ja.PUNCTURE_SOLVE).sum()) == 0
    tx[0] ^= 1
    assert int(ar4ja.syndrome_transmitted(tx, ar4ja.PUNCTURE_SOLVE).sum()) > 0


def test_payload_and_codeword_bit_ordering_are_documented():
    assert "index 0" in ldpc_encoder.PAYLOAD_BIT_ORDERING
    assert "indices 0..1023" in ldpc_encoder.TRANSMITTED_BIT_ORDERING.lower()
