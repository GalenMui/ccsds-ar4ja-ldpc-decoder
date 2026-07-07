# =============================================================================
# constraints/pynq_z2.xdc
# PYNQ-Z2 (TUL) board constraints for rtl/board/pynq_z2_top.sv
# Target part: xc7z020clg400-1
# =============================================================================
#
# PROVENANCE / VERIFICATION STATUS  <-- READ THIS BEFORE GENERATING A BITSTREAM
# -----------------------------------------------------------------------------
# The PACKAGE_PIN and IOSTANDARD values below correspond to the well-known
# public TUL "PYNQ-Z2 v1.0" master constraints (the sysclk, user LEDs, and
# push-buttons block).  They were NOT auto-extracted from board files installed
# on this machine (no PYNQ-Z2 board files were found under the Vivado install at
# the time this file was written), so they are marked as REQUIRING VERIFICATION.
#
# Before you run `make vivado-bitstream`, you MUST confirm each pin against the
# official master XDC for YOUR board revision, e.g.:
#   https://github.com/Xilinx/PYNQ  (board files) or the TUL PYNQ-Z2 reference.
# When you have verified them against a trusted source, change the STATUS line
# below to VERIFIED; the bitstream Make target checks for that word.
#
# STATUS: UNVERIFIED
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# System clock: 125 MHz single-ended fabric clock ("sysclk").
# TUL PYNQ-Z2 master XDC: PACKAGE_PIN H16, LVCMOS33, 125 MHz (8.000 ns).
# TODO(verify): confirm H16 / LVCMOS33 / 125 MHz for your board revision.
# ---------------------------------------------------------------------------
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports sysclk]
create_clock -name sysclk -period 8.000 [get_ports sysclk]

# ---------------------------------------------------------------------------
# Reset push button: BTN0 (active-high on press).
# TUL PYNQ-Z2 master XDC: BTN0 = PACKAGE_PIN D19, LVCMOS33.
# TODO(verify): confirm D19 / LVCMOS33, and that BTN0 is the button you want.
# ---------------------------------------------------------------------------
set_property -dict {PACKAGE_PIN D19 IOSTANDARD LVCMOS33} [get_ports rst_btn]

# ---------------------------------------------------------------------------
# User LEDs LD0..LD3.
# TUL PYNQ-Z2 master XDC: LD0=R14, LD1=P14, LD2=N16, LD3=M14, all LVCMOS33.
# TODO(verify): confirm R14/P14/N16/M14 / LVCMOS33 for your board revision.
# ---------------------------------------------------------------------------
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[3]}]

# ---------------------------------------------------------------------------
# The reset button is asynchronous to sysclk and is synchronized in RTL, so it
# is treated as a false path for setup/hold analysis.
# ---------------------------------------------------------------------------
set_false_path -from [get_ports rst_btn]
