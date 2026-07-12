set script_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $script_dir ..]]

if {[llength $argv] > 0} {
    set part [lindex $argv 0]
} elseif {[info exists ::env(FPGA_PART)]} {
    set part $::env(FPGA_PART)
} else {
    puts "ERROR: pass an FPGA part as argv[0] or set FPGA_PART"
    exit 2
}

# On a memory-constrained host, Vivado's Cross-Boundary/Area Optimization forks
# one ~0.8 GB worker per thread; on the combinational H-matrix cones in this
# decoder that can exhaust a 12 GB box.  Cap threads via VIVADO_MAX_THREADS to
# bound peak memory (trades wall time).  Unset => Vivado default (full speed).
if {[info exists ::env(VIVADO_MAX_THREADS)] && $::env(VIVADO_MAX_THREADS) ne ""} {
    set_param general.maxThreads $::env(VIVADO_MAX_THREADS)
    puts "NOTE: general.maxThreads capped at $::env(VIVADO_MAX_THREADS) (VIVADO_MAX_THREADS)"
}

set build_dir [file join $repo_root results vivado_ooc synth]
file mkdir $build_dir

set source_manifest [file join $repo_root rtl ldpc_sources.f]
set source_fh [open $source_manifest r]
while {[gets $source_fh line] >= 0} {
    set source [string trim $line]
    if {$source eq ""} {
        continue
    }
    if {[string match "#*" $source]} {
        continue
    }
    read_verilog -sv [file join $repo_root $source]
}
close $source_fh

read_xdc [file join $repo_root fpga constraints ldpc_axis_decoder.xdc]

synth_design -top ldpc_axis_decoder_ip -part $part -mode out_of_context

report_utilization -file [file join $build_dir utilization_synth.rpt]
report_timing_summary -file [file join $build_dir timing_summary_synth.rpt]
report_ram_utilization -file [file join $build_dir ram_utilization.rpt]
report_hierarchy -file [file join $build_dir hierarchy.rpt]
report_compile_order -fileset sources_1 -file [file join $build_dir compile_order.rpt]
report_drc -file [file join $build_dir drc.rpt]
write_checkpoint -force [file join $build_dir ldpc_axis_decoder_ip.dcp]
