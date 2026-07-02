# Architecture

## Module Hierarchy

```text
ldpc_axis_decoder_ip
  ldpc_axis_wrapper
    ldpc_decoder_top
      posterior_memory
      message_memory
```

`rtl/syndrome_checker.sv` remains a standalone transmitted-codeword syndrome
test module. It is not instantiated by the decoder core.

## Block Diagram

```text
AXI input word
  -> word/lane unpacker
  -> sequential LLR write port
  -> posterior RAM[0..2559] ----+
                                |
row_col(row, edge) -> edge FSM  +-> q/min/sign row registers
message RAM[row][6] -----------+
                                |
                                +-> posterior writeback + hard_full update

hard_full[2559:0] -> one-row-per-cycle syndrome -> finalize 1024 decoded bits
```

## Memories

Posterior memory:

- Module: `rtl/posterior_memory.sv`
- Depth: 2560
- Width: signed 8 bits by default
- Synchronous read
- Explicit write enable
- No reset loop over memory contents

Check-message memory:

- Module: `rtl/message_memory.sv`
- Depth: 1536 rows
- Width: `6 * MSG_W`, 48 bits by default
- Synchronous read
- Explicit write enable
- Cleared one row per cycle before each frame
- Inactive degree-3 lanes are written as zero

Hard decisions:

- `hard_full[2559:0]` is a register vector.
- It updates on transmitted LLR load, punctured initialization, and posterior
  writeback.
- It lets syndrome checking read up to six bits per row without random RAM
  reads.

## Core Interface

The decoder core no longer accepts a flattened frame vector. The load interface
is sequential:

```systemverilog
llr_write_valid
llr_write_ready
llr_write_addr
llr_write_data
llr_load_clear
start
busy
done
```

`done` is a one-cycle pulse. Result fields remain stable until the next frame
load/start sequence changes them.

## Controller States

```text
S_IDLE
S_INIT_PUNCTURED
S_CLEAR_CHECK_MESSAGES
S_INITIAL_SYNDROME
S_ROW_MESSAGE_READ
S_ROW_MESSAGE_CAPTURE
S_ROW_EDGE_READ_REQUEST
S_ROW_EDGE_READ_CAPTURE
S_ROW_COMPUTE
S_ROW_EDGE_WRITE
S_ROW_MESSAGE_WRITE
S_ITERATION_SYNDROME
S_FINALIZE_OUTPUT
S_DONE
```

The read request/capture split is intentional: both posterior and check-message
RAMs are synchronous and the FSM accounts for one-cycle read latency.

## Frame Initialization

1. The wrapper writes all 2048 transmitted LLRs to posterior addresses
   `0..2047`; hard bits are updated from the sign bit.
2. `S_INIT_PUNCTURED` writes zero to posterior addresses `2048..2559` over
   512 cycles and sets their hard bits to zero.
3. `S_CLEAR_CHECK_MESSAGES` writes zero to each packed message row over
   1536 cycles.
4. `S_INITIAL_SYNDROME` checks one row per cycle.
5. If the initial syndrome passes, the core finalizes with zero iterations.

Punctured variables are not forced to zero after initialization. They are normal
posterior variables during layered decoding.

## Layered Row Processing

For one check row `m` and connected variable `j`:

```text
q_mj = L_j - R_mj_old
```

For active edges only, the row registers track:

- sign XOR
- minimum magnitude
- second minimum magnitude
- first minimum index

Tie rule: the first equal minimum keeps `min1_idx`; a later equal magnitude may
become `min2`.

For each edge:

```text
selected_min = min2 when edge == min1_idx else min1
scaled       = floor(selected_min * 3 / 4)
R_mj_new     = sign_excluding_edge ? -scaled : scaled
L_j_new      = q_mj + R_mj_new
```

`R_mj_new` saturates to `MSG_W`; `L_j_new` saturates to the posterior width.
Both Python and RTL count a saturation event only when clipping changes the
mathematical value.

## Syndrome And Iteration Semantics

The core checks one parity row per cycle by XORing at most six `hard_full` bits.
It runs an initial syndrome before iteration. After every full layered
iteration:

1. If the syndrome passes, decoding succeeds.
2. Otherwise, the next iteration starts unless `MAX_ITERS` has completed.
3. On the final failed iteration, `decoder_fail` is asserted.

`iterations_used` is the number of completed layered iterations. An initial
syndrome pass reports zero.

## Cycle Formula

For this fixed mode:

```text
initial/final overhead = 512 punctured init
                       + 1536 message clear
                       + 1536 initial syndrome
                       + 32 decoded-output pack
                       = 3616 cycles

degree-3 row = 13 cycles
degree-6 row = 22 cycles
row pass     = 512 * 13 + 1024 * 22 = 29184 cycles
iteration    = row pass + 1536 syndrome = 30720 cycles
```

Worst-case at eight iterations:

```text
3616 + 8 * 30720 = 249376 cycles
```

## Future Parallelism

The next optimization should bank posterior memory and process multiple edges
or rows per cycle. The current design keeps graph lookup, AXI framing, row
datapath, posterior storage, and message storage separated so banking can be
introduced without embedding AXI protocol logic inside the compute engine.
