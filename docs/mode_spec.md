# Fixed CCSDS AR4JA Mode Specification

## Standards Source

Primary source: CCSDS 131.0-B-5, *TM Synchronization and Channel Coding*,
September 2023:

```text
https://ccsds.org/Pubs/131x0b5.pdf
```

Relevant printed pages:

- Page 1-7: bit numbering convention.
- Pages 7-7 through 7-8: AR4JA LDPC family, M table, rate-1/2 H matrix, and
  permutation formula.
- Pages 7-9 through 7-10: theta/phi tables 7-3 and 7-4.
- Page 7-11: K values, generator matrix dimensions, codeword length table, and
  last-M-column puncturing.

The implementation is traceable through:

- `models/ar4ja_matrix.py`: constants, theta/phi tables, permutation formula,
  and H construction.
- `scripts/gen_syndrome_rom.py`: generated RTL graph package from the Python H.
- `rtl/ar4ja_1024_pkg.sv`: generated constants used by RTL.

## Supported Mode

Only this fixed mode is implemented:

| Quantity | Value |
| --- | ---: |
| Code family | AR4JA LDPC |
| Rate | 1/2 |
| CCSDS K | 2 |
| M | 512 |
| Information bits, `MK` | 1024 |
| Full internal bits, `M(K+3)` | 2560 |
| Transmitted bits, `M(K+2)` | 2048 |
| Punctured bits | 512 |
| Parity-check rows, `3M` | 1536 |

`models/ar4ja_matrix.validate_dimensions()` checks these constants.

## H Matrix

The unpunctured rate-1/2 parity-check matrix has 3 row blocks and 5 column
blocks, each M by M:

```text
H_1/2 =
[ 0,          0,             I,          0,             I + Pi_1           ]
[ I,          I,             0,          I,             Pi_2 + Pi_3 + Pi_4 ]
[ I,          Pi_5 + Pi_6,   0,          Pi_7 + Pi_8,   I                 ]
```

All additions are over GF(2), so duplicate one entries cancel.

This is not a placeholder matrix. The sparse rows are built from the CCSDS
block formula and the embedded CCSDS theta/phi tables. For this fixed mode the
generated graph has 7680 edges, row weight histogram `3:512, 6:1024`, and
column weight histogram `1:512, 2:512, 3:1024, 6:512`.

## Phi Table Indexing

CCSDS tables 7-3 and 7-4 list phi values as 7-tuples ordered by:

```text
M = {128, 256, 512, 1024, 2048, 4096, 8192}
```

This repository uses the third tuple element because M = 512.

## Permutation Formula

For permutation matrix `Pi_k`, row `i` has a one at column `pi_k(i)`:

```text
pi_k(i) = (M/4) * ((theta_k + floor(4*i/M)) mod 4)
        + (phi_k(floor(4*i/M), M) + i) mod (M/4)
```

Python index 0 corresponds to the CCSDS row/column index 0 used in this
formula.

## Puncturing Convention

The full internal codeword order is:

```text
[u0, u1, p0, p1, p2]
```

Each block is 512 bits. The transmitted codeword is:

```text
[u0, u1, p0, p1]
```

Full internal columns `2048..2559`, the `p2` block, are punctured and are not
transmitted.

For syndrome checking from a transmitted 2048-bit word, the repository uses the
explicit policy `solve_from_third_check_block`: for each `i`, reconstruct
punctured bit `2048+i` from row `1024+i`, whose final H block is `I`. This
forces the third check block to zero without pretending the punctured symbols
were transmitted as zeros. The full 1536-row syndrome is then evaluated.

For iterative decoding, punctured variables are included in the 2560-variable
graph with neutral channel LLR = 0.

## Encoder Convention

The encoder is systematic. Payload bits occupy transmitted indices `0..1023`.
Parity blocks `p0` and `p1` occupy transmitted indices `1024..2047`.

The implementation follows the CCSDS generator construction specialized to the
fixed rate-1/2 matrix:

```text
P = last 3M columns of H
Q = first MK columns of H
W = (P^-1 Q)^T over GF(2)
G = [I_MK W]
```

The last M columns of `G`, corresponding to `p2`, are punctured.

## LLR And Fixed-Point Convention

LLR sign:

- Positive LLR means hard decision bit 0.
- Negative LLR means hard decision bit 1.
- Exactly zero is a stable tie and maps to bit 0.

BPSK mapping:

- Bit 0 maps to `+1`.
- Bit 1 maps to `-1`.

Default quantization:

- LLR width: 8 signed bits.
- Message width: 8 signed bits.
- Signed saturation range: `[-128, 127]`.
- Normalized min-sum scale: `3/4`.

Python and RTL both saturate check-to-variable messages, posterior LLRs, and
variable-to-check messages to the signed message range. The RTL decoder
testbench compares saturation counts against Python-generated vectors.

## Bit Ordering

Python index 0 and RTL bit 0 represent CCSDS Bit 0. Bit 0 is the first
transmitted bit. When a CCSDS binary field is interpreted numerically, Bit 0 is
the MSB.

Text vector files write bit index 0 first. Hex memory files pack bit or LLR
index 0 into the least significant bits of the memory word because that is how
the RTL vectors are indexed. This packing convention is tested by the syndrome
and decoder testbenches.
