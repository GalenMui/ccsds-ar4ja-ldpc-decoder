# Synthesis

The authoritative FPGA synthesis top is:

```text
ldpc_axis_decoder_ip
```

The deterministic RTL source manifest is:

```text
rtl/ldpc_sources.f
```

Generated files must be current before synthesis:

```sh
make generate
```

## Vivado Out-Of-Context Synthesis

Run with the exact FPGA part selected for the target board:

```sh
make synth FPGA_PART=<part>
```

Equivalent direct command:

```sh
vivado -mode batch -nojournal \
  -log results/vivado_ooc/synth/vivado.log \
  -source fpga/synth_ooc.tcl \
  -tclargs <part>
```

The script:

- resolves paths relative to the repository root;
- reads `rtl/ldpc_sources.f`;
- reads `fpga/constraints/ldpc_axis_decoder.xdc`;
- runs `synth_design -mode out_of_context`;
- writes reports under `results/vivado_ooc/synth/`;
- writes `ldpc_axis_decoder_ip.dcp`.

Expected synthesis reports:

```text
results/vivado_ooc/synth/utilization_synth.rpt
results/vivado_ooc/synth/timing_summary_synth.rpt
results/vivado_ooc/synth/ram_utilization.rpt
results/vivado_ooc/synth/hierarchy.rpt
results/vivado_ooc/synth/compile_order.rpt
results/vivado_ooc/synth/drc.rpt
```

## Vivado Out-Of-Context Implementation

Run after selecting a part:

```sh
make impl FPGA_PART=<part>
```

Equivalent direct command:

```sh
vivado -mode batch -nojournal \
  -log results/vivado_ooc/impl/vivado.log \
  -source fpga/impl_ooc.tcl \
  -tclargs <part>
```

The implementation script runs synthesis, opt, place, and route, then writes
reports under `results/vivado_ooc/impl/`.

## IP Packaging

Package the block-design IP with:

```sh
make package-ip FPGA_PART=<part>
```

Equivalent direct command:

```sh
vivado -mode batch -nojournal \
  -log results/ip_repo/package_ip.log \
  -source fpga/package_ip.tcl \
  -tclargs <part>
```

The package script uses `ldpc_axis_decoder_ip` as the IP boundary, reads the
same source manifest, and places output under:

```text
results/ip_repo/ldpc_axis_decoder_ip/
```

## PYNQ-Z2 Board Build

The board-level Vivado flow is source Tcl, not a checked-in `.xpr`:

```sh
make pynq-z2-project
make pynq-z2-synth
make pynq-z2-bitstream
make pynq-z2-package
```

It creates:

```text
results/pynq_z2/vivado/ccsds_ldpc_pynq_z2/
```

and instantiates:

- Zynq-7000 PS7.
- AXI DMA in simple mode with 32-bit streams and a 14-bit length field.
- PS GP0 to DMA AXI-Lite control.
- PS HP0 to DMA memory traffic.
- Processor System Reset.
- `ldpc_axis_decoder_ip` with explicit AXI4-Stream `TKEEP`.

The default target is `xc7z020clg400-1`, `PYNQ_Z2_CLK_MHZ=100.0`, and
`PYNQ_Z2_LANES=8`. The script searches for an installed PYNQ-Z2 board
definition and uses the board preset when available. The tested Linux-overlay
build uses the raw part fallback with explicit FCLK0, GP0, HP0, and address-map
configuration; PS DDR/MIO must already have been initialized by PYNQ Linux.

Board reports are written under:

```text
results/pynq_z2/reports/synth/
results/pynq_z2/reports/impl/
```

The overlay package target copies matching artifact names to:

```text
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.bit
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.hwh
```

## Clock Constraint

The board-independent OOC constraint is:

```text
fpga/constraints/ldpc_axis_decoder.xdc
```

It defines a 10 ns, 100 MHz clock on `aclk`. Board-level pin, clocking, reset,
DDR, DMA, and interrupt constraints must be added only after a board is
selected.

## Local Tool Status

In the current environment (as of the latest Vivado run logged under
`reports/vivado/`):

- Vivado 2025.2 **is** installed at `/tools/AMD/2025.2/Vivado`. The target-part
  smoke check passes:

```text
reports/vivado/smoke.log
  Vivado is working.  Version: 2025.2
  Target part available: xc7z020clg400-1
```

- **The `reports/vivado/synth_ip.log` (2026-07-07) is STALE.** It was produced
  against the pre-`9e200af` RTL whose `posterior_mem[P][DEPTH]` /
  `message_mem[P][GROUPS]` 2-D arrays inferred as ~94 k flip-flops
  (`8-7186 ram_style ignored`, `8-11357 3D-RAM with 20480/73728 registers`) and
  never finished (1.5 h, ~10.9 GB). That RTL no longer exists — commit `9e200af`
  replaced it with per-lane single-port `bank_mem` generate blocks + a crossbar.
- The current banked RTL has been re-characterized with targeted OOC experiments
  (see `docs/SYNTHESIS_MEMORY_ANALYSIS.md` and `experiments/synthesis/`). It now
  infers **block RAM with zero flip-flops for storage** — the `8-7186`/`8-11357`
  warnings are **gone**, and the integrated decoder core peaks at **3.25 GB**
  through RTL optimization (vs 10.9 GB before). Expected block RAM:
  **16 × RAMB18E1 ≈ 8 BRAM tiles (~5.7 % of the XC7Z020)**.
- With `VIVADO_MAX_THREADS=2` the decoder-core OOC synth now **runs to completion**
  (~28 min, ≤ 7.96 GB) instead of thrashing in *Cross Boundary and Area
  Optimization*:

```sh
VIVADO_MAX_THREADS=2 make synth FPGA_PART=xc7z020clg400-1
```

- The first completing run exposed a LUT-fit blocker (~104 k LUTs = ~196 % of the
  XC7Z020) caused by the flat 2560-bit `hard_full` hard-decision register's wide
  mux cones. **This has been fixed:** `hard_full` was removed (it was a redundant
  shadow of the posterior-bank sign bit) and the syndrome/output readers serialised
  over the banked posterior RAM. Re-synthesis: **LUT-as-logic 104 072 → 7 990
  (15 %)**, FF 3 002, BRAM 12 tiles, DSP 0 — the design now fits with large margin.
  Functionally verified (all decoder vectors at LANES 1/8/16, plus AXI framing).
- **Timing — closed at 100 MHz.** The −57.8 ns WNS (the `saturation_count`
  diagnostic counter, a 48-deep 32-bit ripple exposed once storage moved to BRAM)
  was fixed by four behaviour-preserving RTL changes: (1) `$countones` popcount
  tree, (2) deferred 32-bit accumulate from registers, (3) lane-local saturation
  subcounts, (4) pipelined min1/min2 reduction (fold one edge behind +
  `S_GROUP_MIN_DRAIN`). **Full place & route: WNS −57.8 → +0.009 ns (100 MHz met)**
  with a directed impl (default flow lands at −0.056 ns / 4 endpoints ≈ 99.4 MHz), hold met,
  BRAM/DSP unchanged, decode bit-identical. Fix (4) adds **+1 cycle per group**
  of latency. Details in **`docs/SYNTHESIS_MEMORY_ANALYSIS.md`** →
  "Setup-timing remediation". Do not relax the 100 MHz XDC.
- The PS/AXI-DMA PYNQ-Z2 flow has completed synthesis, implementation, and
  bitstream/handoff export. Post-route WNS/TNS is **+0.091/0.000 ns** and hold
  WHS/THS is **+0.018/0.000 ns** at 100 MHz; DRC has no Error or Critical
  Warning violations and `check_timing` reports zero unconstrained endpoints.
- `constraints/pynq_z2.xdc` remains intentionally inactive and unverified for
  the separate PL-only LED flow. The PS/AXI-DMA overlay exposes only Zynq hard
  DDR/FIXED_IO interfaces and uses generated PS/IP constraints.
- Yosys 0.9 (oss-cad-suite) is installed but fails before elaboration on the
  generated SystemVerilog package:

```text
rtl/ar4ja_1024_pkg.sv:3: ERROR: syntax error, unexpected TOK_ID, expecting '='
```

## What To Inspect In Vivado

After `make synth` or `make impl`, inspect:

- `ram_utilization.rpt` for posterior and message memory inference;
- `utilization_*.rpt` for LUT/FF/BRAM/DSP scale;
- `timing_summary_*.rpt` for worst negative slack and critical paths;
- `hierarchy.rpt` for expected hierarchy and no duplicate top;
- `drc.rpt` for critical warnings and clock/reset issues;
- `vivado.log` for unsupported constructs or ignored attributes.
