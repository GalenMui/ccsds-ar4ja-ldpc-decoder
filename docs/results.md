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
PASS vector=0 success=1 iter=0 sat=0 cycles=480
PASS vector=1 success=1 iter=1 sat=0 cycles=4320
PASS vector=2 success=1 iter=1 sat=0 cycles=4320
PASS vector=3 success=1 iter=1 sat=0 cycles=4320
PASS vector=4 success=1 iter=1 sat=0 cycles=4320
PASS vector=5 success=1 iter=1 sat=0 cycles=4320
PASS vector=6 success=1 iter=1 sat=0 cycles=4320
PASS vector=7 success=1 iter=2 sat=2131 cycles=8160
PASS vector=8 success=1 iter=3 sat=8078 cycles=12000
PASS vector=9 success=1 iter=3 sat=8094 cycles=12000
PASS vector=10 success=0 iter=8 sat=0 cycles=31200
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
LANES=1:  PASS 11 decoder vectors, max-iteration failure cycles=249376
LANES=16: PASS 11 decoder vectors, max-iteration failure cycles=15616
```

## Cycle Summary

| Case | LANES=1 | LANES=8 default | LANES=16 |
| --- | ---: | ---: | ---: |
| Initial all-zero pass | 3,616 | 480 | 256 |
| One iteration | 34,336 | 4,320 | 2,176 |
| Two iterations | 65,056 | 8,160 | 4,096 |
| Three iterations | 95,776 | 12,000 | 6,016 |
| Eight-iteration failure | 249,376 | 31,200 | 15,616 |

At a hypothetical 100 MHz clock, the eight-iteration failure case is about
0.312 ms for the default `LANES=8` build. This is a simulation-derived cycle
count, not a timing result.

## Synthesis Status

Vivado was not installed in this environment, so no vendor utilization, RAM
inference, or timing reports were produced.

The PYNQ-Z2 board-level Vivado flow is prepared under `boards/pynq_z2/`, but
was not run here because Vivado is unavailable.

The guarded Make targets were exercised with a sample part and stopped with the
expected tool-unavailable error:

```text
make synth FPGA_PART=xc7a35tcsg324-1      -> Vivado not found
make impl FPGA_PART=xc7a35tcsg324-1       -> Vivado not found
make package-ip FPGA_PART=xc7a35tcsg324-1 -> Vivado not found
make synth FPGA_PART=xc7z020clg400-1      -> Vivado not found
```

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
- PYNQ-Z2 smoke test and benchmark on physical hardware.
- Long BER/FER sweeps.
