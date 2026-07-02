# Phase 1-3 Status

## Files Created Or Modified

- `models/ar4ja_matrix.py`
- `models/ldpc_encoder.py`
- `models/llr_quant.py`
- `models/bpsk_awgn.py`
- `models/ldpc_decoder_float.py`
- `models/ldpc_decoder_fixed.py`
- `models/__init__.py`
- `tests/test_ar4ja_matrix.py`
- `tests/test_ldpc_encoder.py`
- `tests/test_ldpc_fixed.py`
- `tests/test_vector_generation.py`
- `scripts/gen_vectors.py`
- `scripts/gen_syndrome_rom.py`
- `scripts/run_phase1_phase3_tests.py`
- `rtl/ar4ja_1024_pkg.sv`
- `rtl/syndrome_checker.sv`
- `sim/tb_syndrome_checker.sv`
- `vectors/syndrome/*`
- `docs/mode_spec.md`
- `docs/phase1_3_status.md`
- `Makefile`

## Tests Run

Command:

```sh
python3 scripts/run_phase1_phase3_tests.py
```

Result:

```text
PASS python unit tests
PASS generate vectors
PASS generate rtl package
PASS build syndrome simulation
PASS run syndrome simulation
```

Details from this environment:

- `pytest` is not importable under `/usr/bin/python3`, so the phase runner used
  its local assert-based fallback for the pytest-style test functions.
- Fallback Python unit tests: 18 passed, 0 failed.
- RTL simulation: 5 generated vectors passed.
- Direct `python3 -m pytest tests` currently fails with `No module named pytest`;
  after installing `requirements.txt`, the same tests can be run directly with
  pytest.

Standalone RTL commands exercised by the runner:

```sh
python3 scripts/gen_vectors.py
python3 scripts/gen_syndrome_rom.py
iverilog -g2012 -o sim/build/syndrome_checker.vvp rtl/ar4ja_1024_pkg.sv rtl/syndrome_checker.sv sim/tb_syndrome_checker.sv
vvp sim/build/syndrome_checker.vvp
```

## Assumptions

- The matrix values are from CCSDS 131.0-B-5 printed pages 7-7 through 7-10.
- For M = 512, phi values use the third entry in each CCSDS tuple.
- Python index 0 and RTL bit 0 both represent CCSDS Bit 0.
- The transmitted-codeword syndrome policy is `solve_from_third_check_block`.
  It reconstructs punctured bits from the third check block and does not assume
  punctured bits are zero.

## Blockers

No implementation blocker remains for the requested Phase 1 through Phase 3
scope. The only local environment gap is missing `pytest`; the integrated runner
works around this, and direct pytest use requires installing the Python
requirements.

## Phase Completion

- Phase 1: complete for the requested fixed CCSDS AR4JA rate-1/2, k=1024 mode.
- Phase 2: complete for deterministic fixed-point/channel/golden-model scope.
- Phase 3: complete for generated-constant RTL syndrome checker and simulation.
