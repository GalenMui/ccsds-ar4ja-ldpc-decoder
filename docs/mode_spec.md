# Fixed CCSDS AR4JA Mode Specification

## Source

Primary source: CCSDS 131.0-B-5, TM Synchronization and Channel Coding,
September 2023, https://ccsds.org/Pubs/131x0b5.pdf.

Pages used:

- Printed page 1-7: bit numbering convention.
- Printed pages 7-7 through 7-11: LDPC AR4JA matrix, permutation formula,
  phi tables, puncturing, and generator-matrix construction.

## Supported Mode

This repository implements only the fixed rate-1/2 AR4JA LDPC mode with:

- K = 2.
- M = 512.
- Information length k = M*K = 1024 bits.
- Full unpunctured codeword length = M*(K+3) = 2560 bits.
- Transmitted codeword length n = M*(K+2) = 2048 bits.
- Punctured symbols = M = 512 bits.
- Parity-check row count = 3*M = 1536 rows.

## Bit Ordering

Python index 0 and RTL bit 0 represent CCSDS Bit 0. Bit 0 is the first
transmitted bit. When a CCSDS binary value is interpreted numerically, Bit 0 is
the MSB. Text vector files write bit index 0 first; simulator memory files are
hex-encoded so that bit index 0 maps to RTL bit 0.

## Rate-1/2 H Matrix

The full unpunctured parity-check matrix has 3 row blocks and 5 column blocks,
each block M by M:

```text
H_1/2 =
[ 0,          0,             I,          0,             I + Pi_1           ]
[ I,          I,             0,          I,             Pi_2 + Pi_3 + Pi_4 ]
[ I,          Pi_5 + Pi_6,   0,          Pi_7 + Pi_8,   I                 ]
```

All additions are over GF(2), so duplicate one entries cancel.

The permutation matrix Pi_k has one entry in row i and column pi_k(i):

```text
pi_k(i) = (M/4) * ((theta_k + floor(4*i/M)) mod 4)
        + (phi_k(floor(4*i/M), M) + i) mod (M/4)
```

The tuple order for phi table values is M = {128, 256, 512, 1024, 2048, 4096,
8192}. This fixed mode uses the third value in each tuple, because M = 512.

## Puncturing

The last M full-codeword columns, full indices 2048..2559, are punctured and
are not transmitted. The transmitted codeword contains full indices 0..2047.

The Python and RTL transmitted-codeword syndrome convention is explicit:
`solve_from_third_check_block`. Because the third H row block has I in the last
punctured column block, each missing bit 2048+i is reconstructed as the XOR of
the transmitted bits in check row 1024+i. This forces the third check block to
zero without assuming the punctured bits were transmitted as zeros. The full
1536-bit syndrome is then evaluated on that reconstructed full word.

## Encoder

The encoder is systematic. The full codeword order is:

```text
[u0, u1, p0, p1, p2]
```

where u0 and u1 are the two 512-bit information blocks and p2 is the punctured
512-bit parity block.

The standard construction partitions H as:

```text
P = last 3M columns of H
Q = first MK columns of H
W = (P^-1 Q)^T over GF(2)
G = [I_MK W]
```

The implementation solves the equivalent fixed-mode GF(2) equations from this
P/Q partition and then transmits `[u0, u1, p0, p1]`.

## LLR Convention

LLRs use positive values for bit 0 and negative values for bit 1. Quantized LLRs
are signed two's-complement integers, default width 8 bits, saturated to
[-128, 127]. An LLR exactly equal to zero is a stable tie and maps to hard
decision 0.

The BPSK model maps bit 0 to +1 and bit 1 to -1, matching the LLR sign
convention.

## Implemented Scope

Implemented in Phases 1 through 3:

- CCSDS AR4JA rate-1/2, k=1024 matrix construction.
- Sparse row and column adjacency.
- Full and transmitted-codeword syndrome calculations.
- Systematic Python encoder and deterministic vectors.
- Fixed-point LLR quantization and BPSK/AWGN helpers.
- Simple floating-point and fixed-point normalized min-sum model scaffolds.
- Generated SystemVerilog syndrome-checker constants.
- Synthesizable RTL syndrome checker and Icarus simulation testbench.

Intentionally not implemented yet:

- Full iterative RTL decoder core.
- AXI-Stream wrapper.
- FPGA board bringup.
- Other CCSDS LDPC rates, lengths, or modem functions.

