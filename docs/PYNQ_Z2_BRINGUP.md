# PYNQ-Z2 Build and Bring-Up

This is the repeatable build/deploy path for the Linux-controlled PYNQ-Z2
overlay. It preserves the verified `LANES=8` decoder and its 100 MHz target.

## Hardware design

- Device: TUL PYNQ-Z2, `xc7z020clg400-1`.
- Vivado top: `ccsds_ldpc_pynq_z2_bd_wrapper`.
- Decoder: `ldpc_axis_decoder_ip`, unchanged, behind the transparent
  `ldpc_axis_decoder_bd` IP Integrator wrapper.
- Clock: `processing_system7_0/FCLK_CLK0`, 100.0 MHz.
- Reset: PS `FCLK_RESET0_N` through `proc_sys_reset_0`; all AXI and decoder
  resets are active-low and synchronous to FCLK0 after release.
- Data path: PS DDR through HP0, AXI DMA MM2S, decoder, AXI DMA S2MM, PS DDR.
- Control: PS GP0 to AXI DMA AXI-Lite at `0x40400000`.
- Top-level physical interfaces: only the Zynq hard `DDR` and `FIXED_IO`
  interfaces. There are no external PL pins.

No user XDC is active in this block-design build. Clock constraints are
generated from the configured PS FCLK and the IP Integrator metadata. The
repository XDC files serve other flows:

- `constraints/pynq_z2.xdc`: PL-only clock/button/LED bring-up top.
- `fpga/constraints/ldpc_axis_decoder.xdc`: out-of-context decoder timing.

The local Vivado installation does not contain the TUL board definition. The
script therefore targets the exact device and explicitly enables FCLK0, GP0,
HP0, and their address maps. This is valid for an overlay loaded after PYNQ
Linux has initialized the board's PS DDR/MIO. The generated XSA must not be
treated as a standalone boot-platform handoff without first applying the TUL
PS preset.

## Build

Vivado 2025.2 (Build 6299465) is used by the build command:

```bash
make pynq-z2-bitstream
make pynq-z2-package
```

The build recreates the project from Tcl, runs synthesis, `opt_design`,
Explore placement, aggressive physical optimization, Explore routing,
post-route physical optimization, timing/DRC gates, and bitstream generation.
It intentionally refuses to export the hardware platform when setup, hold, or
Error/Critical-Warning DRC checks fail.

Implementation evidence:

```text
results/pynq_z2/reports/impl/timing_summary_impl.rpt
results/pynq_z2/reports/impl/drc_impl.rpt
results/pynq_z2/reports/impl/route_status_impl.rpt
results/pynq_z2/reports/impl/clocks_impl.rpt
results/pynq_z2/logs/bitstream.log
```

Stable deployment artifacts:

```text
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.bit
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.hwh
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.bin
build/pynq_z2/deploy/ccsds_ldpc_pynq_z2.xsa
build/pynq_z2/deploy/manifest.json
```

The matching `.bit` and `.hwh` names are required by PYNQ. The manifest records
the source commit/worktree state, hashes, target, tool version, clock, and
post-route timing.

Measured implementation acceptance results for the generated artifacts:

```text
Route status:       16,553/16,553 routable nets fully routed; 0 route errors
Setup WNS / TNS:   +0.091 ns / 0.000 ns; 0 failing endpoints
Hold WHS / THS:    +0.018 ns / 0.000 ns; 0 failing endpoints
Clock:              10.000 ns, 100.000 MHz, PS7 FCLK_CLK0
check_timing:       0 no-clock or unconstrained endpoints in every category
DRC gate:           0 Error, 0 Critical Warning violations
```

The non-blocking DRC findings are 54 warnings and 2 advisories. Most are the
decoder's existing asynchronous-register-reset-to-BRAM-control warnings; reset
assertion occurs only while the decoder is idle and the design clears its
working memories before processing a frame. Other warnings are generated AXI
interconnect/RAMB optimization advice and one unloaded internal diagnostic net.
They were reviewed, not suppressed. The PS reset is active-low as generated
(`C_EXT_RESET_HIGH=0`) and `proc_sys_reset_0` synchronizes its release to FCLK0.

## SSH and deployment

The deployment is isolated from unrelated notebooks and never deletes remote
files. Verify the configured alias exactly as follows:

```bash
ssh pynq 'hostname && whoami && pwd'
```

The board inspected on July 14, 2026 runs PynqLinux 3.0 (Belfast), based on
Ubuntu 22.04, with kernel `5.15.19-xilinx-v2022.1` on `armv7l`. Its software
versions are:

```text
noninteractive python3: /usr/bin/python3, Python 3.10.4
PYNQ Python:            /usr/local/share/pynq-venv/bin/python3, Python 3.10.4
PYNQ:                   3.0.1
NumPy:                  1.21.5
XRT environment:        XILINX_XRT=/usr
```

The Jupyter service runs
`/usr/local/share/pynq-venv/bin/python3 .../jupyter-notebook` as root, and its
only kernel is the virtual environment's Python 3 kernel. The deployment
directory is inside Jupyter's `/home/xilinx/jupyter_notebooks` tree.

Raw noninteractive SSH does not source `/etc/profile.d/pynq_venv.sh` or
`/etc/profile.d/xrt_setup.sh`. Consequently, plain `python3` resolves to
`/usr/bin/python3` and cannot import the virtual-environment dependencies.
Using only the absolute virtualenv interpreter fixes imports, but PYNQ device
discovery additionally requires `XILINX_XRT=/usr`:

```bash
ssh pynq 'XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 -c "import sys, pynq, numpy; from pynq import Device; print(sys.executable); print(pynq.__version__); print(numpy.__version__); print(Device.devices)"'
```

This command was tested successfully. No package installation, Python change,
or board environment modification was necessary.

Deploy only the runtime and test files:

```bash
./scripts/board/deploy_pynq.sh
```

The script verifies artifacts and SSH, selects the PYNQ interpreter, verifies
PYNQ device discovery, prints the selected versions, and copies the isolated
runtime directory. It does not install packages. Optional deploy-and-run modes
are:

```bash
./scripts/board/deploy_pynq.sh --load
./scripts/board/deploy_pynq.sh --smoke-test
```

Hardware operations on this PynqLinux 3.0 image require a privileged PYNQ
context because PYNQ maps the Zynq SLCR and uses root-owned FPGA/DMA devices.
The verified workflow uses the board image's existing root Jupyter terminal.
It does not weaken device permissions, add passwordless sudo, alter SSH, or add
a second PYNQ installation. The deploy-only SSH workflow remains safe for the
unprivileged `xilinx` account; run overlay programming and DMA tests in the root
Jupyter terminal.

Defaults:

```text
SSH alias:   pynq
Remote path: /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder/
```

Override without editing the script if needed:

```bash
PYNQ_SSH_TARGET=pynq \
PYNQ_REMOTE_DIR=/home/xilinx/ccsds_ar4ja_ldpc_decoder \
./scripts/board/deploy_pynq.sh
```

## Load-only smoke test

This programs the FPGA, verifies PYNQ reports it loaded, lists overlay IP, and
initializes both DMA channels. It does **not** claim decoder correctness.

From the board's root Jupyter terminal, use the verified environment
explicitly:

```bash
cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 load_overlay.py
```

The physical-board run reported `Overlay loaded: True`, discovered
`axi_dma_0`, and initialized both MM2S and S2MM channels.

In a Jupyter notebook:

```python
from pathlib import Path
from pynq import Overlay

root = Path("/home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder")
overlay = Overlay(str(root / "ccsds_ldpc_pynq_z2.bit"))
print("Bitstream loaded:", overlay.is_loaded())
print("Available IP:", sorted(overlay.ip_dict))
```

The Jupyter service and kernel were verified to use the same PYNQ virtual
environment, run with the hardware permissions PYNQ requires, and see the
deployment directory. The notebook-style import and overlay paths are therefore
compatible without a separate kernel or package installation.

## Functional DMA smoke test

The functional test sends the repository's noiseless all-zero CCSDS frame
through AXI DMA and compares status and all decoded bits with the checked-in
Python fixed-point golden model:

```bash
cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 smoke_test.py
```

Optional additional noiseless frames, not yet physically validated:

```bash
XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 smoke_test.py --random-frames 3
```

The smoke test is staged: overlay/DMA discovery, contiguous buffer allocation,
DMA initialization, the minimal all-zero noiseless transfer, and exact golden
output comparison. It prints buffer addresses, transfer sizes, raw MM2S/S2MM
status registers, decoded status flags, deterministic input/output hashes, and
first mismatch indices. Both waits remain bounded by `--timeout` (10 seconds by
default).

If a DMA transfer fails, record the printed status before retrying. The status
decoder reports halted, idle, internal/slave/decode errors, and interrupt bits.
Re-running the smoke test reprograms the overlay and reconstructs both DMA
channels, which is the safe first recovery step for stale channel state. Do not
loop unchanged after a timeout: check that S2MM was submitted first, the lengths
are 2048/160 bytes, physical addresses are aligned and below the DMA address
limit, and the decoder emitted output `TLAST` on word 39.

## Physical hardware result

The first physical PYNQ-Z2 test passed on July 15, 2026. This is an end-to-end
hardware result, distinct from the repository's Python tests and RTL
simulations.

- Board/FPGA: TUL PYNQ-Z2, `xc7z020clg400-1`, `LANES=8` decoder.
- Implemented clock: PS7 FCLK0 at 100 MHz; setup WNS `+0.091 ns`, setup TNS
  `0.000 ns`, hold WHS `+0.018 ns`, hold THS `0.000 ns`.
- Overlay: loaded successfully (`Overlay loaded: True`).
- Addressable DMA: `axi_dma_0`; MM2S and S2MM channels initialized.
- Buffers: 512 `uint32` input words / 2048 bytes and 40 `uint32` output words /
  160 bytes.
- Deterministic input: 1024 zero payload bits, encoded to 2048 zero transmitted
  bits, converted to 2048 LLRs of `+32`, packed as 512 words of `0x20202020`.
- Expected status: `success=1`, `syndrome=1`, `failure=0`, `iterations=0`,
  `saturation=0`, and 1024 decoded zero bits.
- Observed status: `success=1`, `syndrome=1`, `failure=0`, `iterations=0`,
  `cycles=2625`, `saturation=0`, `words=40`.
- DMA completion: MM2S `0x00001002` and S2MM `0x00001002`, both idle with the
  IOC interrupt asserted.
- Expected and actual decoded-output SHA-256:
  `5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef`.
- Final script result: `PYNQ-Z2 LDPC smoke test passed`.

Commands used from the root Jupyter terminal:

```bash
cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 load_overlay.py
XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 smoke_test.py
```

This validates programming, overlay metadata, contiguous allocation, both DMA
directions, AXI stream framing for the minimal valid packet, decoder status,
and the complete 1024-bit decoded result for one zero-noise vector. It is not a
throughput benchmark, BER/FER measurement, consecutive-frame test, noisy-vector
test, randomized hardware regression, or validation of other code rates,
block sizes, or lane configurations.

## Shutdown

After tests finish, stop Linux cleanly before removing power:

```bash
ssh pynq
sudo shutdown -h now
```

To reboot instead, use `sudo reboot`. Both commands require an authenticated
administrator session on the inspected image; do not remove power while Linux
is writing the SD card.
