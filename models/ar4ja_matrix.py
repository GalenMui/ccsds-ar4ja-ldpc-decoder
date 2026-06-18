"""CCSDS AR4JA rate-1/2, k=1024 parity-check construction.

This module implements only the fixed mode used by this repository:

* K = 2
* M = 512
* information bits = M*K = 1024
* full, unpunctured codeword bits = M*(K+3) = 2560
* transmitted codeword bits = M*(K+2) = 2048
* parity-check rows = 3*M = 1536

Bit ordering convention: Python index 0 is CCSDS Bit 0, the first transmitted
bit and the MSB when a field is interpreted as a binary value.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np

K = 2
M = 512
INFO_N = M * K
TX_N = M * (K + 2)
FULL_N = M * (K + 3)
CHECKS = 3 * M
PUNCTURED_N = M

BIT_ORDERING = (
    "Python index 0 is CCSDS Bit 0: the first transmitted bit and, for "
    "binary-valued fields, the most significant bit."
)

PUNCTURE_SOLVE = "solve_from_third_check_block"
SUPPORTED_PUNCTURE_POLICIES = (PUNCTURE_SOLVE,)

M_VALUES = (128, 256, 512, 1024, 2048, 4096, 8192)
M_INDEX = M_VALUES.index(M)

# Tables 7-3 and 7-4 from CCSDS 131.0-B-5. Each phi tuple is ordered for
# M = {128, 256, 512, 1024, 2048, 4096, 8192}.
_TABLE_7_3 = {
    1: (3, (1, 59, 16, 160, 108, 226, 1148), (0, 0, 0, 0, 0, 0, 0)),
    2: (0, (22, 18, 103, 241, 126, 618, 2032), (27, 32, 53, 182, 375, 767, 1822)),
    3: (1, (0, 52, 105, 185, 238, 404, 249), (30, 21, 74, 249, 436, 227, 203)),
    4: (2, (26, 23, 0, 251, 481, 32, 1807), (28, 36, 45, 65, 350, 247, 882)),
    5: (2, (0, 11, 50, 209, 96, 912, 485), (7, 30, 47, 70, 260, 284, 1989)),
    6: (3, (10, 7, 29, 103, 28, 950, 1044), (1, 29, 0, 141, 84, 370, 957)),
    7: (0, (5, 22, 115, 90, 59, 534, 717), (8, 44, 59, 237, 318, 482, 1705)),
    8: (1, (18, 25, 30, 184, 225, 63, 873), (20, 29, 102, 77, 382, 273, 1083)),
    9: (0, (3, 27, 92, 248, 323, 971, 364), (26, 39, 25, 55, 169, 886, 1072)),
    10: (1, (22, 30, 78, 12, 28, 304, 1926), (24, 14, 3, 12, 213, 634, 354)),
    11: (2, (3, 43, 70, 111, 386, 409, 1241), (4, 22, 88, 227, 67, 762, 1942)),
    12: (0, (8, 14, 66, 66, 305, 708, 1769), (12, 15, 65, 42, 313, 184, 446)),
    13: (2, (25, 46, 39, 173, 34, 719, 532), (23, 48, 62, 52, 242, 696, 1456)),
    14: (3, (25, 62, 84, 42, 510, 176, 768), (15, 55, 68, 243, 188, 413, 1940)),
    15: (0, (2, 44, 79, 157, 147, 743, 1138), (15, 39, 91, 179, 1, 854, 1660)),
    16: (1, (27, 12, 70, 174, 199, 759, 965), (22, 11, 70, 250, 306, 544, 1661)),
    17: (2, (7, 38, 29, 104, 347, 674, 141), (31, 1, 115, 247, 397, 864, 587)),
    18: (0, (7, 47, 32, 144, 391, 958, 1527), (3, 50, 31, 164, 80, 82, 708)),
    19: (1, (15, 1, 45, 43, 165, 984, 505), (29, 40, 121, 17, 33, 1009, 1466)),
    20: (2, (10, 52, 113, 181, 414, 11, 1312), (21, 62, 45, 31, 7, 437, 433)),
    21: (0, (4, 61, 86, 250, 97, 413, 1840), (2, 27, 56, 149, 447, 36, 1345)),
    22: (1, (19, 10, 1, 202, 158, 925, 709), (5, 38, 54, 105, 336, 562, 867)),
    23: (2, (7, 55, 42, 68, 86, 687, 1427), (11, 40, 108, 183, 424, 816, 1551)),
    24: (1, (9, 7, 118, 177, 168, 752, 989), (26, 15, 14, 153, 134, 452, 2041)),
    25: (2, (26, 12, 33, 170, 506, 867, 1925), (9, 11, 30, 177, 152, 290, 1383)),
    26: (3, (17, 2, 126, 89, 489, 323, 270), (17, 18, 116, 19, 492, 778, 1790)),
}

_TABLE_7_4 = {
    1: ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),
    2: ((12, 46, 8, 35, 219, 254, 318), (13, 44, 35, 162, 312, 285, 1189)),
    3: ((30, 45, 119, 167, 16, 790, 494), (19, 51, 97, 7, 503, 554, 458)),
    4: ((18, 27, 89, 214, 263, 642, 1467), (14, 12, 112, 31, 388, 809, 460)),
    5: ((10, 48, 31, 84, 415, 248, 757), (15, 15, 64, 164, 48, 185, 1039)),
    6: ((16, 37, 122, 206, 403, 899, 1085), (20, 12, 93, 11, 7, 49, 1000)),
    7: ((13, 41, 1, 122, 184, 328, 1630), (17, 4, 99, 237, 185, 101, 1265)),
    8: ((9, 13, 69, 67, 279, 518, 64), (4, 7, 94, 125, 328, 82, 1223)),
    9: ((7, 9, 92, 147, 198, 477, 689), (4, 2, 103, 133, 254, 898, 874)),
    10: ((15, 49, 47, 54, 307, 404, 1300), (11, 30, 91, 99, 202, 627, 1292)),
    11: ((16, 36, 11, 23, 432, 698, 148), (17, 53, 3, 105, 285, 154, 1491)),
    12: ((18, 10, 31, 93, 240, 160, 777), (20, 23, 6, 17, 11, 65, 631)),
    13: ((4, 11, 19, 20, 454, 497, 1431), (8, 29, 39, 97, 168, 81, 464)),
    14: ((23, 18, 66, 197, 294, 100, 659), (22, 37, 113, 91, 127, 823, 461)),
    15: ((5, 54, 49, 46, 479, 518, 352), (19, 42, 92, 211, 8, 50, 844)),
    16: ((3, 40, 81, 162, 289, 92, 1177), (15, 48, 119, 128, 437, 413, 392)),
    17: ((29, 27, 96, 101, 373, 464, 836), (5, 4, 74, 82, 475, 462, 922)),
    18: ((11, 35, 38, 76, 104, 592, 1572), (21, 10, 73, 115, 85, 175, 256)),
    19: ((4, 25, 83, 78, 141, 198, 348), (17, 18, 116, 248, 419, 715, 1986)),
    20: ((8, 46, 42, 253, 270, 856, 1040), (9, 56, 31, 62, 459, 537, 19)),
    21: ((2, 24, 58, 124, 439, 235, 779), (20, 9, 127, 26, 468, 722, 266)),
    22: ((11, 33, 24, 143, 333, 134, 476), (18, 11, 98, 140, 209, 37, 471)),
    23: ((11, 18, 25, 63, 399, 542, 191), (31, 23, 23, 121, 311, 488, 1166)),
    24: ((3, 37, 92, 41, 14, 545, 1393), (13, 8, 38, 12, 211, 179, 1300)),
    25: ((15, 35, 38, 214, 277, 777, 1752), (2, 7, 18, 41, 510, 430, 1033)),
    26: ((13, 21, 120, 70, 412, 483, 1627), (18, 24, 62, 249, 320, 264, 1606)),
}


@dataclass(frozen=True)
class SparseParityCheck:
    """Sparse parity-check matrix in row adjacency form."""

    n_rows: int
    n_cols: int
    row_to_cols: tuple[tuple[int, ...], ...]

    @property
    def col_to_rows(self) -> tuple[tuple[int, ...], ...]:
        cols: list[list[int]] = [[] for _ in range(self.n_cols)]
        for row, row_cols in enumerate(self.row_to_cols):
            for col in row_cols:
                cols[col].append(row)
        return tuple(tuple(rows) for rows in cols)


@dataclass(frozen=True)
class TransmittedView:
    """Explicit split between transmitted and punctured columns of full H."""

    n_rows: int
    transmitted_cols: int
    full_cols: int
    row_to_tx_cols: tuple[tuple[int, ...], ...]
    row_to_punctured_cols: tuple[tuple[int, ...], ...]
    punctured_columns: tuple[int, ...]
    puncture_policy: str


def theta(pi_index: int) -> int:
    return _TABLE_7_3[pi_index][0]


def phi(pi_index: int, quarter_index: int, m: int = M) -> int:
    """Return phi_k(j, M) for j in {0, 1, 2, 3}."""

    if quarter_index not in (0, 1, 2, 3):
        raise ValueError(f"quarter_index must be 0..3, got {quarter_index}")
    try:
        m_index = M_VALUES.index(m)
    except ValueError as exc:
        raise ValueError(f"unsupported M={m}; expected one of {M_VALUES}") from exc
    if quarter_index in (0, 1):
        return _TABLE_7_3[pi_index][1 + quarter_index][m_index]
    return _TABLE_7_4[pi_index][quarter_index - 2][m_index]


@lru_cache(maxsize=None)
def permutation(pi_index: int, m: int = M) -> tuple[int, ...]:
    """Return pi_k(i) for rows i=0..M-1.

    The corresponding permutation matrix has a one in row i and column
    permutation(k)[i].
    """

    if pi_index not in _TABLE_7_3:
        raise ValueError(f"unsupported permutation index {pi_index}")
    if m % 4:
        raise ValueError("M must be divisible by 4")

    quarter = m // 4
    result: list[int] = []
    for i in range(m):
        j = (4 * i) // m
        col = quarter * ((theta(pi_index) + j) % 4)
        col += (phi(pi_index, j, m) + i) % quarter
        result.append(col)
    return tuple(result)


def _toggle(rows: list[set[int]], row: int, col: int) -> None:
    if col in rows[row]:
        rows[row].remove(col)
    else:
        rows[row].add(col)


def _add_identity(rows: list[set[int]], row_block: int, col_block: int) -> None:
    for i in range(M):
        _toggle(rows, row_block * M + i, col_block * M + i)


def _add_permutation(
    rows: list[set[int]],
    row_block: int,
    col_block: int,
    pi_index: int,
) -> None:
    perm = permutation(pi_index)
    for i, col in enumerate(perm):
        _toggle(rows, row_block * M + i, col_block * M + col)


@lru_cache(maxsize=1)
def build_h_full_sparse() -> SparseParityCheck:
    """Build the full 1536 x 2560 unpunctured CCSDS H_1/2 matrix."""

    rows: list[set[int]] = [set() for _ in range(CHECKS)]

    # Block row 0: [0, 0, I, 0, I + Pi_1]
    _add_identity(rows, 0, 2)
    _add_identity(rows, 0, 4)
    _add_permutation(rows, 0, 4, 1)

    # Block row 1: [I, I, 0, I, Pi_2 + Pi_3 + Pi_4]
    _add_identity(rows, 1, 0)
    _add_identity(rows, 1, 1)
    _add_identity(rows, 1, 3)
    _add_permutation(rows, 1, 4, 2)
    _add_permutation(rows, 1, 4, 3)
    _add_permutation(rows, 1, 4, 4)

    # Block row 2: [I, Pi_5 + Pi_6, 0, Pi_7 + Pi_8, I]
    _add_identity(rows, 2, 0)
    _add_permutation(rows, 2, 1, 5)
    _add_permutation(rows, 2, 1, 6)
    _add_permutation(rows, 2, 3, 7)
    _add_permutation(rows, 2, 3, 8)
    _add_identity(rows, 2, 4)

    row_to_cols = tuple(tuple(sorted(row)) for row in rows)
    return SparseParityCheck(n_rows=CHECKS, n_cols=FULL_N, row_to_cols=row_to_cols)


def build_h_transmitted_view(
    puncture_policy: str = PUNCTURE_SOLVE,
) -> TransmittedView:
    """Return full-H adjacency split into transmitted and punctured columns."""

    if puncture_policy not in SUPPORTED_PUNCTURE_POLICIES:
        raise ValueError(
            f"unsupported puncture policy {puncture_policy!r}; "
            f"supported policies: {SUPPORTED_PUNCTURE_POLICIES}"
        )

    h = build_h_full_sparse()
    row_to_tx_cols: list[tuple[int, ...]] = []
    row_to_punctured_cols: list[tuple[int, ...]] = []
    for row_cols in h.row_to_cols:
        row_to_tx_cols.append(tuple(col for col in row_cols if col < TX_N))
        row_to_punctured_cols.append(tuple(col for col in row_cols if col >= TX_N))

    return TransmittedView(
        n_rows=CHECKS,
        transmitted_cols=TX_N,
        full_cols=FULL_N,
        row_to_tx_cols=tuple(row_to_tx_cols),
        row_to_punctured_cols=tuple(row_to_punctured_cols),
        punctured_columns=tuple(range(TX_N, FULL_N)),
        puncture_policy=puncture_policy,
    )


def row_to_cols() -> tuple[tuple[int, ...], ...]:
    return build_h_full_sparse().row_to_cols


def col_to_rows() -> tuple[tuple[int, ...], ...]:
    return build_h_full_sparse().col_to_rows


def _as_bit_array(bits: Sequence[int] | np.ndarray, expected_len: int) -> np.ndarray:
    arr = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if arr.size != expected_len:
        raise ValueError(f"expected {expected_len} bits, got {arr.size}")
    if np.any((arr != 0) & (arr != 1)):
        raise ValueError("bits must contain only 0 and 1")
    return arr


def syndrome_full(codeword_2560: Sequence[int] | np.ndarray) -> np.ndarray:
    """Compute H*c over GF(2) for a full unpunctured 2560-bit codeword."""

    bits = _as_bit_array(codeword_2560, FULL_N)
    syndrome = np.zeros(CHECKS, dtype=np.uint8)
    for row, cols in enumerate(build_h_full_sparse().row_to_cols):
        value = 0
        for col in cols:
            value ^= int(bits[col])
        syndrome[row] = value
    return syndrome


def reconstruct_punctured(
    codeword_2048: Sequence[int] | np.ndarray,
    puncture_policy: str = PUNCTURE_SOLVE,
) -> np.ndarray:
    """Reconstruct the 512 punctured symbols using an explicit policy.

    The supported policy uses block row 2 of H_1/2, whose last block is I_M.
    For each i, the missing symbol in column 2048+i is set to the XOR of the
    transmitted symbols participating in check row 1024+i. This makes the
    third check block zero without assuming any punctured symbol is zero.
    """

    if puncture_policy != PUNCTURE_SOLVE:
        raise ValueError(
            f"unsupported puncture policy {puncture_policy!r}; "
            f"supported policies: {SUPPORTED_PUNCTURE_POLICIES}"
        )

    tx = _as_bit_array(codeword_2048, TX_N)
    full = np.zeros(FULL_N, dtype=np.uint8)
    full[:TX_N] = tx
    h = build_h_full_sparse()
    for i in range(M):
        row = 2 * M + i
        value = 0
        punctured_cols: list[int] = []
        for col in h.row_to_cols[row]:
            if col < TX_N:
                value ^= int(full[col])
            else:
                punctured_cols.append(col)
        expected_col = TX_N + i
        if punctured_cols != [expected_col]:
            raise RuntimeError(
                "unexpected puncturing structure in row "
                f"{row}: expected {[expected_col]}, got {punctured_cols}"
            )
        full[expected_col] = value
    return full


def syndrome_transmitted(
    codeword_2048: Sequence[int] | np.ndarray,
    puncture_policy: str = PUNCTURE_SOLVE,
) -> np.ndarray:
    """Compute the explicit transmitted-codeword syndrome.

    The transmitted word is first expanded using ``puncture_policy`` and then
    the full 1536-row syndrome is evaluated. With the default policy, rows
    1024..1535 are zero by construction and rows 0..1023 carry the effective
    transmitted-codeword syndrome.
    """

    full = reconstruct_punctured(codeword_2048, puncture_policy)
    return syndrome_full(full)


def validate_dimensions() -> bool:
    h = build_h_full_sparse()
    if K != 2 or M != 512:
        raise AssertionError("unexpected fixed-mode K/M constants")
    if INFO_N != 1024 or TX_N != 2048 or FULL_N != 2560 or CHECKS != 1536:
        raise AssertionError("unexpected fixed-mode dimensions")
    if h.n_rows != CHECKS or h.n_cols != FULL_N or len(h.row_to_cols) != CHECKS:
        raise AssertionError("sparse H dimensions are inconsistent")
    for row, cols in enumerate(h.row_to_cols):
        if any(col < 0 or col >= FULL_N for col in cols):
            raise AssertionError(f"row {row} contains an out-of-range column")
    return True


def validate_permutations(pi_indices: Iterable[int] = range(1, 27)) -> bool:
    expected = list(range(M))
    for pi_index in pi_indices:
        perm = permutation(pi_index)
        if len(perm) != M:
            raise AssertionError(f"Pi_{pi_index} has length {len(perm)}")
        if sorted(perm) != expected:
            raise AssertionError(f"Pi_{pi_index} is not a one-hot permutation")
    return True

