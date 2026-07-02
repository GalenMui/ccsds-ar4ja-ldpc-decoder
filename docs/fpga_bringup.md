# FPGA Bring-Up Guide

This guide is board-independent. Complete board-specific clock, reset, DDR,
DMA, interrupt, address-map, and pin setup after selecting hardware.

## Vivado Integration

1. Add the RTL sources from `rtl/ldpc_sources.f`, or package the wrapper with
   `fpga/package_ip.tcl`.
2. Use `ldpc_axis_decoder_ip` as the block-design boundary.
3. Connect `aclk` and `aresetn`.
4. Connect AXI DMA MM2S to the decoder input stream.
5. Connect decoder output stream to AXI DMA S2MM.
6. Use 32-bit stream widths.
7. Start with one shared AXI clock/reset domain.
8. Do not add board pin constraints in this IP project.

Suggested block diagram:

```text
Processor or host memory
        |
AXI DMA MM2S
        |
LDPC AXI-Stream decoder
        |
AXI DMA S2MM
        |
Processor or host memory
```

## Synthesis Template

Run out-of-context synthesis with a selected FPGA part:

```sh
vivado -mode batch -source fpga/synth_ooc.tcl -tclargs <fpga_part>
```

or:

```sh
FPGA_PART=<fpga_part> vivado -mode batch -source fpga/synth_ooc.tcl
```

The clock constraint template is `fpga/constraints/ldpc_axis_decoder.xdc` and
defaults to 10 ns, 100 MHz.

## DMA Test Procedure

1. Allocate 512 input words.
2. Allocate 40 output words.
3. Pack four signed int8 LLRs per input word.
4. Put the lowest codeword index in byte lane 0.
5. Start S2MM receive DMA before MM2S transmit DMA.
6. Assert `TLAST` on input word 511.
7. Wait for both DMAs to complete.
8. Parse the 40 output words.
9. Check word 0 is `0x4C445043`.
10. Check success, syndrome, iteration, cycle, failure, and saturation fields.
11. Compare decoded bits against a known vector.

Use the host utility:

```sh
python3 scripts/ldpc_dma_util.py pack llr.txt dma_input.bin
python3 scripts/ldpc_dma_util.py parse dma_output.bin --expected-bits expected_bits.txt
```

The compact all-zero known-good vector is:

```text
vectors/board/zero_noiseless_axi_words.txt
```

## ILA Probes

Recommended first probes:

- input `TVALID`, `TREADY`, `TDATA`, `TLAST`;
- output `TVALID`, `TREADY`, `TDATA`, `TLAST`;
- wrapper state;
- core state;
- row index;
- edge index;
- iteration index;
- core start, busy, done;
- syndrome pass;
- decoder success/fail;
- frame error flags.

If the design stalls, first check for missing input `TLAST`, output DMA not
asserting `TREADY`, and reset polarity mistakes.
