#!/usr/bin/env bash
# scripts/run_vivado_impl_pynq_z2.sh
# Stage 3: place & route (and optional bitstream) for the PYNQ-Z2 board top.
#
# Usage:
#   scripts/run_vivado_impl_pynq_z2.sh            # route only
#   scripts/run_vivado_impl_pynq_z2.sh bitstream  # route + bitstream (gated)
#
# Bitstream generation is refused inside the TCL unless constraints/pynq_z2.xdc
# is marked "STATUS: VERIFIED" and timing is met.
set -euo pipefail

VIVADO_SETTINGS="${VIVADO_SETTINGS:-/tools/AMD/2025.2/Vivado/settings64.sh}"
PART="${PYNQ_Z2_PART:-xc7z020clg400-1}"
MODE="${1:-route_only}"

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
LOG="reports/vivado/impl_pynq_z2.log"

echo "== Vivado PYNQ-Z2 implementation (part=$PART, mode=$MODE) =="
vivado -mode batch -nojournal -notrace -log "$LOG" \
    -source scripts/vivado/impl_pynq_z2_top.tcl -tclargs "$PART" "$MODE"

echo "PYNQ-Z2 implementation finished. Log: $LOG"
