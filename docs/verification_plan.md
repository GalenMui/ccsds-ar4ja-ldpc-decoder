# Verification

Run the full repository regression from the root:

```sh
python3 scripts/run_regression.py
```

## Golden Model

`models/ldpc_decoder_fixed.py` is the RTL golden model for decoder behavior.
It matches the implemented layered fixed-point schedule:

- transmitted LLR ordering;
- punctured variables initialized to zero;
- ascending row order;
- immediate posterior update after each row;
- sign convention and zero hard-decision tie;
- deterministic equal-minimum tie handling;
- truncating `floor(selected_min * 3 / 4)`;
- message and posterior saturation;
- initial syndrome and early termination;
- iteration and saturation counts.

`scripts/gen_decoder_vectors.py` regenerates the checked-in RTL vectors from
that model.

## Python Tests

Covered by `scripts/run_phase1_phase3_tests.py`:

- fixed-mode dimensions;
- permutation validity;
- sparse graph shape;
- no duplicate variable addresses inside a check row;
- puncturing model;
- systematic encoder validity;
- hard-decision sign and zero tie;
- LLR saturation;
- noiseless transmitted hard decisions;
- one-iteration punctured-variable recovery for a noiseless nonzero word;
- deterministic low-confidence max-iteration failure;
- deterministic vector generation.

If `pytest` is unavailable, the runner uses a local assert-based fallback for
the repository's plain pytest-style tests.

## RTL Tests

Syndrome checker:

```sh
python3 scripts/gen_vectors.py
python3 scripts/gen_syndrome_rom.py
iverilog -g2012 -o sim/build/syndrome_checker.vvp \
  rtl/ar4ja_1024_pkg.sv rtl/syndrome_checker.sv sim/tb_syndrome_checker.sv
vvp sim/build/syndrome_checker.vvp
```

Decoder core:

- Loads 2048 LLRs through the sequential core write port.
- Checks decoded bits, success/fail, syndrome, iterations, saturation, and
  cycle bounds for 11 deterministic vectors.
- Covers all-zero initial syndrome pass, noiseless nonzero valid words,
  corrected noisy frames, positive/negative saturation cases from generated
  vectors, and a max-iteration failure.

AXI wrapper:

- Preserves input lane ordering.
- Handles input valid gaps.
- Handles output backpressure.
- Checks output stability while stalled.
- Checks exact output word format and payload bit ordering.
- Checks early `TLAST`.
- Checks missing `TLAST` error output and drain recovery.
- Sends multiple valid frames sequentially.
- Sends a malformed frame followed by a valid frame.

## Current Regression Result

Latest local run in this environment:

- Python fallback tests: pass.
- Syndrome RTL simulation: pass.
- Decoder core RTL simulation: pass, 11 vectors.
- AXI wrapper RTL simulation: pass.
- BER/FER smoke script: pass.
- Plot generation: skipped when local `matplotlib` import is unusable.
- Synthesis report parser: pass, reports missing reports honestly.

## Synthesis Checks

Available tools:

- Icarus Verilog and `vvp`: available and used.
- Yosys: available, but this build fails on the generated SystemVerilog package
  syntax before elaboration.
- Vivado: not available in this environment.
- Verilator: not available in this environment.

Do not claim timing closure from these results. Vivado OOC synthesis remains
the next required hardware validation step.

## Remaining Gaps

- Vendor synthesis/timing/resource reports.
- RAM inference inspection in Vivado.
- More noisy random vectors and BER/FER sweeps.
- Automated cycle-by-cycle internal row trace comparison.
- Reset-during-decode/output tests beyond the current reset initialization
  coverage.
- Hardware DMA integration on a selected board.
