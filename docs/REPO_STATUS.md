# Repository Status

Last updated: July 15, 2026.

> Note: sections dated "July 5, 2026" below predate the local Vivado install.
> Vivado 2025.2 was installed on July 7 and a partial out-of-context synthesis
> was attempted; see **Vivado Status (July 7, 2026)** at the end of this file
> and `docs/SYNTHESIS.md` for the authoritative synthesis state.

Current superseding status: the complete 100 MHz PYNQ-Z2 overlay closes timing,
programs successfully, and has passed one deterministic zero-noise frame through
physical AXI DMA. Older issue lists below are retained as development history;
`docs/PYNQ_Z2_BRINGUP.md` is authoritative for the board result.

## Completed And Verified Locally

- Fixed CCSDS AR4JA rate-1/2, k=1024 graph generation.
- Python systematic encoder and fixed-point layered normalized min-sum model.
- Generated graph package `rtl/ar4ja_1024_pkg.sv`.
- Generated supported-lane schedule package `rtl/ldpc_schedule_pkg.sv`.
- Authoritative decoder core `rtl/ldpc_decoder_top.sv`.
- Authoritative FPGA-facing top `rtl/ldpc_axis_decoder_ip.sv`.
- 32-bit AXI4-Stream wrapper with explicit `TKEEP` and deterministic
  malformed-frame handling.
- Board-independent host packing/parsing utility.
- PYNQ-Z2 Vivado block-design Tcl flow.
- PYNQ-Z2 Python driver, smoke test, benchmark, and overlay packager.
- Deterministic decoder and board bring-up vectors.
- `make generate`.
- `make lint`.
- `make test`, including `LANES=1`, `LANES=8`, and `LANES=16` core RTL sims.
- Open-source GitHub Actions workflow for generation, lint, and regression.

## Completed And Verified On Physical Hardware

- TUL PYNQ-Z2 / `xc7z020clg400-1` overlay programming at the implemented
  100 MHz clock.
- `axi_dma_0` discovery and MM2S/S2MM initialization.
- 2048-byte MM2S and 160-byte S2MM transfers, both completing with DMASR
  `0x00001002` (idle and IOC interrupt).
- Minimal zero-noise frame decode with status `success=1`, `syndrome=1`,
  `failure=0`, `iterations=0`, `cycles=2625`, and `saturation=0`.
- All 1024 decoded bits matched the golden output SHA-256
  `5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef`.

This physical coverage is one deterministic all-zero vector. Additional RTL
simulation coverage is not claimed as additional board coverage.

## Architecture Found

The active architecture is a banked, grouped, layered normalized min-sum LDPC
decoder. It uses internal banked posterior RAM arrays, lane-banked packed
check-message RAM arrays, a hard-decision register vector, generated graph
functions, and generated schedule metadata.

The wrapper preserves the current 512-word input and 40-word output ABI and
now exposes full-beat `TKEEP` on both streams for AXI DMA integration.

## Major Issues Found

- The Makefile did not expose the requested generation, lint, synthesis,
  implementation, or package-IP targets.
- `make lint` was a placeholder.
- Documentation claimed `LANES=1` and `LANES=16` were regression-tested, but
  the regression script only ran the default `LANES=8` RTL simulation.
- Vivado scripts existed but synthesis and implementation were not separated.
- IP packaging used an inline source list instead of the deterministic manifest.
- Standalone memory templates were not labeled as reference code.
- No CI workflow existed for the open-source flow.
- Vivado and Verilator are unavailable in the local environment.
- Yosys 0.9 cannot parse the generated SystemVerilog package.
- The selected PYNQ-Z2 board flow had not yet been added.

## Changes Made In This Pass

- Added `scripts/run_lint.py`.
- Updated `Makefile` with `generate`, `lint`, `test`, `synth`, `impl`,
  `package-ip`, and `clean` targets.
- Extended `scripts/run_regression.py` to run RTL core simulations for
  `LANES=1`, `LANES=8`, and `LANES=16`.
- Added `fpga/impl_ooc.tcl`.
- Updated `fpga/synth_ooc.tcl` to run synthesis-only and write synthesis
  reports under `results/vivado_ooc/synth/`.
- Updated `fpga/package_ip.tcl` to read `rtl/ldpc_sources.f` and set stable IP
  metadata.
- Added `.github/workflows/open_source.yml`.
- Labeled `rtl/posterior_memory.sv` and `rtl/message_memory.sv` as reference
  templates.
- Made simulation-only assertion blocks Icarus-friendly.
- Added uppercase documentation entry points requested by the board-readiness
  brief.
- Added explicit AXI4-Stream `TKEEP` ports and `tkeep_error` handling.
- Added PYNQ-Z2 Vivado project/block-design flow under `boards/pynq_z2/`.
- Added overlay packaging with consistent `.bit`/`.hwh` basenames.
- Added PYNQ-Z2 Python driver, smoke test, benchmark, and local packing tests.
- Added board-readiness audit and PYNQ-Z2 bring-up documentation.

## Current Verification Results

- `make test`: pass, including Python unit tests and `LANES=1/8/16` core RTL
  simulations.
- `make lint`: pass for the FPGA-facing top, assertion-enabled top, and
  syndrome checker.
- AXI wrapper simulation: pass with valid frames, `TKEEP`, malformed framing,
  backpressure, and recovery cases.
- Complete PYNQ-Z2 implementation: fully routed at 100 MHz with setup WNS
  `+0.091 ns`, setup TNS `0.000 ns`, hold WHS `+0.018 ns`, and hold THS
  `0.000 ns`; no DRC errors or critical warnings.
- Physical PYNQ-Z2 minimal-vector smoke test: pass as recorded above.

Future physical validation includes consecutive frames, randomized/noisy
vectors, reset/error recovery, throughput benchmarking, and BER/FER sweeps.

## Vivado And Board Status (July 15, 2026)

This supersedes the earlier "did not complete / ~94k flip-flops" notes.

- Vivado 2025.2 installed; `make vivado-smoke` passes for `xc7z020clg400-1`.
- The `LANES=8` `ldpc_axis_decoder_ip` **completes out-of-context synthesis and
  place & route** on the target part, with **0 critical warnings**.
- **Setup timing closes at 100 MHz** (post-route WNS **+0.009 ns**, TNS 0.000 ns,
  0 failing endpoints; hold WHS **+0.128 ns**, TNS 0.000 ns).
- **Utilization:** Slice LUTs 7,848 (14.75 %), Slice Registers 4,626 (4.35 %),
  Block RAM 12 tiles (8×RAMB36 + 8×RAMB18, 8.57 %), DSP 0.
- The posterior and check-message memories now **infer block RAM** (the former
  ~94k flip-flop inference is fixed by per-lane single-port banking; the flat
  `hard_full` register was removed as a redundant posterior-sign shadow). Setup
  closure required a pipelined min1/min2 reduction and lane-local saturation
  counting. Full analysis: `docs/SYNTHESIS_MEMORY_ANALYSIS.md`.
- Evidence (OOC, tool-reported, not gitted — regenerate via
  `experiments/synthesis/impl_ip_timing.tcl`):
  `experiments/synthesis/results/impl_ip_strong/{timing_postroute.rpt,util.rpt}`.
- The complete PS/AXI-DMA overlay bitstream and HWH were generated and deployed.
- Physical programming and the minimal end-to-end DMA known-answer test pass.
- **Not done:** measured hardware throughput/BER, noisy/randomized board vectors,
  consecutive-frame stress, or ILA-based signal capture.
- Toolchain note: the AXI wrapper, core decoder (`LANES=1/8/16`), and syndrome
  sims all build and pass under the installed Icarus 14. (An enum ternary at
  `rtl/ldpc_axis_wrapper.sv:285` that previously failed to elaborate under
  Icarus 14 was fixed with an explicit `wrapper_state_t'(...)` cast.) The
  `LANES=8` core sim takes ~90 s and therefore exceeds the 60 s cap in
  `scripts/run_regression.py` (functional pass, timeout-flagged).
