# Results

## Baseline Before Parallel Refactor

The sequential baseline run before edits passed:

```text
PASS phase1_phase3
PASS decoder_vectors
PASS decoder_check
PASS decoder_build
PASS decoder_sim
PASS axis_build
PASS axis_sim
PASS ber_fer_smoke
PASS summarize_results
SKIP plot_ber_fer
PASS parse_synthesis_reports
```

The sequential run above is the valid pre-parallel baseline.

## Current RTL Simulation

Decoder core, `LANES=8` default:

```text
PASS vector=0 success=1 iter=0 sat=0 cycles=2625
PASS vector=1 success=1 iter=1 sat=0 cycles=8578
PASS vector=2 success=1 iter=1 sat=0 cycles=8578
PASS vector=3 success=1 iter=1 sat=0 cycles=8578
PASS vector=4 success=1 iter=1 sat=0 cycles=8578
PASS vector=5 success=1 iter=1 sat=0 cycles=8578
PASS vector=6 success=1 iter=1 sat=0 cycles=8578
PASS vector=7 success=1 iter=2 sat=2131 cycles=14531
PASS vector=8 success=1 iter=3 sat=8078 cycles=20484
PASS vector=9 success=1 iter=3 sat=8094 cycles=20484
PASS vector=10 success=0 iter=8 sat=0 cycles=50249
```

AXI wrapper:

```text
PASS axis vector=0
PASS axis vector=5
PASS axis vector=10
PASS axis vector=1
PASS early_tlast malformed frame
PASS early_tlast_late malformed frame
PASS axis vector=0 after late early_tlast
PASS bad_tkeep malformed frame
PASS missing_tlast malformed frame
PASS axis vector=0 after malformed frame and reset
```

Additional supported-lane core simulations now run in `make test`:

```text
LANES=1:  PASS 11 decoder vectors, max-iteration failure cycles=401929
LANES=16: PASS 11 decoder vectors, max-iteration failure cycles=25129
```

## Cycle Summary

| Case | LANES=1 | LANES=8 default | LANES=16 |
| --- | ---: | ---: | ---: |
| Initial all-zero pass | 20,993 | 2,625 | 1,313 |
| One iteration | 68,610 | 8,578 | 4,290 |
| Two iterations | 116,227 | 14,531 | 7,267 |
| Three iterations | 163,844 | 20,484 | 10,244 |
| Eight-iteration failure | 401,929 | 50,249 | 25,129 |

At a hypothetical 100 MHz clock, the eight-iteration failure case is about
0.502 ms for the default `LANES=8` build. This is a simulation-derived cycle
count, not a physical latency measurement. The physical zero-vector run also
reported 2,625 decoder cycles, but only that single vector has been compared
between simulation and hardware.

## PYNQ-Z2 Implementation Status

Vivado 2025.2 produced the complete `xc7z020clg400-1` PS/AXI-DMA overlay. The
100 MHz implementation closed timing with setup WNS `+0.091 ns`, setup TNS
`0.000 ns`, hold WHS `+0.018 ns`, and hold THS `0.000 ns`. Detailed evidence is
listed in `docs/PYNQ_Z2_BRINGUP.md`.

These are vendor implementation results. They are distinct from RTL simulation
cycle counts and from the physical-board observation below.

## BER/FER Smoke

The regression still runs the deterministic one-frame BER/FER smoke. It is a
script health check only, not a communication-performance result.

## Physical PYNQ-Z2 Hardware Result

The July 15, 2026 root-Jupyter-terminal run programmed the 100 MHz overlay,
discovered `axi_dma_0`, and passed one end-to-end deterministic DMA decode:

```text
input:  1024 zero payload bits -> 2048 LLRs of +32 -> 512 x 0x20202020
MM2S:   2048 bytes, DMASR 0x00001002 (idle, ioc_irq)
S2MM:    160 bytes, DMASR 0x00001002 (idle, ioc_irq)
status: success=1 syndrome=1 failure=0 iterations=0 cycles=2625 saturation=0
output: 40 words, decoded SHA-256 match
hash:   5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef
```

This confirms physical programming, DMA movement in both directions, framing
for the minimal valid frame, and exact decoded data for one zero-noise vector.

## Remaining Validation Gaps

- Randomized and noisy physical-board vectors.
- Consecutive-frame and reset-recovery hardware stress.
- Hardware BER/FER sweeps and throughput measurements.
- Post-synthesis or post-route simulation.
- Other code rates, block sizes, and physical lane configurations.
