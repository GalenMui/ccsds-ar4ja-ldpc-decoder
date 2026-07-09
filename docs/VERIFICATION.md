# Verification

The one-command open-source regression is:

```sh
make test
```

`make test` runs `scripts/run_regression.py`, which regenerates deterministic
artifacts, runs Python model tests, builds and simulates RTL, runs a BER/FER
smoke check, and parses available synthesis reports.

## Golden Model

`models/ldpc_decoder_fixed.py` is the authoritative decoder model. It matches
the RTL for:

- transmitted LLR ordering;
- punctured-variable initialization;
- grouped layered schedule;
- 3/4 normalized min-sum update;
- equal-minimum tie behavior;
- signed 8-bit clipping;
- saturation-count semantics;
- initial syndrome and early termination;
- max-iteration failure behavior.

## Generated Vectors

```sh
make generate
```

regenerates:

- syndrome vectors in `vectors/syndrome/`;
- `rtl/ar4ja_1024_pkg.sv`;
- `rtl/ldpc_schedule_pkg.sv`;
- schedule reports in `vectors/schedule/`;
- decoder vectors in `vectors/decoder/`.

## Python Tests

The Python tests cover fixed-mode dimensions, permutation validity, graph shape,
puncturing, systematic encoding, fixed-point saturation, hard decisions,
decoder success/failure cases, deterministic vector generation, and schedule
invariants.

## RTL Tests

The regression builds and runs:

- `sim/tb_syndrome_checker.sv`;
- `sim/tb_ldpc_decoder_top.sv` with `LANES=8`;
- `sim/tb_ldpc_decoder_top.sv` with `LANES=1`;
- `sim/tb_ldpc_decoder_top.sv` with `LANES=16`;
- `sim/tb_ldpc_axis_wrapper.sv` with the default `LANES=8`.

Decoder vectors include noiseless frames, corrected error-containing frames,
saturation cases, early termination, and one deterministic max-iteration
failure. The AXI wrapper test covers input valid gaps, output backpressure,
stable stalled output, consecutive frames, early `TLAST`, missing `TLAST`, and a
valid frame after malformed-frame recovery. It also checks full-beat `TKEEP`,
bad input `TKEEP` rejection, late early-`TLAST` counter recovery, output
`TKEEP` stability while stalled, and reset after an incomplete input frame.

## PYNQ-Z2 Host Software Tests

`tests/test_pynq_z2_software.py` validates the board-side pure Python helpers
without importing PYNQ:

- signed int8 LLR range checks;
- little-lane packing into 32-bit DMA words;
- decoded-bit packing;
- response status parsing;
- response magic validation.

## Lint And Elaboration

```sh
make lint
```

uses Icarus Verilog because Verilator is not installed in the current
environment. It warning-checks the FPGA-facing top and standalone syndrome
checker, and separately elaborates the FPGA-facing top with
`LDPC_ENABLE_ASSERTS`.

Narrow Icarus suppressions are used for generated package timescale warnings
and indexed-array sensitivity diagnostics:

```text
-Wno-timescale
-Wno-sensitivity-entire-array
```

## Current Local Results

Last verified July 9, 2026 on the installed oss-cad-suite toolchain
(Icarus 14) and Vivado 2025.2:

- Python unit tests (`pytest tests/`): **31 passed**.
- Syndrome-checker RTL sim (`tb_syndrome_checker`): pass, 5 vectors.
- Core decoder RTL sim, all 11 vectors:
  - `LANES=8`: pass (runtime ~90 s; exceeds the 60 s cap in
    `scripts/run_regression.py`, so the automated step is flagged as a timeout
    even though the simulation completes and passes).
  - `LANES=16`: pass (runtime ~1.5 min; worst-case 15,616 cycles).
  - `LANES=1`: generated schedule present; slow to simulate (worst-case
    ~249k cycles) and covered by the regression's 180 s step.
- AXI wrapper RTL sim (`tb_ldpc_axis_wrapper`, LANES=8): **pass** under the
  installed Icarus 14 (~30 s), covering valid frames, valid gaps, output
  backpressure, stable stalled output, consecutive frames, early `TLAST`,
  missing `TLAST`, bad input `TKEEP`, and a valid frame after malformed-frame
  reset recovery. (An earlier enum-ternary at `rtl/ldpc_axis_wrapper.sv:285`
  failed to elaborate under Icarus 14; it now uses an explicit
  `wrapper_state_t'(...)` cast around the whole expression.)
- `yosys -q -l results/reports/yosys_synth.log fpga/yosys_synth.ys`: fail on
  the generated SystemVerilog package in Yosys 0.9.
- Vivado 2025.2: installed; smoke passes; a `LANES=8` out-of-context synthesis
  was attempted but did not complete (see `docs/SYNTHESIS.md`). No vendor
  timing/utilization numbers exist.
- Verilator: installed (oss-cad-suite) but not currently wired into the lint
  flow, which uses Icarus.

The BER/FER data in `results/reports/ber_fer.csv` is a single 1-frame smoke run
at Eb/N0 = 2.0 dB, not a performance sweep; no BER/FER curve is claimed. The
optional plot step is skipped when the local matplotlib/numpy stack is unusable.
That skip does not affect decoder correctness.

## Remaining Verification Gaps

- Vendor synthesis and timing reports
- Post-synthesis or post-route simulation
- Reset-during-decode/output randomized tests
- Cycle-by-cycle internal trace comparison
- Long BER/FER sweeps
- Physical-board DMA validation
