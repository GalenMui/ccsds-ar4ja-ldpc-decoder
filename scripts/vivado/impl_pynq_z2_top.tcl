# scripts/vivado/impl_pynq_z2_top.tcl
# -----------------------------------------------------------------------------
# Place & route (and optional bitstream) for the PYNQ-Z2 board top.
#
# Stage 3 of the staged flow.  Opens the synthesized checkpoint produced by
# synth_pynq_z2_top.tcl, runs opt/place/route, and writes reports.  Bitstream
# generation is GATED: it only runs when explicitly requested AND the XDC has
# been marked verified (STATUS: VERIFIED) so we never write a bitstream over
# guessed pin constraints.
#
# Usage:
#   vivado -mode batch -source scripts/vivado/impl_pynq_z2_top.tcl [-tclargs <part> <bitstream>]
#   <part>      default xc7z020clg400-1
#   <bitstream> "bitstream" to request a .bit; anything else = route only
#
# Outputs:
#   build/vivado/impl_pynq_z2_top.dcp        post-route checkpoint
#   build/vivado/pynq_z2_top.bit             (only if bitstream requested + XDC verified)
#   reports/vivado/impl_pynq_z2/*.rpt        reports
# -----------------------------------------------------------------------------

proc fail {msg} {
    puts "ERROR: $msg"
    exit 1
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]

set part      "xc7z020clg400-1"
set do_bit    "route_only"
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set part   [lindex $argv 0] }
if {[llength $argv] >= 2 && [lindex $argv 1] ne ""} { set do_bit [lindex $argv 1] }

set build_dir  [file join $repo_root build vivado]
set report_dir [file join $repo_root reports vivado impl_pynq_z2]
set synth_dcp  [file join $build_dir synth_pynq_z2_top.dcp]
set xdc        [file join $repo_root constraints pynq_z2.xdc]
file mkdir $report_dir

puts "== impl_pynq_z2_top =="
puts "repo_root : $repo_root"
puts "part      : $part"
puts "bitstream : $do_bit"

if {![file exists $synth_dcp]} {
    fail "synth checkpoint not found: $synth_dcp (run synth_pynq_z2_top first)"
}

if {[catch {open_checkpoint $synth_dcp} err]} { fail "open_checkpoint failed: $err" }

if {[catch {opt_design}    err]} { fail "opt_design failed: $err" }
if {[catch {place_design}  err]} { fail "place_design failed: $err" }
if {[catch {route_design}  err]} { fail "route_design failed: $err" }

write_checkpoint -force [file join $build_dir impl_pynq_z2_top.dcp]
report_utilization    -file [file join $report_dir utilization.rpt]
report_timing_summary -file [file join $report_dir timing_summary.rpt]
report_drc            -file [file join $report_dir drc.rpt]
report_route_status   -file [file join $report_dir route_status.rpt]

# --- Bitstream gate. ---------------------------------------------------------
if {$do_bit eq "bitstream"} {
    # 1) Refuse to write a bitstream over unverified pin constraints.
    set verified 0
    if {[file exists $xdc]} {
        set fh [open $xdc r]
        set contents [read $fh]
        close $fh
        if {[regexp {STATUS:\s*VERIFIED} $contents]} { set verified 1 }
    }
    if {!$verified} {
        fail "XDC is not marked VERIFIED (constraints/pynq_z2.xdc STATUS line). Refusing to write a bitstream over unverified pins. Verify the PYNQ-Z2 pinout, set STATUS: VERIFIED, and re-run."
    }

    # 2) Refuse if timing did not meet (negative WNS) — surface, do not hide.
    set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    if {$wns ne "" && $wns < 0} {
        puts "WARNING: setup timing not met (WNS = $wns ns). Writing bitstream anyway is unsafe for board operation."
        fail "timing not met; not writing bitstream"
    }

    if {[catch {write_bitstream -force [file join $build_dir pynq_z2_top.bit]} err]} {
        fail "write_bitstream failed: $err"
    }
    puts "bitstream written: [file join $build_dir pynq_z2_top.bit]"
} else {
    puts "route-only run (bitstream not requested)."
}

puts "impl_pynq_z2_top completed: checkpoint at [file join $build_dir impl_pynq_z2_top.dcp]"
exit 0
