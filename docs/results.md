# Results

## Baseline Before Refactor

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

An attempted parallel baseline run raced two generated-package writers and
produced a bogus Icarus syntax failure. The sequential run above is the valid
baseline.

## Current RTL Simulation

Decoder core:

```text
PASS vector=0 success=1 iter=0 sat=0 cycles=3616
PASS vector=1 success=1 iter=1 sat=0 cycles=34336
PASS vector=2 success=1 iter=1 sat=0 cycles=34336
PASS vector=3 success=1 iter=1 sat=0 cycles=34336
PASS vector=4 success=1 iter=1 sat=0 cycles=34336
PASS vector=5 success=1 iter=1 sat=0 cycles=34336
PASS vector=6 success=1 iter=1 sat=0 cycles=34336
PASS vector=7 success=1 iter=2 sat=2131 cycles=65056
PASS vector=8 success=1 iter=3 sat=8078 cycles=95776
PASS vector=9 success=1 iter=3 sat=8094 cycles=95776
PASS vector=10 success=0 iter=8 sat=0 cycles=249376
```

AXI wrapper:

```text
PASS axis vector=0
PASS axis vector=5
PASS axis vector=10
PASS axis vector=1
PASS early_tlast malformed frame
PASS missing_tlast malformed frame
PASS axis vector=0 after malformed frame
```

## Cycle Summary

| Case | Cycles |
| --- | ---: |
| Initial all-zero pass | 3,616 |
| One iteration | 34,336 |
| Two iterations | 65,056 |
| Three iterations | 95,776 |
| Eight-iteration failure | 249,376 |

At a hypothetical 100 MHz clock, the eight-iteration failure case is about
2.49 ms. This is a simulation-derived cycle count, not a timing result.

## Synthesis Status

Vivado was not installed in this environment, so no vendor utilization, RAM
inference, or timing reports were produced.

Yosys is installed, but the local build fails while parsing the generated
SystemVerilog package:

```text
rtl/ar4ja_1024_pkg.sv:3: ERROR: syntax error, unexpected TOK_ID, expecting '='
```

No LUT, FF, BRAM, DSP, Fmax, slack, or power numbers are claimed yet.

## BER/FER Smoke

The regression still runs the deterministic one-frame BER/FER smoke. It is a
script health check only, not a communication-performance result.

## Missing Hardware Results

- Vivado out-of-context synthesis.
- RAM inference inspection.
- Timing summary at 100 MHz.
- Post-synthesis or post-route simulation.
- Board DMA test.
- Long BER/FER sweeps.
