# ccsds-ar4ja-ldpc-decoder

Fixed-mode SystemVerilog/Python experiments for the CCSDS AR4JA LDPC code used
by CCSDS 131.0-B-5, section 7.4.

This repository implements one mode only:

- Code family: CCSDS AR4JA LDPC.
- Rate: 1/2.
- CCSDS K: 2.
- Submatrix size M: 512.
- Information bits: 1024.
- Transmitted codeword bits: 2048.
- Full internal codeword bits: 2560.
- Punctured bits: 512.
- Parity-check rows: 1536.

It is intended as an inspectable decoder design and verification sandbox, not
as a complete spacecraft modem.

## Scope

Implemented:

- CCSDS AR4JA rate-1/2, k=1024 matrix construction from the CCSDS phi/theta
  tables.
- Explicit puncturing policy for the final M internal symbols.
- Systematic Python encoder.
- Floating-point and fixed-point normalized min-sum Python decoder models.
- Deterministic vector generation.
- Generated SystemVerilog graph package.
- RTL syndrome checker.
- Slow, deterministic RTL decoder core compared against the fixed-point Python
  model at frame-output level.
- AXI-style block wrapper and simulation testbench.
- BER/FER smoke scripts and result summarization.

Not in scope:

- Other CCSDS LDPC rates or block lengths.
- CCSDS transfer-frame parsing, ASM/CSM handling, randomization, modulation, or
  synchronization.
- FPGA board bringup.
- ASIC implementation flow.
- Claimed timing closure, resource use, or production performance.

## Repository Structure

```text
docs/        Mode, architecture, verification, results, and review notes
models/      Python matrix, encoder, channel, quantization, and decoder models
rtl/         SystemVerilog package, decoder, syndrome checker, and wrapper
sim/         Icarus testbenches
scripts/     Generation, regression, smoke-test, plotting, and debug utilities
tests/       Python unit tests
vectors/     Deterministic checked-in regression vectors
results/     Local generated reports/plots; ignored except .gitkeep files
```

The large generated RTL graph package `rtl/ar4ja_1024_pkg.sv` is intentional.
Regenerate it with `python3 scripts/gen_syndrome_rom.py`.

## Dependencies

Python:

```sh
python3 -m pip install -r requirements.txt
```

Simulator:

- `iverilog`
- `vvp`

`pytest` is listed in `requirements.txt`. If it is not importable, the
Phase 1/3 runner uses a small local fallback for the plain pytest-style tests.

## One Complete Run

From the repository root:

```sh
python3 scripts/run_regression.py
```

The command prints each subcommand and a compact PASS/FAIL/SKIP summary. It
creates `sim/build/` as needed.

Useful Make targets:

```sh
make help
make test
make regression
make clean
```

## Generate Vectors

Syndrome checker vectors:

```sh
python3 scripts/gen_vectors.py
```

Decoder vectors:

```sh
python3 scripts/gen_decoder_vectors.py
```

RTL graph package:

```sh
python3 scripts/gen_syndrome_rom.py
```

## Run Simulations Directly

Syndrome checker:

```sh
python3 scripts/gen_vectors.py
python3 scripts/gen_syndrome_rom.py
iverilog -g2012 -o sim/build/syndrome_checker.vvp rtl/ar4ja_1024_pkg.sv rtl/syndrome_checker.sv sim/tb_syndrome_checker.sv
vvp sim/build/syndrome_checker.vvp
```

Decoder core:

```sh
python3 scripts/gen_decoder_vectors.py
iverilog -g2012 -o sim/build/ldpc_decoder_top.vvp rtl/ar4ja_1024_pkg.sv rtl/ldpc_decoder_top.sv sim/tb_ldpc_decoder_top.sv
vvp sim/build/ldpc_decoder_top.vvp
```

AXI wrapper:

```sh
iverilog -g2012 -o sim/build/ldpc_axis_wrapper.vvp rtl/ar4ja_1024_pkg.sv rtl/ldpc_decoder_top.sv rtl/ldpc_axis_wrapper.sv sim/tb_ldpc_axis_wrapper.sv
vvp sim/build/ldpc_axis_wrapper.vvp
```

## BER/FER Smoke And Plots

Generate a small deterministic smoke CSV:

```sh
python3 scripts/run_ber_fer.py --frames 1 --ebn0 2.0
python3 scripts/summarize_results.py
```

Generate plots when the local `matplotlib`/`numpy` installation is usable:

```sh
python3 scripts/plot_ber_fer.py
```

Plots and CSVs under `results/` are generated artifacts. The deterministic
regression vectors under `vectors/` are intentionally kept.

## Debug Aids

Matrix dimensions and graph statistics:

```sh
python3 scripts/print_matrix_stats.py
```

List or inspect decoder vectors:

```sh
python3 scripts/inspect_decoder_vector.py --list
python3 scripts/inspect_decoder_vector.py 10
```

## Current Status

The core model, encoder, generated graph, syndrome checker, RTL decoder core,
and AXI wrapper simulations pass in the current environment. The default
regression skips plot generation only when `matplotlib.pyplot` cannot be
imported cleanly.

No synthesis flow exists yet. No resource, timing, board, or hardware-readiness
claims are made.

Start deeper review with:

- `docs/mode_spec.md`
- `docs/architecture.md`
- `docs/verification_plan.md`
- `docs/results.md`
- `docs/deep_dive_guide.md`
- `docs/repo_status.md`
