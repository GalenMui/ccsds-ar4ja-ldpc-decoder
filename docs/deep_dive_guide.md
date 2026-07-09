# Deep Dive Guide

Use this order if you want to understand the repo from first principles before
making board- or synthesis-facing changes.

## Step 1: Understand The CCSDS Mode And Puncturing

Files to read:

- `docs/mode_spec.md`
- `models/ar4ja_matrix.py`

Core idea: this repo implements only CCSDS AR4JA rate 1/2 with K=2, M=512,
1024 information bits, 2048 transmitted bits, 2560 full internal bits, and 512
punctured bits.

Trace:

- `K`, `M`, `INFO_N`, `TX_N`, `FULL_N`, `CHECKS`
- `PUNCTURE_SOLVE`
- `reconstruct_punctured()`

Common mistakes:

- Treating the final 512 punctured bits as transmitted zeros.
- Forgetting that the decoder graph still has 2560 variables.
- Mixing up CCSDS K with information length k.

Test:

```sh
python3 scripts/print_matrix_stats.py
python3 scripts/run_phase1_phase3_tests.py
```

## Step 2: Inspect The Python Matrix Construction

Files to read:

- `models/ar4ja_matrix.py`
- `scripts/gen_syndrome_rom.py`

Core idea: Python constructs H from the CCSDS block matrix, phi/theta tables,
and permutation formula, then emits RTL graph lookup functions.

Trace:

- `_TABLE_7_3`
- `_TABLE_7_4`
- `theta()`
- `phi()`
- `permutation()`
- `build_h_full_sparse()`

Common mistakes:

- Using the wrong phi tuple entry for M=512.
- Off-by-one indexing in `pi_k(i)`.
- Forgetting GF(2) duplicate cancellation.

Test:

```sh
python3 -m pytest tests/test_ar4ja_matrix.py
python3 scripts/gen_syndrome_rom.py
```

If `pytest` is unavailable, use:

```sh
python3 scripts/run_phase1_phase3_tests.py
```

## Step 3: Inspect Encoder And Syndrome Behavior

Files to read:

- `models/ldpc_encoder.py`
- `rtl/syndrome_checker.sv`
- `sim/tb_syndrome_checker.sv`
- `vectors/syndrome/syndrome_vectors.txt`

Core idea: the encoder produces a valid 2560-bit full word and transmits the
first 2048 bits; the syndrome checker reconstructs the punctured block before
checking all 1536 rows.

Trace:

- `encode_full()`
- `encode()`
- `_solve_p2()`
- `syndrome_transmitted()`
- `puncture_col()`

Common mistakes:

- Checking only the first 1024 syndrome rows.
- Packing text vectors differently from RTL hex memory vectors.
- Treating p2 reconstruction as an encoder substitute.

Test:

```sh
python3 scripts/gen_vectors.py
iverilog -g2012 -o sim/build/syndrome_checker.vvp rtl/ar4ja_1024_pkg.sv rtl/syndrome_checker.sv sim/tb_syndrome_checker.sv
vvp sim/build/syndrome_checker.vvp
```

## Step 4: Inspect Fixed-Point Arithmetic

Files to read:

- `models/llr_quant.py`
- `models/bpsk_awgn.py`
- `models/ldpc_decoder_fixed.py`
- `rtl/ldpc_decoder_top.sv`

Core idea: positive LLR means bit 0, negative means bit 1, zero ties to bit 0,
and messages saturate to the signed 8-bit range by default.

Trace:

- `signed_limits()`
- `quantize_llr()`
- `hard_decision_from_llr()`
- `_clip_with_count()`
- `clip_msg()` in RTL
- `saturation_count`

Common mistakes:

- Reversing LLR sign.
- Using Python unlimited integer sums without matching RTL saturation.
- Forgetting that saturation count is part of the golden vector comparison.

Test:

```sh
python3 scripts/run_phase1_phase3_tests.py
python3 scripts/check_decoder_output.py
```

## Step 5: Inspect Decoder Scheduling

Files to read:

- `models/ldpc_decoder_fixed.py`
- `rtl/ldpc_decoder_top.sv`
- `sim/tb_ldpc_decoder_top.sv`

Core idea: the RTL follows the Python generated schedule at frame-output level:
sequential AXI load, bank-parallel punctured initialization, lane-banked
message fetch, one posterior edge phase per group, immediate layered writeback,
syndrome group check, and early termination.

Trace:

- `S_INIT_PUNCTURED`
- `S_CLEAR_CHECK_MESSAGES`
- `S_INITIAL_SYNDROME`
- `S_GROUP_MESSAGE_READ`
- `S_GROUP_EDGE_READ_CAPTURE`
- `S_GROUP_EDGE_WRITE`
- `S_ITERATION_SYNDROME`
- `iterations_used`
- `cycles_elapsed`

Common mistakes:

- Incrementing iteration count before/after the wrong check.
- Comparing transmitted syndrome instead of full internal hard-decision
  syndrome inside the decoder.
- Forgetting that later rows in the same iteration must observe updated
  posterior values.

Test:

```sh
python3 scripts/gen_decoder_vectors.py
iverilog -g2012 -o sim/build/ldpc_decoder_top.vvp rtl/ar4ja_1024_pkg.sv rtl/posterior_memory.sv rtl/message_memory.sv rtl/ldpc_decoder_top.sv sim/tb_ldpc_decoder_top.sv
vvp sim/build/ldpc_decoder_top.vvp
```

## Step 6: Inspect Message Memory Indexing

Files to read:

- `rtl/ar4ja_1024_pkg.sv`
- `scripts/gen_syndrome_rom.py`
- `rtl/ldpc_decoder_top.sv`
- `rtl/message_memory.sv`

Core idea: check messages are stored as one packed word per row per processing
lane. The active schedule group reads up to `LANES` packed rows, unpacks six
local registers per lane, updates them, and writes the group back.

Trace:

- `row_weight()`
- `row_col()`
- `ldpc_schedule_pkg::schedule_lanes_supported()`
- modulo posterior bank map
- lane-banked packed row messages
- lane-local `q` and `R_mj_new` registers

Common mistakes:

- Assuming local edge index equals column degree index.
- Reordering row columns without regenerating vectors and package.
- Running stale `rtl/ar4ja_1024_pkg.sv`.
- Claiming a new `LANES` value without adding schedule validation and RTL tests.

Test:

```sh
make generate
make test
```

## Step 7: Inspect RTL Against Python Vectors

Files to read:

- `scripts/gen_decoder_vectors.py`
- `scripts/inspect_decoder_vector.py`
- `sim/tb_ldpc_decoder_top.sv`

Core idea: the RTL decoder is checked against deterministic fixed-point Python
outputs for public frame results.

Trace:

- `payload_expected.mem`
- `success.mem`
- `syndrome_pass.mem`
- `iterations.mem`
- `saturation.mem`
- `cycle_min.mem`
- `cycle_max.mem`

Common mistakes:

- Updating Python model behavior without regenerating vectors.
- Comparing only decoded bits and ignoring failure/status counters.
- Letting cycle bounds become too tight for harmless scheduling edits.

Test:

```sh
python3 scripts/inspect_decoder_vector.py --list
python3 scripts/inspect_decoder_vector.py 10
make test
```

## Step 8: Inspect AXI Wrapper Framing

Files to read:

- `rtl/ldpc_axis_wrapper.sv`
- `sim/tb_ldpc_axis_wrapper.sv`
- `rtl/ldpc_axis_decoder_ip.sv`

Core idea: the wrapper accepts exactly 512 full-keep 32-bit input words and
emits exactly 40 full-keep 32-bit output words with status and decoded payload.

Trace:

- `W_IDLE`
- `W_UNPACK`
- `W_START`
- `W_DECODE`
- `W_OUTPUT`
- `W_DRAIN`
- `s_axis_tready`
- `s_axis_tkeep`
- `m_axis_tvalid`
- `m_axis_tkeep`
- `m_axis_tlast`
- `early_tlast_error`
- `missing_tlast_error`
- `tkeep_error`

Common mistakes:

- Racing testbench valid/ready on the same clock edge.
- Asserting `tlast` before word 511.
- Consuming output words without honoring backpressure.

Test:

```sh
iverilog -g2012 -o sim/build/ldpc_axis_wrapper.vvp rtl/ar4ja_1024_pkg.sv rtl/ldpc_schedule_pkg.sv rtl/posterior_memory.sv rtl/message_memory.sv rtl/ldpc_decoder_top.sv rtl/ldpc_axis_wrapper.sv sim/tb_ldpc_axis_wrapper.sv
vvp sim/build/ldpc_axis_wrapper.vvp
```

## Step 9: Inspect Performance Scripts

Files to read:

- `scripts/run_ber_fer.py`
- `scripts/summarize_results.py`
- `scripts/plot_ber_fer.py`
- `scripts/parse_synthesis_reports.py`
- `docs/results.md`

Core idea: current BER/FER is a deterministic smoke path, not a performance
claim. Synthesis parsing reports missing data until real reports exist.

Trace:

- `--frames`
- `--ebn0`
- `llr_scale`
- `avg_iterations`
- `decoder_failure_rate`

Common mistakes:

- Treating one-frame smoke output as a performance curve.
- Quoting 100 MHz estimates as measured timing.
- Assuming plot generation works when local matplotlib is broken.

Test:

```sh
python3 scripts/run_ber_fer.py --frames 1 --ebn0 2.0
python3 scripts/summarize_results.py
python3 scripts/parse_synthesis_reports.py
```

## Step 10: Identify Changes Before Board Bringup

Files to read:

- `docs/repo_status.md`
- `docs/results.md`
- `rtl/ldpc_decoder_top.sv`
- `rtl/ldpc_axis_wrapper.sv`

Core idea: board bringup can use the current AXI wrapper and synthesis
templates, but real board work still waits on vendor synthesis/timing and a
selected DMA shell.

Questions to answer:

- Did Vivado infer posterior and check-message storage as RAM?
- What clock target is realistic after synthesis?
- What AXI shell, DMA, or software contract will consume the wrapper frame?
- What BER/FER operating points matter?
- Which internal traces should be exposed for debug?

Test:

```sh
make test
make clean
```
