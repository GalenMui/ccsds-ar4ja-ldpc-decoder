.PHONY: help test lint clean

help:
	@echo "Available targets:"
	@echo "  make test   - report test status"
	@echo "  make lint   - report lint status"
	@echo "  make clean  - remove common generated files"

test:
	@echo "Tests are not implemented yet."

lint:
	@echo "Linting is not configured yet."

clean:
	@rm -rf .pytest_cache __pycache__ htmlcov
	@rm -rf sim_build work obj_dir csrc
	@rm -f *.vcd *.fst *.fsdb *.ghw *.wdb *.log *.out *.err
	@echo "Cleaned common generated files."
