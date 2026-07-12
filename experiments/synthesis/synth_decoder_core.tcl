# experiments/synthesis/synth_decoder_core.tcl
# Gate C: OOC synth of the decoder core (ldpc_decoder_top) alone -- no AXI
# wrapper -- to confirm the banked memories still infer BRAM after integration
# with the full decode datapath, and that runtime/memory are now tractable.
#
#   vivado -mode batch -nojournal -notrace -source <this> -tclargs <part>
set part "xc7z020clg400-1"
set maxthreads 0
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set part [lindex $argv 0] }
if {[llength $argv] >= 2 && [lindex $argv 1] ne ""} { set maxthreads [lindex $argv 1] }

# On a memory-constrained host the multithreaded Cross-Boundary/Area
# Optimization workers (one ~0.8 GB process per thread) are what push this
# design into swap.  Capping threads bounds peak memory so synthesis completes.
if {$maxthreads > 0} {
    set_param general.maxThreads $maxthreads
    puts "== general.maxThreads capped at $maxthreads =="
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]
set out_dir    [file join $script_dir results gateC_decoder_core]
file mkdir $out_dir

foreach s {
    rtl/ar4ja_1024_pkg.sv
    rtl/ldpc_schedule_pkg.sv
    rtl/ldpc_decoder_top.sv
} {
    read_verilog -sv [file join $repo_root $s]
}

set t0 [clock milliseconds]
synth_design -top ldpc_decoder_top -part $part -mode out_of_context -flatten_hierarchy rebuilt
set elapsed_ms [expr {[clock milliseconds] - $t0}]

report_utilization    -file [file join $out_dir utilization.rpt]
report_ram_utilization -file [file join $out_dir ram_utilization.rpt]
report_timing_summary -file [file join $out_dir timing_summary.rpt]
write_checkpoint -force [file join $out_dir gateC_decoder_core.dcp]

proc ncells {ref} { return [llength [get_cells -hierarchical -quiet -filter "REF_NAME == $ref"]] }
set ramb36 [ncells RAMB36E1]
set ramb18 [ncells RAMB18E1]
set luts [llength [get_cells -hierarchical -quiet -filter {PRIMITIVE_GROUP == LUT}]]
set ffs  [llength [get_cells -hierarchical -quiet -filter {PRIMITIVE_GROUP == FLOP_LATCH}]]
set dsps [ncells DSP48E1]
puts "INFERENCE SUMMARY tag=gateC_decoder_core RAMB36=$ramb36 RAMB18=$ramb18 DSP=$dsps LUT=$luts FF=$ffs elapsed_ms=$elapsed_ms"
exit 0
