import numpy as np

from models import ar4ja_matrix as ar4ja


def test_fixed_mode_dimensions():
    assert ar4ja.K == 2
    assert ar4ja.M == 512
    assert ar4ja.INFO_N == 1024
    assert ar4ja.TX_N == 2048
    assert ar4ja.FULL_N == 2560
    assert ar4ja.CHECKS == 1536
    assert ar4ja.validate_dimensions()


def test_permutation_matrices_are_one_hot():
    assert ar4ja.validate_permutations(range(1, 9))
    for pi_index in range(1, 9):
        perm = ar4ja.permutation(pi_index)
        assert len(perm) == ar4ja.M
        assert sorted(perm) == list(range(ar4ja.M))


def test_sparse_adjacency_shapes():
    h = ar4ja.build_h_full_sparse()
    assert len(h.row_to_cols) == ar4ja.CHECKS
    assert len(h.col_to_rows) == ar4ja.FULL_N
    assert max(len(cols) for cols in h.row_to_cols) == 6
    assert all(0 <= col < ar4ja.FULL_N for cols in h.row_to_cols for col in cols)


def test_transmitted_view_keeps_puncturing_explicit():
    view = ar4ja.build_h_transmitted_view(ar4ja.PUNCTURE_SOLVE)
    assert view.puncture_policy == ar4ja.PUNCTURE_SOLVE
    assert view.punctured_columns[0] == ar4ja.TX_N
    assert view.punctured_columns[-1] == ar4ja.FULL_N - 1
    assert len(view.row_to_tx_cols) == ar4ja.CHECKS
    assert len(view.row_to_punctured_cols) == ar4ja.CHECKS


def test_transmitted_reconstruction_for_zero_word():
    tx = np.zeros(ar4ja.TX_N, dtype=np.uint8)
    full = ar4ja.reconstruct_punctured(tx, ar4ja.PUNCTURE_SOLVE)
    assert full.shape == (ar4ja.FULL_N,)
    assert np.array_equal(full[: ar4ja.TX_N], tx)
    assert int(ar4ja.syndrome_transmitted(tx, ar4ja.PUNCTURE_SOLVE).sum()) == 0


def test_bit_ordering_is_documented():
    assert "index 0" in ar4ja.BIT_ORDERING
    assert "CCSDS Bit 0" in ar4ja.BIT_ORDERING

