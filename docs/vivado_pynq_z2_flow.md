# Vivado PYNQ-Z2 Board Bring-Up Flow

This document describes the **staged** Vivado flow for taking the existing
CCSDS AR4JA LDPC decoder from IP-level synthesis toward a real PYNQ-Z2
(`xc7z020clg400-1`) bitstream, without changing the decoder architecture.

It is deliberately separate from, and complementary to, the fuller PS/AXI-DMA
block-design flow in `boards/pynq_z2/vivado/pynq_z2_build.tcl` (see
["Relationship to the PS/DMA flow"](#relationship-to-the-psdma-flow)).

## Stages

| Stage | Make target | Script | What it proves |
|-------|-------------|--------|----------------|
| 0 | `make vivado-smoke` | `scripts/vivado/smoke.tcl` | Vivado runs and knows the part |
| 1 | `make vivado-synth-ip` | `scripts/vivado/synth_ip.tcl` | Decoder IP top synthesizes (OOC) |
| 2 | `make vivado-synth-pynq-z2` | `scripts/vivado/synth_pynq_z2_top.tcl` | Board top + XDC synthesize with real ports |
| 3 | `make vivado-impl-pynq-z2` | `scripts/vivado/impl_pynq_z2_top.tcl` | Board top places & routes |
| 4 | `make vivado-bitstream` | same, gated | Bitstream — only when XDC is verified |

Design under test:
- **IP top:** `ldpc_axis_decoder_ip` (`rtl/ldpc_axis_decoder_ip.sv`) — AXI-Stream
  slave/master (`aclk`, `aresetn`, 32-bit `s_axis`/`m_axis`) plus 4 status flags
  (`frame_error`, `early_tlast_error`, `missing_tlast_error`, `tkeep_error`).
- **Board top:** `pynq_z2_top` (`rtl/board/pynq_z2_top.sv`).

## Prerequisites

- Vivado 2025.2 installed at `/tools/AMD/2025.2/Vivado`.
- The flow sources `/tools/AMD/2025.2/Vivado/settings64.sh`. Override with
  `VIVADO_SETTINGS=/path/to/settings64.sh` (Make) or the same environment
  variable (shell scripts).

### Verify Vivado is available

```bash
make vivado-smoke
```

This confirms `vivado` launches and that `xc7z020clg400-1` is in the install.
Expected tail: `Target part available: xc7z020clg400-1`.

## Stage 1 — IP-level synthesis

```bash
make vivado-synth-ip
```

Reads the package-first source manifest `rtl/ldpc_sources.f` with
`read_verilog -sv`, then synthesizes `ldpc_axis_decoder_ip` **out of context**
(no pins). Outputs:

- Checkpoint: `build/vivado/synth_ip.dcp`
- Reports: `reports/vivado/synth_ip/{utilization,timing_summary,drc}.rpt`
- Log: `reports/vivado/synth_ip.log`

## Stage 2 — PYNQ-Z2 board top synthesis

```bash
make vivado-synth-pynq-z2
```

Reads the same RTL manifest plus `rtl/board/pynq_z2_top.sv` and
`constraints/pynq_z2.xdc`, then synthesizes `pynq_z2_top`. Outputs:

- Checkpoint: `build/vivado/synth_pynq_z2_top.dcp`
- Reports: `reports/vivado/synth_pynq_z2/*.rpt`
- Log: `reports/vivado/synth_pynq_z2.log`

The script warns about any top-level port left without a `PACKAGE_PIN`.

## Stage 3 — Implementation (place & route)

```bash
make vivado-impl-pynq-z2
```

Opens the Stage 2 checkpoint and runs `opt_design` → `place_design` →
`route_design` (route only, **no bitstream**). Outputs:

- Checkpoint: `build/vivado/impl_pynq_z2_top.dcp`
- Reports: `reports/vivado/impl_pynq_z2/*.rpt` (including `route_status.rpt`)

## Stage 4 — Bitstream (gated)

```bash
make vivado-bitstream
```

Bitstream generation is **refused** unless BOTH conditions hold:

1. `constraints/pynq_z2.xdc` contains the line `STATUS: VERIFIED`.
2. Setup timing is met (WNS ≥ 0).

This prevents writing a bitstream over guessed pins or a failing design. If the
XDC is still `STATUS: UNVERIFIED`, the run fails cleanly with an explanatory
message. See ["XDC status"](#xdc-status) for what to verify first.

## What the minimal board top does

`pynq_z2_top`:

- Brings in `sysclk` (125 MHz), `rst_btn`, and drives 4 user `led[3:0]` — the
  only external I/O, all real board resources.
- Synchronizes the reset button and runs a free-running heartbeat counter →
  `led[0]` (proves the design is clocked and out of reset).
- Contains a **small internal LFSR stimulus** that streams pseudo-random words
  into the decoder's AXI-Stream slave and always accepts its master port. This
  keeps the full decoder datapath alive through synthesis/implementation rather
  than being constant-folded away.
- Surfaces coarse activity/status on `led[1..3]`: input handshake seen, output
  handshake/data activity, and a sticky framing/tkeep error flag.

## What the minimal board top does NOT prove

- **Not functional correctness.** The internal stimulus is **not** valid CCSDS
  codeword data, so a lit "output" or "error" LED says nothing about decode
  correctness. Correctness is proven only by the simulation testbenches and the
  Python/RTL regression (`make regression`), never by this board top.
- **No PS / AXI-DMA / DDR.** This is a PL-only bring-up top; there is no data
  path to or from the Zynq processing system here.
- **Timing closure at 125 MHz is a known open item.** The decoder was not
  timing-optimized for the full board clock; Stage 3 may report negative slack.
  Options for real bring-up: add an MMCM/clock divider to run the decoder
  slower, or pipeline the critical paths. Until then, `make vivado-bitstream`
  will (correctly) refuse if timing is not met.

## What remains for real PS / AXI-DMA integration

The complete accelerator path (PS7 + AXI DMA + HP port + address map) already
exists as a block-design script: `boards/pynq_z2/vivado/pynq_z2_build.tcl`
(`make pynq-z2-project | pynq-z2-synth | pynq-z2-bitstream`). Real data movement
from Linux/PYNQ into the decoder should use that flow, not `pynq_z2_top`.
Outstanding items there include installing the TUL PYNQ-Z2 board files and
validating the DMA/decoder AXI-Stream widths end to end on hardware.

## Relationship to the PS/DMA flow

- `pynq_z2_top` (this doc) = minimal, PL-only, LED bring-up. Fast path to prove
  the RTL synthesizes and implements on the real part with real pins.
- `boards/pynq_z2/vivado/pynq_z2_build.tcl` = full PS/AXI-DMA overlay. The real
  software-controlled accelerator target.

Both target `xc7z020clg400-1`.

## XDC status

`constraints/pynq_z2.xdc` is currently **`STATUS: UNVERIFIED`**.

The `PACKAGE_PIN`/`IOSTANDARD` values match the widely published TUL PYNQ-Z2
v1.0 master constraints (`sysclk=H16` @125 MHz, `led[0..3]=R14/P14/N16/M14`,
`rst_btn=BTN0=D19`, all `LVCMOS33`), but **no PYNQ-Z2 board files were found in
the local Vivado install** to auto-verify them. Before generating a bitstream:

1. Cross-check every pin against the official master XDC for **your** board
   revision (e.g. the Xilinx/TUL PYNQ-Z2 reference).
2. Confirm the button you want as reset (BTN0/D19 assumed) and the LED mapping.
3. Change the header line in `constraints/pynq_z2.xdc` to `STATUS: VERIFIED`.

Only then will `make vivado-bitstream` proceed.

## Cleaning up

```bash
make clean-vivado   # removes build/vivado, reports/vivado, .Xil
```
