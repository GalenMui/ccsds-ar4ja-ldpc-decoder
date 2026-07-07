# scripts/vivado/synth_pynq_z2_top.tcl
# -----------------------------------------------------------------------------
# Synthesis of the PYNQ-Z2 board top (pynq_z2_top) WITH board pin constraints.
#
# Stage 2 of the staged flow: proves the board top + XDC elaborate and
# synthesize with real top-level ports mapped to the part.
#
# Usage:
#   vivado -mode batch -source scripts/vivado/synth_pynq_z2_top.tcl [-tclargs <part>]
# Default part: xc7z020clg400-1
#
# Outputs:
#   build/vivado/synth_pynq_z2_top.dcp        post-synth checkpoint
#   reports/vivado/synth_pynq_z2/*.rpt        reports
# -----------------------------------------------------------------------------

proc fail {msg} {
    puts "ERROR: $msg"
    exit 1
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]

set part "xc7z020clg400-1"
set top  "pynq_z2_top"
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set part [lindex $argv 0] }

set board_top [file join $repo_root rtl board pynq_z2_top.sv]
set xdc       [file join $repo_root constraints pynq_z2.xdc]

set build_dir  [file join $repo_root build vivado]
set report_dir [file join $repo_root reports vivado synth_pynq_z2]
file mkdir $build_dir
file mkdir $report_dir

puts "== synth_pynq_z2_top =="
puts "repo_root : $repo_root"
puts "part      : $part"
puts "top       : $top"

if {![file exists $board_top]} { fail "board top not found: $board_top" }
if {![file exists $xdc]}       { fail "XDC not found: $xdc" }

# --- Read RTL manifest (packages first), then the board top. -----------------
set manifest [file join $repo_root rtl ldpc_sources.f]
if {![file exists $manifest]} { fail "source manifest not found: $manifest" }

set fh [open $manifest r]
set sources {}
while {[gets $fh line] >= 0} {
    set s [string trim $line]
    if {$s eq "" || [string match "#*" $s]} { continue }
    set path [file join $repo_root $s]
    if {![file exists $path]} { fail "listed source not found: $path" }
    lappend sources $path
}
close $fh
lappend sources $board_top

foreach f $sources {
    puts "read_verilog -sv $f"
    if {[catch {read_verilog -sv $f} err]} { fail "read_verilog failed for $f: $err" }
}

if {[catch {read_xdc $xdc} err]} { fail "read_xdc failed for $xdc: $err" }

if {[catch {synth_design -top $top -part $part} err]} {
    fail "synth_design failed: $err"
}

write_checkpoint -force [file join $build_dir synth_pynq_z2_top.dcp]
report_utilization    -file [file join $report_dir utilization.rpt]
report_timing_summary -file [file join $report_dir timing_summary.rpt]
report_drc            -file [file join $report_dir drc.rpt]

# Flag any top-level ports that ended up without a package pin (guards against
# a bitstream over unconstrained I/O).
set unconstrained {}
foreach p [get_ports] {
    if {[get_property PACKAGE_PIN $p] eq ""} { lappend unconstrained $p }
}
if {[llength $unconstrained] > 0} {
    puts "WARNING: top-level ports without PACKAGE_PIN: $unconstrained"
}

puts "synth_pynq_z2_top completed: checkpoint at [file join $build_dir synth_pynq_z2_top.dcp]"
exit 0
