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
make pynq-z2-overlay
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
definition and uses the board preset when available. Without board files, it
falls back to the raw part and warns that the result is for structural checks
until board files are installed.

Board reports are written under:

```text
results/pynq_z2/reports/synth/
results/pynq_z2/reports/impl/
```

The overlay package target copies matching artifact names to:

```text
results/pynq_z2/overlay/ccsds_ldpc_pynq_z2.bit
results/pynq_z2/overlay/ccsds_ldpc_pynq_z2.hwh
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

- A logged out-of-context `synth_design -top ldpc_axis_decoder_ip
  -part xc7z020clg400-1` run **elaborated the full RTL cleanly** and began
  synthesis, but **did not complete** on the 12 GB host. The log
  (`reports/vivado/synth_ip.log`) ends inside `Start Technology Mapping` after
  roughly 1.5 h of cross-boundary/timing optimization (peak ~10.9 GB RSS with
  ~100 MB physical memory free). No `utilization_*.rpt`,
  `timing_summary_*.rpt`, or `.dcp` was produced.
- Because synthesis did not finish, **no LUT, FF, BRAM, DSP, timing, power, or
  Fmax numbers are available or claimed.**
- The synthesis log shows the posterior and check-message memories are being
  inferred as large flip-flop arrays, not block RAM:

```text
WARNING: [Synth 8-7186] Applying attribute ram_style = "block" is ignored,
  object 'posterior_mem[0][0]' is not inferred as ram due to incorrect usage
WARNING: [Synth 8-11357] Potential Runtime issue for 3D-RAM ... RAM
  posterior_mem_reg with 20480 registers
WARNING: [Synth 8-11357] Potential Runtime issue for 3D-RAM ... RAM
  message_mem_reg with 73728 registers
```

  This flip-flop inference (~94k registers for the memories alone) is almost
  certainly why synthesis is so slow/memory-hungry and must be resolved (single
  synchronous read/write port per bank, no asynchronous reset over the array)
  before area or timing can be assessed on the XC7Z020.
- PYNQ-Z2 project synthesis, implementation, bitstream generation, and overlay
  export have **not** been run.
- The bitstream target remains gated: `constraints/pynq_z2.xdc` is marked
  `STATUS: UNVERIFIED`, and `make vivado-bitstream` refuses to run until the
  pin/IO constraints are verified against a trusted PYNQ-Z2 source.
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
