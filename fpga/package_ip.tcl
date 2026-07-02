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

set ip_dir [file join $repo_root results ip_repo ldpc_axis_decoder_ip]
file mkdir $ip_dir

create_project -force ldpc_axis_decoder_ip_packager $ip_dir -part $part
add_files [list \
    [file join $repo_root rtl ar4ja_1024_pkg.sv] \
    [file join $repo_root rtl posterior_memory.sv] \
    [file join $repo_root rtl message_memory.sv] \
    [file join $repo_root rtl ldpc_decoder_top.sv] \
    [file join $repo_root rtl ldpc_axis_wrapper.sv] \
    [file join $repo_root rtl ldpc_axis_decoder_ip.sv] \
]
set_property top ldpc_axis_decoder_ip [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $ip_dir -vendor user.org -library user -taxonomy /UserIP -force
set core [ipx::current_core]
set_property name ldpc_axis_decoder_ip $core
set_property display_name "CCSDS AR4JA LDPC AXI-Stream Decoder" $core
set_property description "Fixed CCSDS AR4JA rate-1/2 k=1024 layered normalized min-sum decoder with 32-bit AXI-Stream input and output" $core
ipx::associate_bus_interfaces -busif s_axis -clock aclk $core
ipx::associate_bus_interfaces -busif m_axis -clock aclk $core
ipx::save_core $core
close_project
