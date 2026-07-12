# experiments/synthesis/run_ooc.tcl
# -----------------------------------------------------------------------------
# Reusable single-question OOC synthesis experiment runner.
#
# Usage:
#   vivado -mode batch -nojournal -notrace \
#     -source experiments/synthesis/run_ooc.tcl \
#     -tclargs <tag> <top> <part> <src1> [<src2> ...]
#
# Writes reports to experiments/synthesis/results/<tag>/ and prints a one-line
# INFERENCE SUMMARY (RAMB18/RAMB36/LUT/FF/LUTRAM + elapsed) that the harness
# greps for.  Each experiment answers exactly one question and should finish in
# seconds-to-minutes, never the multi-hour full-decoder run.
# -----------------------------------------------------------------------------

if {[llength $argv] < 4} {
    puts "ERROR: usage: <tag> <top> <part> <src...>"
    exit 2
}
set tag  [lindex $argv 0]
set top  [lindex $argv 1]
set part [lindex $argv 2]
set srcs [lrange $argv 3 end]

set script_dir [file dirname [file normalize [info script]]]
set out_dir    [file join $script_dir results $tag]
file mkdir $out_dir

puts "== OOC experiment: $tag =="
puts "top  : $top"
puts "part : $part"
foreach s $srcs {
    puts "src  : $s"
    if {![file exists $s]} { puts "ERROR: missing source $s"; exit 1 }
    read_verilog -sv $s
}

set t0 [clock milliseconds]
if {[catch {synth_design -top $top -part $part -mode out_of_context -flatten_hierarchy rebuilt} err]} {
    puts "ERROR: synth_design failed: $err"
    exit 1
}
set elapsed_ms [expr {[clock milliseconds] - $t0}]

report_utilization      -file [file join $out_dir utilization.rpt]
if {[catch {report_ram_utilization -file [file join $out_dir ram_utilization.rpt]} e]} {
    puts "note: report_ram_utilization unavailable: $e"
}
write_checkpoint -force [file join $out_dir ${tag}.dcp]

# --- Primitive tallies straight from the netlist ------------------------------
proc ncells {ref} { return [llength [get_cells -hierarchical -quiet -filter "REF_NAME == $ref"]] }
set ramb36 [ncells RAMB36E1]
set ramb18 [ncells RAMB18E1]
# distributed RAM appears as RAMD*/RAMS* primitives
set lutram 0
foreach r {RAMD32 RAMD64 RAMS32 RAMS64} { incr lutram [ncells $r] }
set luts [llength [get_cells -hierarchical -quiet -filter {PRIMITIVE_GROUP == LUT}]]
set ffs  [llength [get_cells -hierarchical -quiet -filter {PRIMITIVE_GROUP == FLOP_LATCH}]]

puts "INFERENCE SUMMARY tag=$tag RAMB36=$ramb36 RAMB18=$ramb18 LUTRAM=$lutram LUT=$luts FF=$ffs elapsed_ms=$elapsed_ms"
exit 0
