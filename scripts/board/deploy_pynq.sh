#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_DIR="${PYNQ_DEPLOY_DIR:-$REPO_ROOT/build/pynq_z2/deploy}"
SSH_TARGET="${PYNQ_SSH_TARGET:-pynq}"
REMOTE_DIR="${PYNQ_REMOTE_DIR:-/home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder}"

required=(
    ccsds_ldpc_pynq_z2.bit
    ccsds_ldpc_pynq_z2.hwh
    manifest.json
    README.txt
    requirements.txt
    load_overlay.py
    smoke_test.py
    benchmark.py
    ccsds_ldpc_pynq.py
    models
)

for name in "${required[@]}"; do
    if [[ ! -e "$DEPLOY_DIR/$name" ]]; then
        echo "ERROR: required deployment artifact is missing: $DEPLOY_DIR/$name" >&2
        echo "Run: make pynq-z2-package" >&2
        exit 2
    fi
done

echo "Checking SSH connectivity to $SSH_TARGET..."
ssh "$SSH_TARGET" 'hostname && whoami && pwd'

echo "Creating isolated remote directory: $REMOTE_DIR"
ssh "$SSH_TARGET" "mkdir -p -- '$REMOTE_DIR'"

sources=()
for name in "${required[@]}"; do
    sources+=("$DEPLOY_DIR/$name")
done
scp -r "${sources[@]}" "$SSH_TARGET:$REMOTE_DIR/"

echo "Deployed PYNQ-Z2 overlay files to $SSH_TARGET:$REMOTE_DIR/"
echo "Load-only test: ssh $SSH_TARGET 'cd $REMOTE_DIR && python3 load_overlay.py'"
echo "Functional test: ssh $SSH_TARGET 'cd $REMOTE_DIR && python3 smoke_test.py'"
