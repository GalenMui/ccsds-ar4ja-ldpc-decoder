# Repository Status

| Area | Status | Evidence | Command to verify | Known risk | Next action |
| --- | --- | --- | --- | --- | --- |
| CCSDS matrix | complete | `models/ar4ja_matrix.py` builds the fixed rate-1/2 H from CCSDS theta/phi tables; dimensions are tested. | `python3 scripts/print_matrix_stats.py` | Human audit of every copied table value is still needed. | Compare `_TABLE_7_3` and `_TABLE_7_4` against CCSDS 131.0-B-5 pages 7-9 and 7-10. |
| Encoder | complete | `models/ldpc_encoder.py` systematic encoder produces full words with zero syndrome and transmitted 2048-bit words. | `python3 scripts/run_phase1_phase3_tests.py` | Python only; no RTL encoder exists. | Keep as golden generator or add RTL encoder only if needed. |
| Fixed-point model | complete | `models/ldpc_decoder_fixed.py` generates deterministic decoder vectors with saturation and iteration counts. | `python3 scripts/check_decoder_output.py` | Not a statistically validated performance model. | Add more channel cases and internal trace dumps if changing RTL schedule. |
| Syndrome checker RTL | complete | `rtl/syndrome_checker.sv` passes 5 Python-generated vectors. | `python3 scripts/run_phase1_phase3_tests.py` | Combinational implementation may be large after synthesis. | Synthesize and decide whether to pipeline or serialize. |
| Decoder core RTL | simulation-complete for baseline | `rtl/ldpc_decoder_top.sv` is a row-serial layered decoder with posterior RAM and row-packed message RAM; it passes 11 fixed-point Python vectors. | `python3 scripts/run_regression.py` | Vendor synthesis/timing and RAM inference are not yet measured. | Run Vivado OOC synthesis and inspect memory/timing reports. |
| AXI wrapper | simulation-complete for current ABI | `rtl/ldpc_axis_wrapper.sv` passes normal, stalled, sequential, early-TLAST, missing-TLAST drain, and malformed-then-valid tests. | `python3 scripts/run_regression.py` | Simulation only; no real DMA integration yet. | Integrate `ldpc_axis_decoder_ip` with AXI DMA on selected hardware. |
| Unit tests | complete | Pytest-style tests pass under fallback runner. | `python3 scripts/run_phase1_phase3_tests.py` | Direct pytest requires installed dependency. | Use `python3 -m pip install -r requirements.txt` for direct pytest. |
| Simulation tests | complete for current scope | Syndrome, decoder, and AXI Icarus simulations pass. | `python3 scripts/run_regression.py` | Icarus passing is not synthesis or formal proof. | Add internal-message and post-synthesis checks. |
| BER/FER scripts | partial | One-frame smoke CSV and summary run. | `python3 scripts/run_ber_fer.py --frames 1 --ebn0 2.0` | Smoke result is not a performance curve. | Run longer sweeps after model/RTL confidence improves. |
| Synthesis reports | scaffolded, not measured | Vivado Tcl and XDC templates exist; local Yosys cannot parse the generated SV package. | `yosys -q -l results/reports/yosys_synth.log fpga/yosys_synth.ys` | No real resource/timing data exists. | Run Vivado with a selected FPGA part. |
| Documentation | updated for layered core | README plus architecture, AXI, verification, results, and bring-up docs exist. | `ls docs` | Docs can drift after RTL changes. | Update docs in the same commit as design changes. |
| Board bringup readiness | prepared for integration | `rtl/ldpc_axis_decoder_ip.sv`, Vivado Tcl, XDC, DMA utility, and bring-up guide exist. | `ls fpga scripts/ldpc_dma_util.py docs/fpga_bringup.md` | No board has been selected or tested. | Select board, run synthesis, then connect AXI DMA. |

## Critical Correctness Checklist

| Check | Status | Evidence |
| --- | --- | --- |
| CCSDS matrix construction traceable to CCSDS 131.0-B-5 | pass with review caveat | Code references tables 7-3/7-4 and section 7.4; docs link the official PDF and pages. Manual table audit remains recommended. |
| No fake placeholder LDPC matrix | pass | H is built from phi/theta tables and permutation formula, not random or identity placeholders. |
| Mode consistently rate 1/2, k=1024 | pass | Constants and tests fix K=2, M=512, INFO_N=1024. |
| M=512 used correctly | pass | Phi indexing uses the third tuple entry; tests validate permutation length. |
| Full internal codeword length 2560 where required | pass | Python decoder and RTL core allocate FULL_N=2560. |
| Transmitted codeword length 2048 | pass | Encoder, vectors, wrapper input use TX_N=2048. |
| Puncturing handled explicitly | pass | `PUNCTURE_SOLVE` reconstructs final M bits for syndrome; decoder uses neutral LLRs. |
| Parity-check row count 1536 | pass | CHECKS=1536 in Python and generated RTL package. |
| LLR sign convention consistent | pass | Python tests and RTL hard decision use nonnegative -> 0, negative -> 1. |
| Fixed-point saturation consistent | pass | Python vectors include saturation counts compared by RTL decoder sim. |
| Bit ordering documented and tested | pass | `docs/mode_spec.md`, tests, and vector packers document index 0 conventions. |
| RTL decoder compares against fixed-point Python golden model | pass at public-output level | `sim/tb_ldpc_decoder_top.sv` compares generated vector outputs. |

## Personally Review Before Trusting

- Every theta/phi table entry in `models/ar4ja_matrix.py`.
- The `p2` solve in `models/ldpc_encoder.py`.
- The saturation order in `models/ldpc_decoder_fixed.py` versus `rtl/ldpc_decoder_top.sv`.
- The generated `row_col()` ordering in `rtl/ar4ja_1024_pkg.sv`.
- The AXI wrapper output contract in `rtl/ldpc_axis_wrapper.sv`.
