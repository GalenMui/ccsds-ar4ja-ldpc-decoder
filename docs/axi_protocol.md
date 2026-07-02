# AXI Protocol

## Input

The decoder accepts one AXI-Stream frame per codeword.

- `s_axis_tdata`: 32 bits
- `s_axis_tvalid/s_axis_tready`: standard handshake
- `s_axis_tlast`: required on the final input word
- Input words: 512
- LLRs per word: 4
- LLR type: signed int8

Lane order:

```text
tdata[7:0]   -> codeword index 4*w + 0
tdata[15:8]  -> codeword index 4*w + 1
tdata[23:16] -> codeword index 4*w + 2
tdata[31:24] -> codeword index 4*w + 3
```

The wrapper captures one accepted word, deasserts `s_axis_tready`, and writes
the four lanes into the core over four cycles. Arbitrary `s_axis_tvalid` gaps
are allowed.

## Malformed Input

Error flags are asserted through the error output transaction and remain set
until the next accepted frame begins.

Early `TLAST`:

- The partial frame is rejected.
- `frame_error` and `early_tlast_error` assert.
- The output frame has `decoder_success=0` and `decoder_fail=1`.

Missing final `TLAST`:

- The 512-word frame is rejected.
- `frame_error` and `missing_tlast_error` assert.
- An error output frame is produced.
- After the output frame, the wrapper enters a drain state and discards input
  words until a word with `s_axis_tlast=1` handshakes.
- The next valid frame is accepted only after that drain `TLAST`.

## Output

The output frame is 40 words:

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

`m_axis_tdata`, `m_axis_tvalid`, and `m_axis_tlast` remain stable while
`m_axis_tvalid=1` and `m_axis_tready=0`. `m_axis_tlast` is asserted only on
word 39.

## Reset

`ldpc_axis_wrapper` uses active-high synchronous behavior from the external
`rst` input. `ldpc_axis_decoder_ip` exposes Vivado-style `aresetn` and converts
it to the wrapper reset internally.
