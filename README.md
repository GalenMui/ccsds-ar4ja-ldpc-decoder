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

The RTL decoder is a row-serial, edge-serial layered normalized min-sum core.
It is not a complete modem: synchronization, demodulation, packet parsing,
multi-rate support, and board-specific constraints are outside this project.

## Architecture Status

Implemented:

- Fixed CCSDS AR4JA rate-1/2, k=1024 graph generation.
- Python systematic encoder and fixed-point layered normalized min-sum model.
- Generated `rtl/ar4ja_1024_pkg.sv` graph package.
- Memory-based RTL decoder core with:
  - synchronous posterior RAM, 2560 signed 8-bit entries;
  - row-packed check-message RAM, 1536 x 48 bits;
  - hard-decision vector updated during load and layered writeback;
  - sequential punctured-variable initialization;
  - sequential check-message clear;
  - one check row active at a time and one posterior edge read/write at a time.
- 32-bit AXI-Stream wrapper preserving the 512-word input and 40-word output ABI.
- Board-facing `aclk`/`aresetn` wrapper for Vivado-style IP integration.
- Icarus regression tests and board-independent DMA packing/parsing utility.
- Vivado Tcl templates and an attempted Yosys flow.

Current limitations:

- Only 3/4 normalization is implemented.
- Only this CCSDS mode is supported.
- No row or edge parallelism yet.
- Vivado was not available in this environment, so vendor utilization/timing
  were not measured.
- The local Yosys build cannot parse the generated SystemVerilog package, so
  generic synthesis is blocked by tool support here.

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

## Cycle Counts

Measured in RTL simulation for the core, excluding AXI input/output transfer:

- Initial pass, all-zero valid frame: 3,616 cycles.
- One layered iteration: 30,720 cycles.
- Worst-case 8 iterations: 249,376 cycles.
- Degree-3 row: 13 cycles.
- Degree-6 row: 22 cycles.
- Sequential syndrome pass: 1,536 cycles.

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
python3 scripts/run_regression.py
```

Useful Make targets:

```sh
make test
make regression
make clean
```

Direct decoder simulation:

```sh
python3 scripts/gen_decoder_vectors.py
iverilog -g2012 -o sim/build/ldpc_decoder_top.vvp \
  rtl/ar4ja_1024_pkg.sv rtl/posterior_memory.sv rtl/message_memory.sv \
  rtl/ldpc_decoder_top.sv sim/tb_ldpc_decoder_top.sv
vvp sim/build/ldpc_decoder_top.vvp
```

Direct AXI simulation:

```sh
iverilog -g2012 -o sim/build/ldpc_axis_wrapper.vvp \
  rtl/ar4ja_1024_pkg.sv rtl/posterior_memory.sv rtl/message_memory.sv \
  rtl/ldpc_decoder_top.sv rtl/ldpc_axis_wrapper.sv sim/tb_ldpc_axis_wrapper.sv
vvp sim/build/ldpc_axis_wrapper.vvp
```

## Synthesis

Vivado out-of-context template:

```sh
vivado -mode batch -source fpga/synth_ooc.tcl -tclargs <fpga_part>
```

or:

```sh
FPGA_PART=<fpga_part> vivado -mode batch -source fpga/synth_ooc.tcl
```

The default clock constraint is 10 ns on `aclk` in
`fpga/constraints/ldpc_axis_decoder.xdc`.

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

- `docs/architecture.md`
- `docs/axi_protocol.md`
- `docs/verification_plan.md`
- `docs/fpga_bringup.md`
