# Recipes below `source` Vivado's settings64.sh, which uses the bash-only
# `source` builtin.  Force bash so `make vivado-*` works on systems where
# /bin/sh is dash (e.g. Ubuntu).
SHELL := /bin/bash

PYTHON ?= python3
VIVADO ?= vivado
FPGA_PART ?=
PYNQ_Z2_PART ?= xc7z020clg400-1
PYNQ_Z2_CLK_MHZ ?= 100.0
PYNQ_Z2_LANES ?= 8
PYNQ_Z2_JOBS ?= 4
PYNQ_Z2_OVERLAY_DIR ?= build/pynq_z2/deploy

VIVADO_SETTINGS ?= /tools/AMD/2025.2/Vivado/settings64.sh

BENCH_RESULTS ?= results/hardware/ber_fer.jsonl

.PHONY: help generate test phase1_3 phase4_6 regression lint synth impl package-ip \
	pynq-z2-project pynq-z2-synth pynq-z2-bitstream pynq-z2-overlay \
	pynq-z2-package clean \
	benchmark-selftest pynq-z2-benchmark-cmds pynq-z2-analyze \
	vivado-smoke vivado-synth-ip vivado-synth-pynq-z2 vivado-impl-pynq-z2 \
	vivado-bitstream clean-vivado

help:
	@echo "Available targets:"
	@echo "  make generate  - regenerate checked-in graph, schedule, and vector artifacts"
	@echo "  make test      - run the full open-source regression"
	@echo "  make phase1_3  - run Phase 1/3 Python and RTL checks"
	@echo "  make phase4_6  - run the full repository regression"
	@echo "  make regression - run the full repository regression"
	@echo "  make lint      - run open-source RTL elaboration/lint checks"
	@echo "  make synth FPGA_PART=<part>      - run Vivado OOC synthesis"
	@echo "  make impl FPGA_PART=<part>       - run Vivado OOC implementation"
	@echo "  make package-ip FPGA_PART=<part> - package the AXI-Stream IP"
	@echo "  make pynq-z2-project   - create and validate the PYNQ-Z2 Vivado project"
	@echo "  make pynq-z2-synth     - run PYNQ-Z2 project synthesis"
	@echo "  make pynq-z2-bitstream - implement and generate the PYNQ-Z2 bitstream"
	@echo "  make pynq-z2-overlay   - package .bit/.hwh and PYNQ Python files"
	@echo "  --- hardware benchmark suite ---"
	@echo "  make benchmark-selftest      - offline harness self-check (software model)"
	@echo "  make pynq-z2-benchmark-cmds  - print exact board benchmark commands"
	@echo "  make pynq-z2-analyze BENCH_RESULTS=<jsonl> - aggregate retrieved results"
	@echo "  --- staged PYNQ-Z2 board bring-up (scripts/vivado) ---"
	@echo "  make vivado-smoke          - check Vivado + target part are available"
	@echo "  make vivado-synth-ip       - OOC synth of the decoder IP top"
	@echo "  make vivado-synth-pynq-z2  - synth of the PYNQ-Z2 board top + XDC"
	@echo "  make vivado-impl-pynq-z2   - place & route the PYNQ-Z2 board top"
	@echo "  make vivado-bitstream      - bitstream (only if XDC is VERIFIED)"
	@echo "  make clean-vivado          - remove build/vivado and reports/vivado"
	@echo "  make clean     - remove common generated files"

generate:
	$(PYTHON) scripts/gen_vectors.py
	$(PYTHON) scripts/gen_syndrome_rom.py
	$(PYTHON) scripts/gen_parallel_schedule.py
	$(PYTHON) scripts/gen_decoder_vectors.py

test: regression

phase1_3:
	$(PYTHON) scripts/run_phase1_phase3_tests.py

phase4_6:
	$(PYTHON) scripts/run_regression.py

regression:
	$(PYTHON) scripts/run_regression.py

lint: generate
	$(PYTHON) scripts/run_lint.py

synth: generate
	@if [ -z "$(FPGA_PART)" ]; then echo "ERROR: set FPGA_PART=<part>"; exit 2; fi
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/vivado_ooc/synth
	$(VIVADO) -mode batch -nojournal -log results/vivado_ooc/synth/vivado.log -source fpga/synth_ooc.tcl -tclargs $(FPGA_PART)

impl: generate
	@if [ -z "$(FPGA_PART)" ]; then echo "ERROR: set FPGA_PART=<part>"; exit 2; fi
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/vivado_ooc/impl
	$(VIVADO) -mode batch -nojournal -log results/vivado_ooc/impl/vivado.log -source fpga/impl_ooc.tcl -tclargs $(FPGA_PART)

package-ip: generate
	@if [ -z "$(FPGA_PART)" ]; then echo "ERROR: set FPGA_PART=<part>"; exit 2; fi
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/ip_repo
	$(VIVADO) -mode batch -nojournal -log results/ip_repo/package_ip.log -source fpga/package_ip.tcl -tclargs $(FPGA_PART)

pynq-z2-project: generate
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/pynq_z2/logs
	env PYNQ_Z2_PART="$(PYNQ_Z2_PART)" PYNQ_Z2_CLK_MHZ="$(PYNQ_Z2_CLK_MHZ)" PYNQ_Z2_LANES="$(PYNQ_Z2_LANES)" PYNQ_Z2_JOBS="$(PYNQ_Z2_JOBS)" \
		$(VIVADO) -mode batch -nojournal -log results/pynq_z2/logs/project.log \
		-source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs project

pynq-z2-synth: generate
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/pynq_z2/logs
	env PYNQ_Z2_PART="$(PYNQ_Z2_PART)" PYNQ_Z2_CLK_MHZ="$(PYNQ_Z2_CLK_MHZ)" PYNQ_Z2_LANES="$(PYNQ_Z2_LANES)" PYNQ_Z2_JOBS="$(PYNQ_Z2_JOBS)" \
		$(VIVADO) -mode batch -nojournal -log results/pynq_z2/logs/synth.log \
		-source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs synth

pynq-z2-bitstream: generate
	@command -v $(VIVADO) >/dev/null 2>&1 || { echo "ERROR: $(VIVADO) not found; install Vivado or set VIVADO=/path/to/vivado"; exit 127; }
	@mkdir -p results/pynq_z2/logs
	env PYNQ_Z2_PART="$(PYNQ_Z2_PART)" PYNQ_Z2_CLK_MHZ="$(PYNQ_Z2_CLK_MHZ)" PYNQ_Z2_LANES="$(PYNQ_Z2_LANES)" PYNQ_Z2_JOBS="$(PYNQ_Z2_JOBS)" \
		$(VIVADO) -mode batch -nojournal -log results/pynq_z2/logs/bitstream.log \
		-source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs bitstream

pynq-z2-package:
	$(PYTHON) boards/pynq_z2/scripts/package_overlay.py --output-dir $(PYNQ_Z2_OVERLAY_DIR)

# -----------------------------------------------------------------------------
# Hardware benchmark suite (software/pynq_z2/benchmark.py).
# `benchmark-selftest` validates the whole harness offline with the bit-accurate
# software model (source="software-model", never a hardware claim).  The real
# measurements run on the board's root Jupyter terminal; `pynq-z2-benchmark-cmds`
# prints the exact commands.  `pynq-z2-analyze` aggregates a retrieved JSONL.
# -----------------------------------------------------------------------------
benchmark-selftest:
	@mkdir -p results/selftest
	$(PYTHON) -m software.pynq_z2.benchmark ber-fer --simulate \
		--ebn0 3.5 --frames 3 --min-frames 1 \
		--output results/selftest/ber_fer.jsonl
	$(PYTHON) -m software.pynq_z2.benchmark throughput --simulate \
		--frames 3 --warmup 1 --noiseless \
		--output results/selftest/throughput.json
	$(PYTHON) scripts/plot_benchmark.py csv results/selftest/ber_fer.jsonl

pynq-z2-benchmark-cmds:
	@echo "Run from the PYNQ-Z2 root Jupyter terminal, in the deployed directory:"
	@echo "  cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder"
	@echo "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py correctness \\"
	@echo "      --output results/hardware/correctness.jsonl"
	@echo "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py ber-fer \\"
	@echo "      --ebn0 1.0 1.5 2.0 2.5 3.0 --frames 200 --max-frame-errors 60 --resume \\"
	@echo "      --output results/hardware/ber_fer.jsonl"
	@echo "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py throughput \\"
	@echo "      --frames 500 --noiseless --output results/hardware/throughput.json"
	@echo "  XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 benchmark.py soak \\"
	@echo "      --minutes 15 --checkpoint-every 500 --output results/hardware/soak.jsonl"
	@echo "Retrieve results over unprivileged SSH, then: make pynq-z2-analyze BENCH_RESULTS=<file>"

pynq-z2-analyze:
	$(PYTHON) scripts/plot_benchmark.py csv $(BENCH_RESULTS)
	@echo "For plots: $(PYTHON) scripts/plot_benchmark.py ber-fer $(BENCH_RESULTS)"

pynq-z2-overlay: pynq-z2-bitstream
	$(PYTHON) boards/pynq_z2/scripts/package_overlay.py --output-dir $(PYNQ_Z2_OVERLAY_DIR)

# -----------------------------------------------------------------------------
# Staged PYNQ-Z2 board bring-up (scripts/vivado/*.tcl + shell wrappers).
# These use the committed, self-contained RTL packages directly and do not
# depend on `generate`.  They source Vivado from $(VIVADO_SETTINGS).
# -----------------------------------------------------------------------------
vivado-smoke:
	@test -f "$(VIVADO_SETTINGS)" || { echo "ERROR: $(VIVADO_SETTINGS) not found; set VIVADO_SETTINGS="; exit 127; }
	@mkdir -p reports/vivado
	. "$(VIVADO_SETTINGS)" && vivado -mode batch -nojournal -notrace \
		-log reports/vivado/smoke.log -source scripts/vivado/smoke.tcl

vivado-synth-ip:
	PYNQ_Z2_PART="$(PYNQ_Z2_PART)" VIVADO_SETTINGS="$(VIVADO_SETTINGS)" scripts/run_vivado_synth_ip.sh

vivado-synth-pynq-z2:
	PYNQ_Z2_PART="$(PYNQ_Z2_PART)" VIVADO_SETTINGS="$(VIVADO_SETTINGS)" scripts/run_vivado_synth_pynq_z2.sh

vivado-impl-pynq-z2: vivado-synth-pynq-z2
	PYNQ_Z2_PART="$(PYNQ_Z2_PART)" VIVADO_SETTINGS="$(VIVADO_SETTINGS)" scripts/run_vivado_impl_pynq_z2.sh route_only

# Bitstream is intentionally gated: impl_pynq_z2_top.tcl refuses to write a
# bitstream unless constraints/pynq_z2.xdc is marked "STATUS: VERIFIED" and
# timing is met.
vivado-bitstream: vivado-synth-pynq-z2
	PYNQ_Z2_PART="$(PYNQ_Z2_PART)" VIVADO_SETTINGS="$(VIVADO_SETTINGS)" scripts/run_vivado_impl_pynq_z2.sh bitstream

clean-vivado:
	@rm -rf build/vivado reports/vivado .Xil
	@echo "Cleaned build/vivado and reports/vivado."

clean:
	@rm -rf .pytest_cache __pycache__ htmlcov
	@rm -rf sim_build sim/build work obj_dir csrc
	@rm -f *.vcd *.fst *.fsdb *.ghw *.wdb *.log *.out *.err
	@rm -rf results/vivado_ooc results/ip_repo results/pynq_z2
	@echo "Cleaned common generated files."
