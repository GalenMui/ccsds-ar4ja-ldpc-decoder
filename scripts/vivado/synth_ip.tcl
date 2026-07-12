# scripts/vivado/synth_ip.tcl
# -----------------------------------------------------------------------------
# Out-of-context synthesis of the decoder IP-level top (ldpc_axis_decoder_ip).
#
# This proves the core RTL synthesizes for the PYNQ-Z2 part with no board top
# and no pin constraints (OOC).  It is the first stage of the staged flow.
#
# Usage:
#   vivado -mode batch -source scripts/vivado/synth_ip.tcl [-tclargs <part> <top>]
# Defaults: part=xc7z020clg400-1  top=ldpc_axis_decoder_ip
#
# Outputs:
#   build/vivado/synth_ip.dcp             post-synth checkpoint
#   reports/vivado/synth_ip/*.rpt         utilization / timing / drc reports
# -----------------------------------------------------------------------------

proc fail {msg} {
    puts "ERROR: $msg"
    exit 1
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]

set part "xc7z020clg400-1"
set top  "ldpc_axis_decoder_ip"
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set part [lindex $argv 0] }
if {[llength $argv] >= 2 && [lindex $argv 1] ne ""} { set top  [lindex $argv 1] }

set build_dir  [file join $repo_root build vivado]
set report_dir [file join $repo_root reports vivado synth_ip]
file mkdir $build_dir
file mkdir $report_dir

puts "== synth_ip =="
puts "repo_root : $repo_root"
puts "part      : $part"
puts "top       : $top"

# Cap Vivado optimizer threads on a memory-constrained host (one ~0.8 GB worker
# per thread during Cross-Boundary/Area Optimization).  Unset => Vivado default.
if {[info exists ::env(VIVADO_MAX_THREADS)] && $::env(VIVADO_MAX_THREADS) ne ""} {
    set_param general.maxThreads $::env(VIVADO_MAX_THREADS)
    puts "NOTE: general.maxThreads capped at $::env(VIVADO_MAX_THREADS)"
}

# --- Read the RTL source manifest (packages are listed first). ---------------
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
if {[llength $sources] == 0} { fail "no sources found in manifest $manifest" }

foreach f $sources {
    puts "read_verilog -sv $f"
    if {[catch {read_verilog -sv $f} err]} { fail "read_verilog failed for $f: $err" }
}

# --- Synthesize out-of-context (no board pins). ------------------------------
if {[catch {synth_design -top $top -part $part -mode out_of_context} err]} {
    fail "synth_design failed: $err"
}

write_checkpoint -force [file join $build_dir synth_ip.dcp]
report_utilization  -file [file join $report_dir utilization.rpt]
report_timing_summary -file [file join $report_dir timing_summary.rpt]
report_drc          -file [file join $report_dir drc.rpt]

puts "synth_ip completed: checkpoint at [file join $build_dir synth_ip.dcp]"
exit 0
