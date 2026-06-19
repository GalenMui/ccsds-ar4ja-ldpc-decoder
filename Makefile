PYTHON ?= python3

.PHONY: help test phase1_3 phase4_6 regression lint clean

help:
	@echo "Available targets:"
	@echo "  make test      - run Phase 1/3 Python and RTL checks"
	@echo "  make phase1_3  - run Phase 1/3 Python and RTL checks"
	@echo "  make phase4_6  - run the full repository regression"
	@echo "  make regression - run the full repository regression"
	@echo "  make lint      - report lint status"
	@echo "  make clean  - remove common generated files"

test: phase1_3

phase1_3:
	$(PYTHON) scripts/run_phase1_phase3_tests.py

phase4_6:
	$(PYTHON) scripts/run_regression.py

regression:
	$(PYTHON) scripts/run_regression.py

lint:
	@echo "Linting is not configured yet."

clean:
	@rm -rf .pytest_cache __pycache__ htmlcov
	@rm -rf sim_build sim/build work obj_dir csrc
	@rm -f *.vcd *.fst *.fsdb *.ghw *.wdb *.log *.out *.err
	@echo "Cleaned common generated files."
