# Synthesis Memory & Feasibility Analysis (XC7Z020 / PYNQ-Z2)

Status date: 2026-07-11. Tool: Vivado 2025.2, part `xc7z020clg400-1`, OOC.

This report documents why top-level synthesis of `ldpc_axis_decoder_ip` previously
stalled for hours near out-of-memory, what the current RTL actually does, the
targeted experiments run to confirm it, and the one remaining feasibility risk.

## TL;DR

* The historical stall (documented in `docs/SYNTHESIS.md`, log
  `reports/vivado/synth_ip.log`) was caused by the **old 3-D unpacked memory
  arrays** `posterior_mem[P][DEPTH]` / `message_mem[P][GROUPS]` being inferred as
  **~94 000 flip-flops** (`Synth 8-11357 "3D-RAM ... with 20480/73728 registers"`,
  `8-7186 ram_style ignored`). That RTL no longer exists.
* Commit `9e200af` ("doc update synth stall") **replaced those arrays with P
  independent single-port `bank_mem` generate blocks + a per-lane crossbar**.
  This banked RTL had **never been synthesized** — the stale log predates it.
* Targeted OOC experiments confirm the banked RTL now infers **block RAM with
  zero flip-flops for storage** (Gate A + Gate B), and the integrated decoder
  core reproduces this with **zero `8-11357`/`8-7186` warnings** and a **3.25 GB**
  peak through RTL optimization (Gate C), versus the old 10.9 GB.
* Capping `general.maxThreads` (2) keeps the *Cross Boundary and Area
  Optimization* workers bounded so synthesis **runs to completion** (~28 min,
  ≤ 7.96 GB) instead of thrashing to OOM.
* **A LUT-fit blocker was then surfaced by the completing run** — the flat
  2560-bit `hard_full` hard-decision register's wide variable-index mux cones
  drove **104 072 LUTs-as-logic = 196 % of the XC7Z020** (BRAM 8.6 %, DSP 0 %,
  FF 5.3 %). **This has now been fixed in RTL** (see "Implemented fix"): `hard_full`
  was removed because it is a redundant shadow of the posterior-bank sign bit;
  the syndrome check and output read now read those sign bits serially from the
  banked posterior RAM. Functionally verified (all vectors, LANES 1/8/16 + AXI).
  Re-synthesis LUT numbers below.
* (Historical detail of the LUT blocker, before the fix:) the LUTs were dominated
  by the flat 2560-bit `hard_full` register's wide variable-index mux trees and
  the on-the-fly `row_col` connectivity — these combinational cones were shrunk by
  eliminating the register (bank the
  hard-decision store / ROM the adjacency / incremental syndrome). See
  "Required next step".

## Synthesized hierarchy (LANES = 8)

```
ldpc_axis_decoder_ip            (rtl/ldpc_axis_decoder_ip.sv)  -- synthesis top
└─ ldpc_axis_wrapper            (rtl/ldpc_axis_wrapper.sv)     -- AXI4-Stream framing
   └─ ldpc_decoder_top          (rtl/ldpc_decoder_top.sv)      -- decoder core + storage
```
`posterior_memory.sv` / `message_memory.sv` are reference single-port templates in
the manifest but are **not instantiated** by the core; the core infers its banks
inline via the `g_posterior_banks` / `g_message_banks` generate blocks.

Config (from `ar4ja_1024_pkg`): rate-1/2 AR4JA, `INFO_N=1024`, `TX_N=2048`,
`FULL_N=2560`, `CHECKS=1536`, `MAX_ROW_WEIGHT=6`, `LLR_W=MSG_W=8`, `LANES(P)=8`.

## Storage inventory

| # | Structure | Logical dims | Total bits | Banked (P=8) | Ports/cyc | Index | Array reset | Read | Inferred (proven) |
|---|-----------|--------------|-----------:|--------------|-----------|-------|-------------|------|-------------------|
| 1 | Posterior LLR `g_posterior_banks[*].bank_mem` | 2560 × 8 | 20 480 | 8 × (320 × 8) | 1W+1R (SDP) | bank=col%8, addr=col/8 | none | sync (reg) | **8 × RAMB18E1** |
| 2 | Check→var msg `g_message_banks[*].bank_mem` | 1536 × 48 | 73 728 | 8 × (192 × 48) | 1W+1R (SDP) | bank=lane, addr=group | none | sync (reg) | **8 × RAMB18E1** |
| 3 | `hard_full` hard-decision vector | 2560 × 1 | 2 560 | — | multi var R/W | bit / word index | sync `'0` | comb (bit) | 2560 FF + muxes (correct as reg) |
| 4 | `decoded_bits` output | 1024 × 1 | 1 024 | — | word W, word R | word index | sync `'0` | — | 1024 FF |
| 5 | Per-lane working regs (`lane_col/bank/addr/old_msg/new_msg/q/mag/sign`) | P×6 each | few k | — | — | loop-unrolled | sync | — | pipeline FFs |
| 6 | AXI `out_bits` / holds | 1024 + 32 | ~1 k | — | — | — | sync | — | FFs |

**Adjacency tables** (`row_col`, `row_weight`, `perm_col`, `phi512`, …) are pure
combinational functions in `ar4ja_1024_pkg`, **not stored memories**. They are
evaluated on the fly; see the remaining-risk section.

Total inferred block RAM: **16 × RAMB18E1 = 8 BRAM tiles** of the 140 on the
XC7Z020 (**~5.7 %**) — comfortable headroom.

## Why the old RTL exploded (root cause, now historical)

`ldpc_decoder_top.sv` (pre-`9e200af`, line 85–86) declared:
```systemverilog
(* ram_style="block" *) logic signed [LLR_W-1:0] posterior_mem [0:P-1][0:BANK_DEPTH-1];
(* ram_style="block" *) logic        [ROW_MSG_W-1:0] message_mem  [0:P-1][0:GROUPS-1];
```
and wrote/read them with per-lane **variable bank indices inside the sequential
process** (`posterior_mem[posterior_bank(col)][addr] <= …` for all P lanes each
cycle). A 2-D array written at `[variable][variable]` from one clocked process is
not a Vivado RAM template, so it flattened to a flip-flop array with a full
address-decode mux tree → `8-7186` (ram_style ignored) + `8-11357` (3D-RAM with
20480 / 73728 registers). ~94 k FFs plus their mux cones is what made
*Cross Boundary and Area Optimization* run 1.5 h at 10.9 GB and never finish.

## The fix already in the tree (commit `9e200af`)

Storage is now **P physically-separate single-port banks**, each a canonical
Vivado synchronous-RAM template:
```systemverilog
for (gp = 0; gp < P; gp++) begin : g_posterior_banks
    (* ram_style = "block" *) logic signed [LLR_W-1:0] bank_mem [0:BANK_DEPTH-1];
    always_ff @(posedge clk) begin
        if (pmem_we[gp]) bank_mem[pmem_waddr[gp]] <= pmem_wdata[gp];
        if (pmem_re[gp]) posterior_read_data[gp]  <= bank_mem[pmem_raddr[gp]];
    end
end
```
Two combinational crossbars (`pmem_*`, `mmem_*`) route each active lane to a
distinct bank. The layered schedule guarantees the ≤ P active lanes hit P
**distinct** banks each cycle (asserted under `LDPC_ENABLE_ASSERTS`), so every
physical bank sees ≤ 1 read and ≤ 1 write per cycle — exactly what SDP block RAM
supports. Read is registered (`*_read_data`), and the arrays are **not reset**
(they are always written before read), so nothing forces FF inference.

## Experiments (OOC, xc7z020clg400-1)

Runner: `experiments/synthesis/run_ooc.tcl`; driver `run_experiments.sh`.

| Gate | Question | Top | Result | RAMB18 | RAMB36 | FF (mem) | Elapsed |
|------|----------|-----|--------|-------:|-------:|---------:|--------:|
| A | Does the plain SP template infer BRAM? | `posterior_memory` (2560×8) | ✅ | 0 | 1 | 0 | 20 s |
| A | " | `message_memory` (1536×48) | ✅ | 0 | 3 | 0 | 16 s |
| B | Does the *verbatim inline banked* pattern infer BRAM? | `bank_experiment` (P=8) | ✅ | 8* | 0 | 0 | 15 s |
| C | Does the integrated core synth complete, bounded mem, infer BRAM? | `ldpc_decoder_top` | ✅ completes (thread-capped); ❌ LUT overflow | 8×RAMB36 + 8×RAMB18 | — | **5 597 (no 8-11357)** | ~28 min @ ≤7.96 GB (`maxThreads=2`) |

\* Gate B reports 8 RAMB18 because the harness's XOR-reduced stimulus let the
optimizer fold the (identical-address) message banks; the RAM-inference report
shows **all 16** banks recognized as `RAM_SDP`/BLOCK (`192×48`, `320×8`) with 0
FF/0 LUTRAM. In the real core the message banks carry distinct per-lane data and
are retained. Gate A independently proves the message template → block RAM.

Gate C evidence (`experiments/synthesis/results/gateC_decoder_core/synth_ABORTED_crossboundary_thrash.log`):
`Finished Synthesize … peak = 3180 MB`; `Finished RTL Optimization Phase 2 …
peak = 3253 MB`; **zero** `8-11357`/`8-7186`; register histogram shows one
2560-bit + one 1024-bit + the 12-bit adjacency regs — i.e. control/datapath FFs,
not the old 94 k-FF memory arrays.

## Remaining risk: combinational H-matrix / min-sum cones

The banked memories are solved. The residual cost is that the decoder recomputes
parity-check connectivity **combinationally** every cycle rather than reading a
stored table:

* `ldpc_decoder_top.sv:307-325` (initial/iteration syndrome): for `P*MAX_ROW_WEIGHT
  = 48` (lane,edge) pairs it evaluates `ar4ja_1024_pkg::row_col(row,edge)` (which
  calls `perm_col` → modulo/division + `phi512`/`theta_value` case) **and** uses
  each result as a variable index into the 2560-bit `hard_full` register (48 ×
  2560:1 muxes), XOR-reduced.
* `ldpc_decoder_top.sv:485-503` re-derives the same `row_col` for all 48 pairs
  when capturing a group (registered, so pipelined, but still 48 copies).

These flattened cones are what Vivado's *Cross Boundary and Area Optimization*
grinds on; with default threading it forks 7 ~0.8 GB workers → ~7.6 GB + swap on
the 12 GB host. Peak *memory of the design itself* is only ~3.3 GB.

### Mitigations
1. **Host mitigation (implemented):** cap `general.maxThreads` (2 here) so the
   optimization workers don't collectively exhaust RAM. Trades wall time for a
   bounded, completing run. Wired into the OOC scripts.
2. **RTL fix (recommended next):** precompute the row→column adjacency into a
   ROM (or accumulate the syndrome incrementally from the already-registered
   `lane_col` during the edge pass) so the syndrome states stop rebuilding 48×
   `row_col` + 48 wide `hard_full` muxes combinationally. This directly shrinks
   the cross-boundary optimization problem and improves timing. Higher functional
   risk — must be re-verified against all decoder vectors.

## Gate C baseline (BEFORE the LUT fix) — measured numbers

With `general.maxThreads 2` the decoder-core OOC synth **ran to completion** in
~28 min at **≤ 7.96 GB peak** (vs the old default-thread run that thrashed to
OOM at the identical *Start Technology Mapping* point). Measured on the original
`hard_full` RTL (`experiments/synthesis/results/gateC_decoder_core_ORIG_hardfull/`):

| Resource | Used | XC7Z020 avail | Util | Verdict |
|----------|-----:|--------------:|-----:|---------|
| Block RAM tile | 12 (8×RAMB36 + 8×RAMB18) | 140 | 8.6 % | ✅ great margin |
| DSP48E1 | 0 | 220 | 0 % | ✅ |
| Slice Registers (FF) | 5 597 | 106 400 | 5.3 % | ✅ |
| **LUT as Logic** | **104 072** | **53 200** | **195.6 %** | ❌ **did not fit** |
| MUXF7 / MUXF8 | 10 553 / 5 064 | 26 600 / 13 300 | ~39 % | ⚠ wide-mux fingerprint |

(Message banks are 48-bit-wide → each maps to a RAMB36; posterior banks are
8-bit-wide → RAMB18. That is 12 BRAM tiles, not the 8 first estimated.)

## Implemented fix — remove the `hard_full` register

**Key equivalence:** `hard_full[c]` was *always* written to exactly the sign bit
of `posterior_mem[c]` — LLR load writes `llr` / hard `llr[MSB]`; puncture writes
`0` / hard `0`; edge-write writes `posterior_clipped` / hard `posterior_clipped[MSB]`.
So `hard_full` was a **redundant shadow of the posterior-bank sign bit** and could
be deleted outright. Its only two readers were re-plumbed to read the sign bit from
the already-banked posterior RAM:

* **Syndrome check** (`S_SYN_CAPTURE` → `S_SYN_EDGE_REQ`/`S_SYN_EDGE_CAP` →
  `S_SYN_FINISH`): for each group of P rows, the per-row edge→bank/addr map is
  loaded, then P posterior sign bits are read per edge (edge *e* across the P rows
  hits P *distinct* banks — the same schedule guarantee the decode edge loop uses)
  and XOR-accumulated into per-row parities. Replaces the old single-cycle
  combinational scan of 48 × `row_col` + 48 × 2560:1 `hard_full` reads.
* **Final output** (`S_OUT_REQ`/`S_OUT_CAP`): the K_BITS info-column hard
  decisions are read P at a time from the posterior sign bits (info col *c* → bank
  *c%P*, addr *c/P*, so every bank at `addr = output_read_idx` yields P consecutive
  bits). Replaces the old word-indexed read of `hard_full`.
* **Writes:** all four `hard_full` write sites and its reset were deleted; the
  posterior-bank writes (which already carry the sign) are untouched.

This removes the flat 2560-bit register, its ~17 wide variable-index write muxes,
and the 48-way syndrome read scan. **Latency tradeoff:** the syndrome sweep grows
from 1 cycle/group to `1 + 2·degree` cycles/group and the output read from
~32 cycles to `2·K_BITS/P` cycles — a throughput reduction accepted to obtain a
placeable design (the ticket's "trade throughput for feasible resource usage").
`docs/` cycle model (`scripts/gen_decoder_vectors.py`) and `cycle_max.mem` were
updated to the new serial worst case; **all decode outputs are bit-identical.**

### Files changed by the fix
`rtl/ldpc_decoder_top.sv` (state machine + crossbar), `scripts/gen_decoder_vectors.py`
(cycle_max model), `vectors/decoder/cycle_max.mem` (regenerated).

### Post-fix re-synthesis (decoder core, measured)

`experiments/synthesis/results/gateC_decoder_core/`, same OOC flow / part:

| Resource | Before fix | After fix | XC7Z020 | Util after |
|----------|-----------:|----------:|--------:|-----------:|
| **LUT as Logic** | 104 072 | **7 990** | 53 200 | **15.0 %** ✅ |
| MUXF7 / MUXF8 | 10 553 / 5 064 | **8 / 0** | 26 600 / 13 300 | ~0 % ✅ |
| Register (FF) | 5 597 | **3 002** | 106 400 | 2.8 % ✅ |
| Block RAM tile | 12 | **12** (8×RAMB36 + 8×RAMB18) | 140 | 8.6 % ✅ |
| DSP48E1 | 0 | **0** | 220 | 0 % ✅ |
| Synth time / peak RSS | ~28 min / 7.96 GB | **~2 min / 2.23 GB** | — | — |

**~11× fewer LUTs** (196 % → 15 %); the FF drop of ~2 600 is the deleted 2560-bit
`hard_full` register; the wide-mux fingerprint (F7/F8) is essentially gone. Cross-
Boundary/Area Optimization no longer thrashes (RTL-opt fell from ~13 min to 27 s),
so the thread cap is now only a safety belt, not a necessity.

## Gate D — full IP top synth with 100 MHz clock (measured)

`synth_design -top ldpc_axis_decoder_ip` + `fpga/constraints/ldpc_axis_decoder.xdc`
(100 MHz on `aclk`), OOC, `maxThreads 2`. `reports/vivado/gateD_ip/`.

| Resource | Used | XC7Z020 | Util |
|----------|-----:|--------:|-----:|
| Block RAM tile | 12 (8×RAMB36 + 8×RAMB18) | 140 | 8.6 % ✅ |
| DSP48E1 | 0 | 220 | 0 % ✅ |
| Register (FF) | 4 232 | 106 400 | 4.0 % ✅ |
| LUT | 10 729 | 53 200 | 20 % ✅ |
| **Setup WNS** | **−57.8 ns** | (10 ns period) | ❌ **timing fails** |

Full synthesis completes in ~3.5 min at ~2.7 GB. **Area fit is excellent, but
timing at 100 MHz is badly missed.** Worst path: `lane_min1_idx_reg` →
`saturation_count_reg[31]`, **102 logic levels / 45 CARRY4, 30 ns of pure logic**
(placement cannot fix 102 levels in a 10 ns window). Root cause: `saturation_count`
is accumulated as `+32'd1` **per edge across P·MAX_ROW_WEIGHT = 48 conditional
32-bit adds** every group — a diagnostic counter, not on the decode datapath.

## Feasibility verdict

* **Memory architecture: solved and proven.** 12 BRAM tiles, 0 memory-FF, no
  ignored `ram_style`. A defensible, BRAM-backed storage design.
* **LUT overflow: FIXED.** Removing the redundant `hard_full` register cut LUT-as-
  logic to **15–20 % of the XC7Z020**. The design fits with large margin on every
  area axis and has ample place-and-route headroom.
* **Timing: NOT yet closed.** WNS −57.8 ns at 100 MHz, dominated by the wide
  `saturation_count` adder chain (remediation item #4 below). This is the next
  required fix; it is small and behaviour-preserving (the counter *value* is
  unchanged — only the accumulation width/structure).

### Where the LUTs go (from the RTL component report, `synth.log`)

* `Muxes: 2 Input 2560 Bit := 19` and `15 Input 2560 Bit := 1` — the flat
  **2560-bit `hard_full` register** with ~19 variable-indexed / state-selected
  wide write paths (LLR load, 8 puncture lanes, 8 edge-write lanes) plus its
  syndrome read-out. Wide muxing over a 2560-bit vector is the single largest
  LUT consumer (order ~40–50 k LUTs).
* Hundreds of small muxes (`2 Input 8 Bit := 419`, `12 Bit := 176`, `9 Bit :=
  177`, …) — the per-lane min-sum edge selection and the on-the-fly
  `row_col`/`perm_col` connectivity replicated across `P*MAX_ROW_WEIGHT`.
* `Adders: 32 Bit := 91` — the `saturation_count` accumulation is done as a wide
  32-bit add per edge (48 conditional 32-bit adds) instead of a small local count
  widened once.

## Remediation status & next steps

1. **Bank/serialise the hard-decision store — ✅ DONE (this change).** The flat
   2560-bit `hard_full` register was removed as a redundant shadow of the
   posterior-bank sign bit; the syndrome and output readers were serialised over
   the banked posterior read port. LUT-as-logic 104 072 → 7 990. Verified.
2. **Narrow `saturation_count` accumulation — NEXT (timing).** Currently a chain of
   48 conditional 32-bit adds/group ⇒ the −57.8 ns critical path. Compute a small
   local per-group count (≤48 ⇒ 6 bits) and add it to the 32-bit total once. The
   counter value is unchanged, so it is behaviour-preserving; expected to remove
   the dominant critical path. **Small, low-risk — the recommended next fix.**
3. **Pipeline the min-sum / connectivity path if timing still misses** after (2)
   (register `row_col`/`perm_col` outputs; split the min-sum select). Medium risk.
4. **(Optional) ROM the row→column adjacency** to further trim `perm_col`
   arithmetic and improve timing/area margin.

Every RTL change must be re-verified against all decoder vectors (LANES = 1/8/16)
and the AXI framing tests, then re-synthesised for area **and timing**.
