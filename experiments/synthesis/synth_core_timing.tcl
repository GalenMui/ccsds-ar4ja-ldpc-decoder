# experiments/synthesis/synth_core_timing.tcl
# Focused OOC synth of the decoder core WITH a 100 MHz clock on `clk`, to measure
# setup timing of the failing path (which lives in ldpc_decoder_top).  Fast
# (~2 min, ~2 GB) so it can be run before/after a targeted RTL change.
#
#   vivado -mode batch -nojournal -notrace -source <this> -tclargs <tag> [period_ns]
set tag "core_timing"
set period 10.0
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set tag    [lindex $argv 0] }
if {[llength $argv] >= 2 && [lindex $argv 1] ne ""} { set period [lindex $argv 1] }

set_param general.maxThreads 2
set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]
set out_dir    [file join $script_dir results $tag]
file mkdir $out_dir

foreach s {rtl/ar4ja_1024_pkg.sv rtl/ldpc_schedule_pkg.sv rtl/ldpc_decoder_top.sv} {
    read_verilog -sv [file join $repo_root $s]
}
set t0 [clock milliseconds]
synth_design -top ldpc_decoder_top -part xc7z020clg400-1 -mode out_of_context \
    -flatten_hierarchy rebuilt
create_clock -name clk -period $period [get_ports clk]
set el [expr {[clock milliseconds]-$t0}]

report_utilization        -file [file join $out_dir utilization.rpt]
report_ram_utilization    -file [file join $out_dir ram.rpt]
report_timing_summary     -file [file join $out_dir timing_summary.rpt]
# Top worst paths grouped by unique endpoint, so we see the path *classes*.
report_timing -setup -max_paths 12 -unique_pins -path_type summary \
    -file [file join $out_dir worst_paths.rpt]

# Compact per-path breakdown (endpoint / slack / levels / logic ns / route ns) for
# the top 25 unique-endpoint setup paths, so we can classify logic- vs route-bound.
set fh [open [file join $out_dir path_breakdown.rpt] w]
puts $fh [format "%-42s %8s %6s %8s %8s" "ENDPOINT" "SLACK" "LVLS" "LOGIC" "ROUTE"]
foreach p [get_timing_paths -setup -max_paths 25 -unique_pins] {
    set ep    [get_property ENDPOINT_PIN $p]
    set slk   [get_property SLACK $p]
    set lvl   [get_property LOGIC_LEVELS $p]
    set dl    [get_property DATAPATH_LOGIC_DELAY $p]
    set dr    [get_property DATAPATH_DELAY $p]
    puts $fh [format "%-42s %8.3f %6s %8.3f %8.3f" $ep $slk $lvl $dl $dr]
}
close $fh

proc nc {r} { return [llength [get_cells -hierarchical -quiet -filter "REF_NAME == $r"]] }
set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -setup] 0]]
set luts [llength [get_cells -hier -quiet -filter {PRIMITIVE_GROUP == LUT}]]
set ffs  [llength [get_cells -hier -quiet -filter {PRIMITIVE_GROUP == FLOP_LATCH}]]
puts "CORE TIMING tag=$tag period=$period WNS=$wns RAMB36=[nc RAMB36E1] RAMB18=[nc RAMB18E1] DSP=[nc DSP48E1] LUT=$luts FF=$ffs elapsed_ms=$el"
exit 0
