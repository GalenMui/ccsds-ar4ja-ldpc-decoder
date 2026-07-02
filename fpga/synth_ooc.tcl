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

set build_dir [file join $repo_root results vivado_ooc]
file mkdir $build_dir

read_verilog -sv [file join $repo_root rtl ar4ja_1024_pkg.sv]
read_verilog -sv [file join $repo_root rtl posterior_memory.sv]
read_verilog -sv [file join $repo_root rtl message_memory.sv]
read_verilog -sv [file join $repo_root rtl ldpc_decoder_top.sv]
read_verilog -sv [file join $repo_root rtl ldpc_axis_wrapper.sv]
read_verilog -sv [file join $repo_root rtl ldpc_axis_decoder_ip.sv]
read_xdc [file join $repo_root fpga constraints ldpc_axis_decoder.xdc]

synth_design -top ldpc_axis_decoder_ip -part $part -mode out_of_context
opt_design
place_design
route_design

report_utilization -file [file join $build_dir utilization.rpt]
report_timing_summary -file [file join $build_dir timing_summary.rpt]
report_ram_utilization -file [file join $build_dir ram_utilization.rpt]
write_checkpoint -force [file join $build_dir ldpc_axis_decoder_ip.dcp]
