# PYNQ-Z2 Bring-Up

This flow targets the TUL PYNQ-Z2 board with the Zynq-7000
`xc7z020clg400-1` device.

## Build Requirements

- Vivado installed and on `PATH`, or set `VIVADO=/path/to/vivado`.
- TUL PYNQ-Z2 Vivado board files installed for the final board build.
- PYNQ Linux on the board for host-side validation.

The Tcl flow searches installed board parts for PYNQ-Z2 and uses the board
preset when found. If the board files are missing, it falls back to the raw
`xc7z020clg400-1` part and prints a warning. Use that fallback for structural
project checks only; install the board files before relying on PS DDR/MIO
settings for hardware.

## Build Commands

From the repository root:

```sh
make pynq-z2-project
make pynq-z2-synth
make pynq-z2-bitstream
make pynq-z2-overlay
```

Configuration knobs:

```sh
make pynq-z2-bitstream \
  VIVADO=/path/to/vivado \
  PYNQ_Z2_PART=xc7z020clg400-1 \
  PYNQ_Z2_CLK_MHZ=100.0 \
  PYNQ_Z2_LANES=8 \
  PYNQ_Z2_JOBS=4
```

Generated project and reports:

```text
results/pynq_z2/vivado/ccsds_ldpc_pynq_z2/
results/pynq_z2/reports/
results/pynq_z2/logs/
```

The overlay package is:

```text
results/pynq_z2/overlay/ccsds_ldpc_pynq_z2.bit
results/pynq_z2/overlay/ccsds_ldpc_pynq_z2.hwh
```

The package directory also includes the PYNQ Python driver, smoke test,
benchmark, `requirements.txt`, and golden-model modules needed by the smoke
test.

## Block Design

The Vivado Tcl script creates this single-clock first-bring-up design:

```text
PS DDR
  <-> Zynq PS7 HP0
  <-> AXI memory interconnect
  <-> AXI DMA MM2S/S2MM
  ->  ldpc_axis_decoder_ip
  ->  AXI DMA S2MM
  <-> PS DDR

PS GP0 -> AXI-Lite interconnect -> AXI DMA control
PS FCLK0 100 MHz -> DMA, interconnects, decoder
Processor System Reset -> active-low AXI resets
```

Stable instance names used by software:

```text
axi_dma_0
ldpc_axis_decoder_0
processing_system7_0
proc_sys_reset_0
```

The DMA is simple mode, 32-bit stream width, with a 14-bit length field. The
largest transaction is the 2048-byte input frame, so this leaves margin.

The DMA AXI-Lite register segment is assigned to:

```text
0x40400000, range 64 KiB
```

## Transfer Contract

Host-to-PL input:

- Allocate 512 `uint32` words.
- Pack four signed int8 LLRs per word.
- Start S2MM receive before MM2S transmit.
- Transfer exactly 2048 bytes on MM2S.

PL-to-host output:

- Allocate 40 `uint32` words.
- Transfer exactly 160 bytes on S2MM.
- The decoder asserts `TLAST` on output word 39.
- Every input and output beat is a full 32-bit beat with `TKEEP=4'hf`.

## Running On The Board

Copy the generated overlay package directory to the PYNQ-Z2 board. From that
directory on the board:

```sh
python3 smoke_test.py
python3 smoke_test.py --random-frames 3
python3 benchmark.py --frames 10
```

The smoke test:

- Loads `ccsds_ldpc_pynq_z2.bit` and matching `.hwh`.
- Verifies `axi_dma_0` is visible in overlay metadata.
- Generates known noiseless frames.
- Runs the repository fixed-point golden model.
- Transfers through AXI DMA.
- Compares decoder status, iterations, saturation count, and decoded bits.

The benchmark reports Python + AXI DMA + decoder wall-clock time. It does not
claim pure decoder-core latency.

## Packaging Existing Artifacts

If a bitstream has already been generated, package without rebuilding:

```sh
make pynq-z2-package
```

Deploy to a mounted directory:

```sh
python3 boards/pynq_z2/scripts/package_overlay.py --deploy /media/pynq/ldpc
```

Deploy through SSH or mDNS using your own credentials:

```sh
python3 boards/pynq_z2/scripts/package_overlay.py --deploy xilinx@pynq:~/ldpc_overlay
```

The packaging script refuses missing or stale artifacts by default.

## Hardware Debug

Recommended ILA probes, if needed:

- `s_axis_tvalid`, `s_axis_tready`, `s_axis_tdata`, `s_axis_tkeep`, `s_axis_tlast`
- `m_axis_tvalid`, `m_axis_tready`, `m_axis_tdata`, `m_axis_tkeep`, `m_axis_tlast`
- `frame_error`, `early_tlast_error`, `missing_tlast_error`, `tkeep_error`
- DMA channel status in PYNQ

Common failures:

- S2MM wait never completes: check output `TLAST`, reset polarity, and S2MM
  started before MM2S.
- Immediate error response: check input length, `TLAST`, and `TKEEP`.
- Good status but bad bits: check LLR byte order and payload bit order.
- Works once only: restart both DMA channels for every frame and use 160-byte
  receive buffers.
