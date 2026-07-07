#!/usr/bin/env bash
# scripts/run_vivado_synth_ip.sh
# Stage 1: out-of-context synthesis of the decoder IP top (ldpc_axis_decoder_ip).
set -euo pipefail

VIVADO_SETTINGS="${VIVADO_SETTINGS:-/tools/AMD/2025.2/Vivado/settings64.sh}"
PART="${PYNQ_Z2_PART:-xc7z020clg400-1}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f "$VIVADO_SETTINGS" ]]; then
    echo "ERROR: Vivado settings not found: $VIVADO_SETTINGS" >&2
    echo "       Set VIVADO_SETTINGS=/path/to/settings64.sh" >&2
    exit 127
fi
# shellcheck disable=SC1090
source "$VIVADO_SETTINGS"

mkdir -p reports/vivado build/vivado
LOG="reports/vivado/synth_ip.log"

echo "== Vivado IP synthesis (part=$PART) =="
vivado -mode batch -nojournal -notrace -log "$LOG" \
    -source scripts/vivado/synth_ip.tcl -tclargs "$PART"

echo "IP synthesis finished. Log: $LOG"
