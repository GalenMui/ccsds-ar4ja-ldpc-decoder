# Stream Protocol

The FPGA-facing top is `ldpc_axis_decoder_ip`. It exposes one clock, one
active-low reset, one 32-bit AXI4-Stream input, one 32-bit AXI4-Stream output,
and four frame-error status signals.

## Clock And Reset

- `aclk`: single clock for all logic and both streams
- `aresetn`: active-low reset, converted internally to active-high `rst`
- Keep `aresetn=0` until `aclk` is stable
- Reset returns the wrapper to idle, clears output valid, and clears error flags

## Input Frame

Each input frame contains exactly 512 accepted AXI words.

```text
2048 transmitted LLRs / 4 LLRs per word = 512 words
```

Each LLR is a signed int8 in two's-complement form. Byte-lane order is:

```text
s_axis_tdata[7:0]   -> codeword index 4*w + 0
s_axis_tdata[15:8]  -> codeword index 4*w + 1
s_axis_tdata[23:16] -> codeword index 4*w + 2
s_axis_tdata[31:24] -> codeword index 4*w + 3
```

`s_axis_tkeep` must be `4'hf` on every accepted input word. `s_axis_tlast`
must be asserted with word 511. Input counters advance only on
`s_axis_tvalid && s_axis_tready`.

The wrapper accepts one word, deasserts `s_axis_tready`, writes the four LLRs
into the core over four cycles, then accepts the next word.

## Output Frame

Each output frame contains exactly 40 accepted AXI words.

```text
word 0:  0x4C445043, ASCII "LDPC"
word 1:  decoder_success
word 2:  syndrome_pass
word 3:  iterations_used
word 4:  cycles_elapsed
word 5:  decoder_fail
word 6:  saturation_count
word 7:  reserved, zero
word 8:  decoded_bits[31:0]
word 9:  decoded_bits[63:32]
...
word 39: decoded_bits[1023:992]
```

Payload bit `decoded_bits[i]` appears at bit `i % 32` of output word
`8 + floor(i / 32)`.

Output counters advance only on `m_axis_tvalid && m_axis_tready`.
`m_axis_tdata`, `m_axis_tkeep`, and `m_axis_tlast` remain stable while
`m_axis_tvalid=1 && m_axis_tready=0`. `m_axis_tkeep` is `4'hf` for every valid
output beat. `m_axis_tlast` is asserted only on word 39.

## Malformed Frames

Early `TLAST` before word 511:

- Partial input is rejected.
- `frame_error=1` and `early_tlast_error=1`.
- A normal 40-word output frame is produced with `decoder_success=0` and
  `decoder_fail=1`.
- The wrapper returns to idle after the error output frame.

Missing `TLAST` on word 511:

- The 512-word input is rejected.
- `frame_error=1` and `missing_tlast_error=1`.
- A normal 40-word output frame is produced with `decoder_success=0` and
  `decoder_fail=1`.
- After the output frame, the wrapper drains input until an accepted word has
  `s_axis_tlast=1`.
- A valid frame after drain is accepted without reset.

Bad `TKEEP`:

- Every input word must be a full four-byte beat.
- If an accepted input word has `s_axis_tkeep != 4'hf`, the frame is rejected.
- `frame_error=1` and `tkeep_error=1`.
- A normal 40-word output frame is produced with `decoder_success=0` and
  `decoder_fail=1`.
- If the bad beat was not also `TLAST`, the wrapper drains input until an
  accepted word has `s_axis_tlast=1`.

Error flags remain visible through the error output transaction and are cleared
when the next input frame begins.

## Transfer Sizes

- Input DMA transfer: 512 words = 2048 bytes
- Output DMA transfer: 40 words = 160 bytes
- Stream width: 32 bits
- Input `TLAST`: word 511
- Output `TLAST`: word 39
- Input `TKEEP`: `4'hf` on every word
- Output `TKEEP`: `4'hf` on every valid word

## Host Utility

Pack and parse board-independent files:

```sh
python3 scripts/ldpc_dma_util.py pack llr.txt dma_input.bin
python3 scripts/ldpc_dma_util.py parse dma_output.bin --expected-bits expected_bits.txt
```
