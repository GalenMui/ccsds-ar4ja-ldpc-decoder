#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_DIR="${PYNQ_DEPLOY_DIR:-$REPO_ROOT/build/pynq_z2/deploy}"
SSH_TARGET="${PYNQ_SSH_TARGET:-pynq}"
REMOTE_DIR="${PYNQ_REMOTE_DIR:-/home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder}"

action=deploy
case "${1:-}" in
    "") ;;
    --load) action=load ;;
    --smoke-test) action=smoke-test ;;
    -h|--help)
        echo "Usage: $0 [--load|--smoke-test]"
        exit 0
        ;;
    *)
        echo "ERROR: unknown option: $1" >&2
        echo "Usage: $0 [--load|--smoke-test]" >&2
        exit 2
        ;;
esac
if (( $# > 1 )); then
    echo "ERROR: expected at most one option" >&2
    exit 2
fi

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

echo "Detecting the remote PYNQ Python environment..."
remote_xrt="$({ ssh "$SSH_TARGET" 'bash -lc '\''printf %s "${XILINX_XRT:-}"'\'''; } 2>/dev/null || true)"
if [[ -z "$remote_xrt" ]]; then
    remote_xrt=/usr
fi

remote_python=""
candidates=(
    /usr/local/share/pynq-venv/bin/python3
    /usr/local/share/pynq-venv/bin/python
)
login_python="$({ ssh "$SSH_TARGET" 'bash -lc '\''command -v python3'\'''; } 2>/dev/null || true)"
if [[ -n "$login_python" ]]; then
    candidates+=("$login_python")
fi

for candidate in "${candidates[@]}"; do
    if ssh "$SSH_TARGET" \
        "test -x '$candidate' && XILINX_XRT='$remote_xrt' '$candidate' -c 'import pynq, numpy; from pynq import Device, Overlay, allocate; assert Device.devices'" \
        >/dev/null 2>&1; then
        remote_python="$candidate"
        break
    fi
done

if [[ -z "$remote_python" ]]; then
    echo "ERROR: no working PYNQ Python environment was found on $SSH_TARGET." >&2
    echo "No packages were installed or modified." >&2
    exit 3
fi

version_info="$(ssh "$SSH_TARGET" \
    "XILINX_XRT='$remote_xrt' '$remote_python' -c 'import sys, pynq, numpy; print(sys.executable); print(sys.version.split()[0]); print(pynq.__version__); print(numpy.__version__)'")"
mapfile -t versions <<<"$version_info"
echo "Selected PYNQ Python: ${versions[0]}"
echo "Python ${versions[1]}, PYNQ ${versions[2]}, NumPy ${versions[3]}"
echo "PYNQ runtime environment: XILINX_XRT=$remote_xrt"

echo "Creating isolated remote directory: $REMOTE_DIR"
ssh "$SSH_TARGET" "mkdir -p -- '$REMOTE_DIR'"

sources=()
for name in "${required[@]}"; do
    sources+=("$DEPLOY_DIR/$name")
done
scp -r "${sources[@]}" "$SSH_TARGET:$REMOTE_DIR/"

echo "Deployed PYNQ-Z2 overlay files to $SSH_TARGET:$REMOTE_DIR/"

hardware_prefix=""
if ssh "$SSH_TARGET" 'test "$(id -u)" -eq 0' >/dev/null 2>&1; then
    hardware_prefix=env
elif ssh "$SSH_TARGET" 'sudo -n true' >/dev/null 2>&1; then
    hardware_prefix="sudo -n env"
fi

load_command="cd '$REMOTE_DIR' && ${hardware_prefix:+$hardware_prefix }XILINX_XRT='$remote_xrt' '$remote_python' load_overlay.py"
smoke_command="cd '$REMOTE_DIR' && ${hardware_prefix:+$hardware_prefix }XILINX_XRT='$remote_xrt' '$remote_python' smoke_test.py"

if [[ "$action" == deploy ]]; then
    echo "PYNQ import check: PASS"
    if [[ -n "$hardware_prefix" ]]; then
        echo "Load-only test: ssh $SSH_TARGET \"$load_command\""
        echo "Functional test: ssh $SSH_TARGET \"$smoke_command\""
    else
        echo "Hardware tests require root on this PYNQ image; no noninteractive root runner was found."
        echo "Use the root-run Jupyter kernel, or an administrator-approved interactive sudo session."
    fi
    exit 0
fi

if [[ -z "$hardware_prefix" ]]; then
    echo "ERROR: PYNQ imports work, but FPGA access requires root on $SSH_TARGET." >&2
    echo "The SSH user is non-root, sudo -n is unavailable, and no privilege settings were changed." >&2
    exit 4
fi

if [[ "$action" == load ]]; then
    ssh "$SSH_TARGET" "$load_command"
else
    ssh "$SSH_TARGET" "$smoke_command"
fi
