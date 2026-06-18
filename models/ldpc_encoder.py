"""Systematic encoder for the fixed CCSDS AR4JA rate-1/2 mode.

Payload bit index 0 is CCSDS Bit 0, the first information bit. The full
unpunctured codeword order is:

    [information block 0, information block 1, parity block 0,
     parity block 1, punctured parity block 2]

The transmitted 2048-bit codeword omits the final 512-bit punctured parity
block. This encoder derives the parity symbols from the same P and Q partition
defined by CCSDS 131.0-B-5 section 7.4.3.3, specialized to the rate-1/2 block
structure.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import numpy as np

from . import ar4ja_matrix as ar4ja

PAYLOAD_BIT_ORDERING = ar4ja.BIT_ORDERING
TRANSMITTED_BIT_ORDERING = (
    "Transmitted codeword index 0 is the first information bit. Indices "
    "0..1023 are systematic payload bits, and indices 1024..2047 are the "
    "first two 512-bit parity blocks. Full-codeword indices 2048..2559 are "
    "punctured and are not transmitted."
)


def _as_payload(payload_bits: Sequence[int] | np.ndarray) -> np.ndarray:
    arr = np.asarray(payload_bits, dtype=np.uint8).reshape(-1)
    if arr.size != ar4ja.INFO_N:
        raise ValueError(f"expected {ar4ja.INFO_N} payload bits, got {arr.size}")
    if np.any((arr != 0) & (arr != 1)):
        raise ValueError("payload bits must contain only 0 and 1")
    return arr


def _permute_sum(pi_indices: Sequence[int], vector: np.ndarray) -> np.ndarray:
    out = np.zeros(ar4ja.M, dtype=np.uint8)
    for pi_index in pi_indices:
        perm = ar4ja.permutation(pi_index)
        for row, col in enumerate(perm):
            out[row] ^= vector[col]
    return out


def _xor_row_set(rows: list[set[int]], row: int, cols: Sequence[int]) -> None:
    for col in cols:
        if col in rows[row]:
            rows[row].remove(col)
        else:
            rows[row].add(col)


@lru_cache(maxsize=1)
def _p2_system_rows() -> tuple[int, ...]:
    """Rows of A = I + (Pi_7 + Pi_8)(Pi_2 + Pi_3 + Pi_4) as bit masks."""

    c_rows: list[set[int]] = []
    for row in range(ar4ja.M):
        row_cols: set[int] = set()
        for pi_index in (2, 3, 4):
            col = ar4ja.permutation(pi_index)[row]
            if col in row_cols:
                row_cols.remove(col)
            else:
                row_cols.add(col)
        c_rows.append(row_cols)

    rows = [set([row]) for row in range(ar4ja.M)]
    for row in range(ar4ja.M):
        for pi_index in (7, 8):
            c_row = ar4ja.permutation(pi_index)[row]
            _xor_row_set(rows, row, tuple(c_rows[c_row]))

    masks = []
    for cols in rows:
        mask = 0
        for col in cols:
            mask |= 1 << col
        masks.append(mask)
    return tuple(masks)


@lru_cache(maxsize=1)
def _p2_system_inverse_rows() -> tuple[int, ...]:
    """Return inverse rows for the fixed 512 x 512 GF(2) p2 system."""

    n = ar4ja.M
    rows = [row | (1 << (n + i)) for i, row in enumerate(_p2_system_rows())]

    rank = 0
    for col in range(n):
        pivot = None
        for candidate in range(rank, n):
            if (rows[candidate] >> col) & 1:
                pivot = candidate
                break
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        for r in range(n):
            if r != rank and ((rows[r] >> col) & 1):
                rows[r] ^= rows[rank]
        rank += 1

    if rank != n:
        raise RuntimeError("rate-1/2 P submatrix did not yield a full-rank p2 system")

    left_mask = (1 << n) - 1
    inverse_rows: list[int] = []
    for i, row in enumerate(rows):
        if (row & left_mask) != (1 << i):
            raise RuntimeError("GF(2) elimination did not reduce the p2 system to identity")
        inverse_rows.append(row >> n)
    return tuple(inverse_rows)


def _bits_to_mask(bits: np.ndarray) -> int:
    mask = 0
    for i, bit in enumerate(bits):
        if int(bit):
            mask |= 1 << i
    return mask


def _mask_to_bits(mask: int, n: int) -> np.ndarray:
    return np.fromiter(((mask >> i) & 1 for i in range(n)), dtype=np.uint8, count=n)


def _solve_p2(rhs: np.ndarray) -> np.ndarray:
    rhs_mask = _bits_to_mask(rhs)
    solution_mask = 0
    for row, inv_mask in enumerate(_p2_system_inverse_rows()):
        if (inv_mask & rhs_mask).bit_count() & 1:
            solution_mask |= 1 << row
    return _mask_to_bits(solution_mask, ar4ja.M)


def encode_full(payload_bits: Sequence[int] | np.ndarray) -> np.ndarray:
    """Encode a 1024-bit payload into the full unpunctured 2560-bit codeword."""

    payload = _as_payload(payload_bits)
    u0 = payload[: ar4ja.M]
    u1 = payload[ar4ja.M :]

    b_u0 = _permute_sum((7, 8), u0)
    d_u1 = _permute_sum((5, 6), u1)
    b_u1 = _permute_sum((7, 8), u1)
    rhs = u0 ^ b_u0 ^ d_u1 ^ b_u1

    p2 = _solve_p2(rhs)
    c_p2 = _permute_sum((2, 3, 4), p2)
    p1 = u0 ^ u1 ^ c_p2
    p0 = p2 ^ _permute_sum((1,), p2)

    full = np.zeros(ar4ja.FULL_N, dtype=np.uint8)
    full[0 : ar4ja.M] = u0
    full[ar4ja.M : 2 * ar4ja.M] = u1
    full[2 * ar4ja.M : 3 * ar4ja.M] = p0
    full[3 * ar4ja.M : 4 * ar4ja.M] = p1
    full[4 * ar4ja.M : 5 * ar4ja.M] = p2
    return full


def encode(payload_bits: Sequence[int] | np.ndarray) -> np.ndarray:
    """Encode a payload and return the transmitted 2048-bit punctured codeword."""

    return encode_full(payload_bits)[: ar4ja.TX_N].copy()


def encode_payload(
    payload_bits: Sequence[int] | np.ndarray,
    *,
    return_full: bool = False,
) -> np.ndarray:
    """Compatibility wrapper for callers that prefer an explicit return flag."""

    full = encode_full(payload_bits)
    if return_full:
        return full
    return full[: ar4ja.TX_N].copy()


@lru_cache(maxsize=1)
def generator_matrix_transmitted() -> np.ndarray:
    """Construct G with punctured columns omitted by encoding basis payloads."""

    rows = np.zeros((ar4ja.INFO_N, ar4ja.TX_N), dtype=np.uint8)
    for bit in range(ar4ja.INFO_N):
        payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
        payload[bit] = 1
        rows[bit, :] = encode(payload)
    return rows


@lru_cache(maxsize=1)
def generator_matrix_full() -> np.ndarray:
    """Construct full G = [I_MK W], including the final punctured M columns."""

    rows = np.zeros((ar4ja.INFO_N, ar4ja.FULL_N), dtype=np.uint8)
    for bit in range(ar4ja.INFO_N):
        payload = np.zeros(ar4ja.INFO_N, dtype=np.uint8)
        payload[bit] = 1
        rows[bit, :] = encode_full(payload)
    return rows

