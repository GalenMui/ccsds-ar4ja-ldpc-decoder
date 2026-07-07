#!/usr/bin/env bash
# scripts/run_vivado_synth_pynq_z2.sh
# Stage 2: synthesis of the PYNQ-Z2 board top (pynq_z2_top) with board XDC.
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
LOG="reports/vivado/synth_pynq_z2.log"

echo "== Vivado PYNQ-Z2 board top synthesis (part=$PART) =="
vivado -mode batch -nojournal -notrace -log "$LOG" \
    -source scripts/vivado/synth_pynq_z2_top.tcl -tclargs "$PART"

echo "PYNQ-Z2 top synthesis finished. Log: $LOG"
