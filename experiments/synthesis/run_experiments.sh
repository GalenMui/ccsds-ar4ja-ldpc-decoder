#!/usr/bin/env bash
# Drive the staged memory-inference experiments (Gate A + Gate B).
set -u
cd "$(dirname "$0")/../.." || exit 1
VIV=/tools/AMD/2025.2/Vivado/bin/vivado
PART=xc7z020clg400-1
RUN=experiments/synthesis/run_ooc.tcl
LOG=experiments/synthesis/results
mkdir -p "$LOG"

run() {  # tag top "src..."
  local tag=$1 top=$2; shift 2
  echo "### RUNNING $tag ($top) ###"
  "$VIV" -mode batch -nojournal -notrace -log "$LOG/$tag.log" -journal "$LOG/$tag.jou" \
    -source "$RUN" -tclargs "$tag" "$top" "$PART" "$@" 2>&1 | tee "$LOG/$tag.console"
}

# Gate A: plain reference single-port templates (full dims).
run gateA_posterior posterior_memory rtl/posterior_memory.sv
run gateA_message   message_memory   rtl/message_memory.sv

# Gate B: verbatim inline banked pattern from decoder_top (LANES=8 dims).
run gateB_banks bank_experiment experiments/synthesis/bank_experiment.sv

echo "### ALL EXPERIMENTS DONE ###"
grep -h "INFERENCE SUMMARY" "$LOG"/*.console 2>/dev/null || echo "no summaries found"
