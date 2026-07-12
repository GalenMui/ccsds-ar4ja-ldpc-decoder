# experiments/synthesis/impl_ip_timing.tcl
# Focused OOC implementation (synth -> opt -> place -> route) of the full IP top
# with the 100 MHz clock, to get REAL post-route timing.  Justified because the
# post-synth OOC slack is dominated by pessimistic pre-placement route estimates
# (the worst path is only ~13 logic levels / 3.5 ns of logic), so only place &
# route can confirm 100 MHz closure.  The design is small (~10k LUT, 12 BRAM) so
# this is cheap.
#
#   vivado -mode batch -nojournal -notrace -source <this> -tclargs [period_ns]
set period 10.0
if {[llength $argv] >= 1 && [lindex $argv 0] ne ""} { set period [lindex $argv 0] }

set_param general.maxThreads 2
set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir .. ..]]
set out_dir    [file join $script_dir results impl_ip]
file mkdir $out_dir

foreach s {
    rtl/ar4ja_1024_pkg.sv rtl/ldpc_schedule_pkg.sv
    rtl/posterior_memory.sv rtl/message_memory.sv
    rtl/ldpc_decoder_top.sv rtl/ldpc_axis_wrapper.sv rtl/ldpc_axis_decoder_ip.sv
} { read_verilog -sv [file join $repo_root $s] }
read_xdc [file join $repo_root fpga constraints ldpc_axis_decoder.xdc]

set t0 [clock milliseconds]
synth_design -top ldpc_axis_decoder_ip -part xc7z020clg400-1 -mode out_of_context
set wns_synth [get_property SLACK [lindex [get_timing_paths -max_paths 1 -setup] 0]]
report_utilization -file [file join $out_dir util_synth.rpt]

opt_design
place_design
phys_opt_design
route_design
# Post-route physical optimisation (legitimate part of a normal impl flow; not a
# timing exception) — often recovers the last 1–2 ns of route-dominated slack.
catch {phys_opt_design}
set el [expr {[clock milliseconds]-$t0}]

report_timing_summary -file [file join $out_dir timing_postroute.rpt]
report_utilization    -file [file join $out_dir util_postroute.rpt]
report_ram_utilization -file [file join $out_dir ram_postroute.rpt]
set wns_route [get_property SLACK [lindex [get_timing_paths -max_paths 1 -setup] 0]]
set whs_route [get_property SLACK [lindex [get_timing_paths -max_paths 1 -hold] 0]]

proc nc {r} { return [llength [get_cells -hierarchical -quiet -filter "REF_NAME == $r"]] }
puts "IMPL RESULT period=$period WNS_synth=$wns_synth WNS_route=$wns_route WHS_route=$whs_route RAMB36=[nc RAMB36E1] RAMB18=[nc RAMB18E1] DSP=[nc DSP48E1] LUT=[llength [get_cells -hier -quiet -filter {PRIMITIVE_GROUP==LUT}]] FF=[llength [get_cells -hier -quiet -filter {PRIMITIVE_GROUP==FLOP_LATCH}]] elapsed_ms=$el"
exit 0
