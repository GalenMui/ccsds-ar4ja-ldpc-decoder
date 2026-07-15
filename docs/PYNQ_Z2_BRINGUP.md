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

On the July 14, 2026 host run, the board answered but SSH stopped at the
passphrase prompt for `/home/galenmui/.ssh/id_ed25519`. Deployment and all
board-side commands below therefore remain untested until that key is unlocked
in the user's SSH agent. No SSH configuration or board files were changed.

Deploy only the runtime and test files:

```bash
./scripts/board/deploy_pynq.sh
```

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

```bash
ssh pynq
cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder
python3 load_overlay.py
```

Expected IP includes `axi_dma_0`.

In a Jupyter notebook:

```python
from pathlib import Path
from pynq import Overlay

root = Path("/home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder")
overlay = Overlay(str(root / "ccsds_ldpc_pynq_z2.bit"))
print("Bitstream loaded:", overlay.is_loaded())
print("Available IP:", sorted(overlay.ip_dict))
```

## Functional DMA smoke test

The functional test sends the repository's noiseless all-zero CCSDS frame
through AXI DMA and compares status and all decoded bits with the checked-in
Python fixed-point golden model:

```bash
ssh pynq 'cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder && python3 smoke_test.py'
```

Optional additional noiseless frames:

```bash
ssh pynq 'cd /home/xilinx/jupyter_notebooks/ccsds_ar4ja_ldpc_decoder && python3 smoke_test.py --random-frames 3'
```

## Shutdown

After tests finish, stop Linux cleanly before removing power:

```bash
ssh pynq
sudo shutdown -h now
```
