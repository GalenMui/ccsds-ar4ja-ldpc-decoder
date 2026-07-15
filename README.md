# ccsds-ar4ja-ldpc-decoder

Synthesizable SystemVerilog and Python reference models for one fixed CCSDS
AR4JA LDPC mode from CCSDS 131.0-B-5:

- Code family: AR4JA LDPC
- Rate: 1/2
- k: 1024 information bits
- Transmitted variables: 2048
- Full internal variables: 2560
- Punctured variables: 512, internal indices 2048..2559
- Parity-check rows: 1536

The RTL decoder is a partially parallel layered normalized min-sum core. The
default configuration processes 8 independent check rows per schedule group;
`LANES=1` and `LANES=16` are also generated and regression-tested.
It is not a complete modem: synchronization, demodulation, packet parsing,
multi-rate support, and board-specific constraints are outside this project.

## Architecture Status

Implemented:

- Fixed CCSDS AR4JA rate-1/2, k=1024 graph generation.
- Python systematic encoder and fixed-point layered normalized min-sum model.
- Generated `rtl/ar4ja_1024_pkg.sv` graph package.
- Memory-based RTL decoder core with:
  - banked synchronous posterior RAM, 2560 signed 8-bit entries total
    (P single-port banks, block-RAM inferred);
  - lane-banked row-packed check-message RAM, 1536 x 48 bits total
    (block-RAM inferred);
  - hard decisions read directly from the posterior-bank sign bits (no separate
    hard-decision register); syndrome check and output read are serialised over
    the banked read port;
  - bank-parallel punctured-variable initialization;
  - bank-parallel check-message clear;
  - pipelined min1/min2 reduction (folded one edge behind) for timing;
  - generated conflict-free row groups for `LANES=1`, `LANES=8`, and
    `LANES=16`.
- 32-bit AXI-Stream wrapper preserving the 512-word input and 40-word output ABI.
- Board-facing `aclk`/`aresetn` wrapper for Vivado-style IP integration.
- Explicit AXI4-Stream `TKEEP` handling for AXI DMA integration.
- Tcl-based PYNQ-Z2 Vivado block-design flow and PYNQ host software.
- Timing-closed PYNQ-Z2 bitstream, hardware handoff, deployment script, and
  load-only/functional board smoke-test scripts.
- Icarus regression tests and board-independent DMA packing/parsing utility.
- Vivado Tcl templates and an attempted Yosys flow.

Current limitations:

- Only 3/4 normalization is implemented.
- Only this CCSDS mode is supported.
- `LANES=8` is the production default. `LANES=1`, `LANES=8`, and `LANES=16`
  all pass the deterministic RTL vector regression (all 11 vectors).
- The local Yosys 0.9 build cannot parse the generated SystemVerilog package,
  so open-source generic synthesis is blocked by tool support here.
- The AXI-Stream wrapper, core decoder, and syndrome simulations all build and
  pass under the installed Icarus 14 toolchain.

## Timing / Resources (Vivado 2025.2, xc7z020clg400-1, OOC)

`ldpc_axis_decoder_ip`, `LANES=8`, clock `aclk` 10.000 ns (100 MHz):

| Metric | Value |
|--------|-------|
| Stage | out-of-context **post-route implementation** |
| Setup WNS / TNS | **+0.009 ns / 0.000 ns** (0 failing endpoints) |
| Hold WHS / THS | **+0.128 ns / 0.000 ns** (0 failing endpoints) |
| Slice LUTs | 7 848 (14.75 %) |
| Slice Registers | 4 626 (4.35 %) |
| Block RAM tiles | 12 = 8×RAMB36 + 8×RAMB18 (8.57 %) |
| DSP48E1 | 0 |
| Critical warnings | 0 |

The posterior and check-message memories infer block RAM (no flip-flop arrays,
`ram_style="block"` honoured). Setup closure at 100 MHz was reached with a
directed implementation (`synth -retiming`, `place`/`route -directive Explore`,
post-route `phys_opt_design`); the default flow lands at WNS −0.056 ns (≈99.4
MHz). Reproduce with `experiments/synthesis/impl_ip_timing.tcl` (default) or the
directed strategy documented in `docs/SYNTHESIS_MEMORY_ANALYSIS.md`.

The complete PYNQ-Z2 PS/AXI-DMA design also closes at 100 MHz and produces a
bitstream (WNS +0.091 ns, TNS 0; hold WHS +0.018 ns, THS 0). Physical-board
loading and end-to-end DMA testing still require an unlocked SSH key; no
on-hardware throughput or BER is claimed. Numbers above remain tool-reported
OOC results, not board measurements.

## Fixed-Point Rules

- Input/posterior LLR width: signed 8 bits.
- Check-message width: signed 8 bits.
- Positive posterior means hard bit 0.
- Negative posterior means hard bit 1.
- Zero ties to hard bit 0.
- Punctured variables initialize to neutral LLR 0 and are decoded normally.
- Layered row update:

```text
q_mj = L_j - R_mj_old
R_mj_new = sign_excluding_edge * floor(selected_min * 3 / 4)
L_j_new = q_mj + R_mj_new
```

Saturation events are counted only when clipping changes the mathematical value.

## AXI-Stream ABI

Input frame:

- 512 words.
- 32-bit `s_axis_tdata`.
- `s_axis_tkeep` must be `4'hf` on every accepted word.
- Four signed int8 LLRs per word.
- Lane ordering: bits `[7:0]` are the lowest codeword index in the word, then
  `[15:8]`, `[23:16]`, `[31:24]`.
- `s_axis_tlast` must be asserted on word 511.

Output frame:

```text
word 0:  0x4C445043 ("LDPC")
word 1:  decoder_success
word 2:  syndrome_pass
word 3:  iterations_used
word 4:  cycles_elapsed
word 5:  decoder_fail
word 6:  saturation_count
word 7:  reserved, zero
word 8..39: decoded_bits[1023:0], 32 bits per word
```

`m_axis_tkeep` is `4'hf` on every valid output word. `m_axis_tlast` is asserted
only on output word 39.

## Cycle Counts

Measured in RTL simulation for the core, excluding AXI input/output transfer:

- `LANES=8` default: initial pass 480 cycles; one layered iteration 3,840
  cycles; worst-case 8 iterations 31,200 cycles.
- `LANES=16`: initial pass 256 cycles; one layered iteration 1,920 cycles;
  worst-case 8 iterations 15,616 cycles.
- `LANES=1`: initial pass 3,616 cycles; one layered iteration 30,720 cycles;
  worst-case 8 iterations 249,376 cycles.
- Degree-3 group: 13 cycles.
- Degree-6 group: 22 cycles.
- Syndrome pass: `1536 / LANES` cycles.

These are functional simulation counts, not timing-closed FPGA results.

## Repository Structure

```text
docs/        Architecture, protocol, verification, and bring-up notes
fpga/        Board-independent Vivado/Yosys synthesis templates
models/      Python matrix, encoder, channel, quantization, and decoder models
rtl/         SystemVerilog graph package, memories, core, and AXI wrappers
sim/         Icarus testbenches
scripts/     Generation, regression, DMA utility, and report scripts
tests/       Python unit tests
vectors/     Deterministic regression and board-test vectors
results/     Generated reports and plots
```

`rtl/ar4ja_1024_pkg.sv` is generated. Regenerate it with:

```sh
python3 scripts/gen_syndrome_rom.py
```

## Run Regression

```sh
make test
```

Useful Make targets:

```sh
make generate
make lint
make test
make regression
make synth FPGA_PART=<part>
make impl FPGA_PART=<part>
make package-ip FPGA_PART=<part>
make pynq-z2-project
make pynq-z2-synth
make pynq-z2-bitstream
make pynq-z2-overlay
make clean
```

Direct decoder simulation:

```sh
python3 scripts/gen_decoder_vectors.py
iverilog -g2012 -o sim/build/ldpc_decoder_top.vvp \
  rtl/ar4ja_1024_pkg.sv rtl/ldpc_schedule_pkg.sv \
  rtl/posterior_memory.sv rtl/message_memory.sv \
  rtl/ldpc_decoder_top.sv sim/tb_ldpc_decoder_top.sv
vvp sim/build/ldpc_decoder_top.vvp
```

Direct AXI simulation:

```sh
iverilog -g2012 -o sim/build/ldpc_axis_wrapper.vvp \
  rtl/ar4ja_1024_pkg.sv rtl/ldpc_schedule_pkg.sv \
  rtl/posterior_memory.sv rtl/message_memory.sv \
  rtl/ldpc_decoder_top.sv rtl/ldpc_axis_wrapper.sv sim/tb_ldpc_axis_wrapper.sv
vvp sim/build/ldpc_axis_wrapper.vvp
```

## Synthesis

Vivado out-of-context template:

```sh
make synth FPGA_PART=<fpga_part>
```

Implementation and IP packaging:

```sh
make impl FPGA_PART=<fpga_part>
make package-ip FPGA_PART=<fpga_part>
```

The default clock constraint is 10 ns on `aclk` in
`fpga/constraints/ldpc_axis_decoder.xdc`.

**Current synthesis status:** Vivado 2025.2; the `LANES=8` IP completes
out-of-context synthesis **and place & route** on the target part. Setup timing
closes at 100 MHz (post-route WNS +0.009 ns, hold WHS +0.128 ns, 0 critical
warnings); block RAM is inferred for the posterior and check-message memories.
See the "Timing / Resources" table above and `docs/SYNTHESIS_MEMORY_ANALYSIS.md`
for the full architecture/timing analysis. The routed board-overlay evidence
and exact deployment commands are in `docs/PYNQ_Z2_BRINGUP.md`.

## PYNQ-Z2 Overlay

First-board integration targets the TUL PYNQ-Z2
(`xc7z020clg400-1`) using PS DDR, AXI DMA, and the existing
`ldpc_axis_decoder_ip` stream interface:

```sh
make pynq-z2-project
make pynq-z2-synth
make pynq-z2-bitstream
make pynq-z2-package
```

The packaged overlay appears under:

```text
build/pynq_z2/deploy/
```

Deploy the runtime subset without deleting unrelated board files:

```sh
./scripts/board/deploy_pynq.sh
```

Then run the load-only test before the functional DMA test:

```sh
python3 load_overlay.py
python3 smoke_test.py
python3 benchmark.py --frames 10
```

See `docs/PYNQ_Z2_BRINGUP.md`, `docs/PYNQ_Z2.md`, and
`docs/BOARD_READINESS_AUDIT.md`.

## DMA Utility

Pack 2048 signed int8 LLRs into 512 little-lane 32-bit words:

```sh
python3 scripts/ldpc_dma_util.py pack llr.txt dma_input.bin
```

Parse a 40-word response:

```sh
python3 scripts/ldpc_dma_util.py parse dma_output.bin
```

See `vectors/board/zero_noiseless_axi_words.txt` for a compact known-good
all-zero frame.

## Start Reading

- `docs/ARCHITECTURE.md`
- `docs/STREAM_PROTOCOL.md`
- `docs/VERIFICATION.md`
- `docs/SYNTHESIS.md`
- `docs/BOARD_BRINGUP.md`
- `docs/PYNQ_Z2_BRINGUP.md`
- `docs/PYNQ_Z2.md`
- `docs/BOARD_READINESS_AUDIT.md`
- `docs/REPO_STATUS.md`
