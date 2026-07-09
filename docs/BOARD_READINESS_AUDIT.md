# Board Readiness Audit

Last updated: July 5, 2026.

## Architecture Found

The active decoder is not an HLS design and not a modem shell. It is a
SystemVerilog, partially parallel, layered normalized min-sum decoder for one
fixed CCSDS AR4JA mode:

- Rate 1/2, k=1024 information bits.
- 2048 transmitted LLRs per frame.
- 2560 internal variables including 512 punctured variables.
- 1536 parity-check rows.
- Signed 8-bit input/posterior LLRs and signed 8-bit check messages.
- Fixed 3/4 normalization and fixed `MAX_ITERS=8` in the board build.
- Default `LANES=8`; generated schedules also cover `LANES=1` and `LANES=16`.

The authoritative FPGA-facing top is:

```text
rtl/ldpc_axis_decoder_ip.sv
```

The synthesis source order is:

```text
rtl/ldpc_sources.f
```

The design uses one clock domain at the decoder boundary: `aclk` plus active
low `aresetn`.

## Stream ABI

Input is one AXI4-Stream frame of 512 accepted 32-bit words:

- 2048 signed int8 LLRs.
- Four LLRs per word.
- Byte lane 0 is the lowest codeword index in the word.
- `s_axis_tkeep` must be `4'hf` on every accepted input word.
- `s_axis_tlast` must be asserted on input word 511.

Output is one AXI4-Stream frame of 40 accepted 32-bit words:

- 8 status words.
- 32 payload words containing decoded information bits.
- `m_axis_tkeep` is `4'hf` on every valid output word.
- `m_axis_tlast` is asserted only on output word 39.

The wrapper holds `m_axis_tdata`, `m_axis_tkeep`, and `m_axis_tlast` stable
while stalled. It accepts a new input frame after the previous output frame is
fully transferred. Back-to-back frames are supported at the transaction level,
with wrapper-controlled gaps while each accepted input word is unpacked into
four core writes.

Malformed input handling:

- Early `TLAST` produces a 40-word error response.
- Missing final `TLAST` produces a 40-word error response, then drains input
  until a later accepted word has `TLAST`.
- Bad input `TKEEP` produces a 40-word error response. If the bad beat was not
  also `TLAST`, the wrapper drains until `TLAST`.
- Reset aborts any in-progress input, decode, or output transaction and returns
  the wrapper to idle. Host software must restart both DMA channels after reset.

Transfer sizes for AXI DMA:

```text
Input:  512 words = 2048 bytes
Output:  40 words =  160 bytes
```

## Integration Boundary

The PYNQ-Z2 design keeps board logic outside the decoder core. The board
project instantiates:

- Zynq-7000 Processing System.
- AXI DMA in simple mode.
- AXI Interconnect for DMA AXI-Lite control from PS GP0.
- AXI Interconnect for DMA memory traffic to PS HP0.
- Processor System Reset.
- The existing `ldpc_axis_decoder_ip` RTL module.

No external PL pins are required for first bring-up.

The default board target is:

```text
Board: TUL PYNQ-Z2
Part:  xc7z020clg400-1
Clock: PS FCLK0 at 100 MHz
DMA:   axi_dma_0
DMA register base: 0x40400000
```

## Generated And Authoritative Files

Generated but checked-in source artifacts:

- `rtl/ar4ja_1024_pkg.sv`
- `rtl/ldpc_schedule_pkg.sv`
- `vectors/syndrome/*`
- `vectors/decoder/*`
- `vectors/schedule/*`

Regenerate them with:

```sh
make generate
```

Vivado projects, runs, bitstreams, handoff files, checkpoints, reports, and
overlay packages are generated artifacts under `results/` and are not
authoritative source.

## Verification Baseline

Pre-board-integration commands run in this environment on July 5, 2026:

```sh
make test
make lint
yosys -q -l results/reports/yosys_synth.log fpga/yosys_synth.ys
make synth FPGA_PART=xc7z020clg400-1
make impl FPGA_PART=xc7z020clg400-1
make package-ip FPGA_PART=xc7z020clg400-1
make pynq-z2-project
make pynq-z2-package
```

Observed results:

- `make test`: pass.
- `make lint`: pass.
- AXI wrapper simulation: pass with valid frames, stalls, malformed `TLAST`,
  bad `TKEEP`, reset after incomplete input, and malformed-then-valid recovery.
- Yosys 0.9: fails before elaboration on the generated SystemVerilog package.

Update (July 7, 2026): Vivado 2025.2 was subsequently installed. `make
vivado-smoke` passes and the `LANES=8` IP elaborates cleanly, but a logged
out-of-context `synth_design` run did **not** complete on the 12 GB host — it
reached technology mapping after ~1.5 h and produced no reports or checkpoint
(`reports/vivado/synth_ip.log`). PYNQ-Z2 synthesis, implementation, timing,
utilization, DRC, CDC, and bitstream generation have not been run. The
bitstream target stays gated on `constraints/pynq_z2.xdc` being marked
`STATUS: VERIFIED` (currently `UNVERIFIED`).

No hardware throughput, timing closure, utilization, or board-validation
results are claimed.

## Implementation Risks To Inspect In Vivado

The XC7Z020 fit and timing risk is dominated by:

- Posterior and check-message memory inference.
- The `hard_full[2559:0]` register vector used for syndrome checks.
- Generated graph lookup functions and row-column indexing.
- Lane-parallel min/sign reductions.
- High-fanout reset and frame-control signals.

The source avoids runtime reset loops over the inferred posterior memories.
Vivado reports that must be inspected after build:

```text
results/pynq_z2/reports/synth/ram_utilization_synth.rpt
results/pynq_z2/reports/synth/utilization_synth.rpt
results/pynq_z2/reports/synth/timing_summary_synth.rpt
results/pynq_z2/reports/impl/timing_summary_impl.rpt
results/pynq_z2/reports/impl/drc_impl.rpt
results/pynq_z2/reports/impl/cdc_impl.rpt
```
