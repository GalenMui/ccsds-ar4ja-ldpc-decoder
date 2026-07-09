# Architecture

This repository implements one fixed CCSDS AR4JA LDPC decoder mode:

- Code family: AR4JA LDPC
- Rate: 1/2
- Information bits: 1024
- Transmitted variables: 2048
- Full internal variables: 2560
- Punctured variables: 512, internal indices 2048..2559
- Check rows: 1536

## Authoritative RTL

Core top:

```text
rtl/ldpc_decoder_top.sv
```

FPGA-facing top:

```text
rtl/ldpc_axis_decoder_ip.sv
```

This top exposes 32-bit AXI4-Stream input and output interfaces with explicit
4-bit `TKEEP`, plus `frame_error`, `early_tlast_error`,
`missing_tlast_error`, and `tkeep_error` status outputs.

Source order is defined by:

```text
rtl/ldpc_sources.f
```

`rtl/syndrome_checker.sv` is a standalone tested utility. `rtl/posterior_memory.sv`
and `rtl/message_memory.sv` are reference synchronous RAM templates and are not
instantiated by the authoritative decoder core.

## Hierarchy

```text
ldpc_axis_decoder_ip
  ldpc_axis_wrapper
    ldpc_decoder_top
      banked posterior RAM arrays
      lane-banked row-message RAM arrays
      generated AR4JA graph functions
      generated schedule metadata
```

## Dataflow

```text
AXI input word
  -> 4 x signed int8 unpack
  -> sequential core LLR write port
  -> posterior banks[LANES][FULL_N/LANES]
  -> grouped layered normalized min-sum updates
  -> hard_full[2559:0]
  -> syndrome checks after load and after each iteration
  -> decoded_bits[1023:0]
  -> 40-word AXI status/result frame
```

The PYNQ-Z2 integration instantiates this same FPGA-facing top behind AXI DMA.
It does not replace the decoder core or change the supported CCSDS mode.

## Decoding Algorithm

The decoder is a partially parallel layered normalized min-sum decoder. The
default build uses `LANES=8`; `LANES=1` and `LANES=16` are also generated and
RTL-regression-tested.

For each check-row edge:

```text
q_mj       = L_j - R_mj_old
selected  = min2 if edge is min1 else min1
scaled    = floor(selected * 3 / 4)
R_mj_new  = sign_excluding_edge ? -scaled : scaled
L_j_new   = q_mj + R_mj_new
```

Only 3/4 normalization is implemented. Equal-minimum tie behavior preserves the
first minimum index; later equal values may become the second minimum.

## Storage

Posterior storage is inferred inside `ldpc_decoder_top` as `LANES` synchronous
banks. The bank map is:

```text
bank = variable % LANES
addr = variable / LANES
```

Check messages are stored as one row-message bank per lane. Each row message is
packed as six signed 8-bit values. Degree-3 rows zero the inactive slots.

The hard-decision vector `hard_full[2559:0]` is a register vector updated during
LLR load, punctured initialization, and layered writeback. It lets syndrome
checks read all row bits without random RAM reads.

## Schedule

`scripts/gen_parallel_schedule.py` validates the supported lane counts and
generates `rtl/ldpc_schedule_pkg.sv` plus reports in `vectors/schedule/`.

For the fixed graph, consecutive ascending row groups are conflict-free for
`LANES=1`, `LANES=8`, and `LANES=16` under the modulo posterior bank map:

```text
row = group * LANES + lane
```

The edge ordering remains the generated `ar4ja_1024_pkg::row_col(row, edge)`
order.

## Control Flow

The core states are:

```text
S_IDLE
S_INIT_PUNCTURED
S_CLEAR_CHECK_MESSAGES
S_INITIAL_SYNDROME
S_GROUP_MESSAGE_READ
S_GROUP_MESSAGE_CAPTURE
S_GROUP_EDGE_READ_REQUEST
S_GROUP_EDGE_READ_CAPTURE
S_GROUP_COMPUTE
S_GROUP_EDGE_WRITE
S_GROUP_MESSAGE_WRITE
S_ITERATION_SYNDROME
S_FINALIZE_OUTPUT
S_DONE
```

The read request/capture split models synchronous posterior and message RAM
latency. Message RAMs are cleared per frame; posterior RAMs are fully
initialized by the 2048 transmitted LLR writes plus the punctured-variable
initialization pass.

## Fixed-Point Behavior

- Input LLR width: signed 8 bits
- Check-message width: signed 8 bits
- Positive posterior means hard bit 0
- Negative posterior means hard bit 1
- Zero ties to hard bit 0
- Message and posterior clipping use signed 8-bit saturation
- Saturation count increments only when clipping changes the mathematical value

## Syndrome And Iterations

An initial syndrome check runs before any iteration. If it passes, the decoder
reports success with `iterations_used=0`.

After each full layered iteration, syndrome is checked again. If it passes,
decoding succeeds and terminates early. If `MAX_ITERS` completes without a
passing syndrome, `decoder_fail` is asserted.

## Known Limits

- Fixed CCSDS rate-1/2, k=1024 mode only
- No RTL encoder
- No multi-rate or runtime graph configuration
- Vendor synthesis, RAM inference, timing, and utilization are still pending
- Board-level DMA, clocking, reset, and physical validation are pending
