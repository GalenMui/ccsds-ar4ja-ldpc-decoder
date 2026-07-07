# Recreate the PYNQ-Z2 Vivado project and block design from repository sources.
#
# Usage:
#   vivado -mode batch -source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs project
#   vivado -mode batch -source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs synth
#   vivado -mode batch -source boards/pynq_z2/vivado/pynq_z2_build.tcl -tclargs bitstream

proc fail {message} {
    puts "ERROR: $message"
    exit 1
}

proc warn {message} {
    puts "WARNING: $message"
}

proc require_file {path} {
    if {![file exists $path]} {
        fail "required file not found: $path"
    }
}

proc get_env_or_default {name default_value} {
    if {[info exists ::env($name)] && $::env($name) ne ""} {
        return $::env($name)
    }
    return $default_value
}

proc set_cell_property_if_present {cell property value} {
    set actual_property ""
    foreach candidate [list_property $cell] {
        if {[string tolower $candidate] eq [string tolower $property]} {
            set actual_property $candidate
            break
        }
    }
    if {$actual_property eq ""} {
        warn "property $property is not present on $cell"
        return
    }
    set_property $actual_property $value $cell
}

proc set_cell_properties_if_present {cell property_pairs} {
    foreach {property value} $property_pairs {
        set_cell_property_if_present $cell $property $value
    }
}

proc connect_pin_if_present {source_pin sink_pin} {
    set source [get_bd_pins -quiet $source_pin]
    set sink [get_bd_pins -quiet $sink_pin]
    if {[llength $source] == 0} {
        warn "source pin not found: $source_pin"
        return
    }
    if {[llength $sink] == 0} {
        warn "sink pin not found: $sink_pin"
        return
    }
    connect_bd_net $source $sink
}

proc read_source_manifest {repo_root manifest_relpath} {
    set manifest [file join $repo_root $manifest_relpath]
    require_file $manifest

    set files [list]
    set fh [open $manifest r]
    while {[gets $fh line] >= 0} {
        set source [string trim $line]
        if {$source eq "" || [string match "#*" $source]} {
            continue
        }
        set path [file join $repo_root $source]
        require_file $path
        lappend files $path
    }
    close $fh
    return $files
}

proc find_pynq_z2_board_part {} {
    foreach board_part [get_board_parts -quiet] {
        set name [string tolower [get_property NAME $board_part]]
        set display [string tolower [get_property DISPLAY_NAME $board_part]]
        set vendor [string tolower [get_property VENDOR $board_part]]
        set haystack "$name $display $vendor"
        if {[string match "*pynq*z2*" $haystack] || [string match "*pynq-z2*" $haystack]} {
            return $board_part
        }
    }
    return ""
}

proc maybe_make_external_intf {pin_path external_name} {
    set pin [get_bd_intf_pins -quiet $pin_path]
    if {[llength $pin] == 0} {
        warn "interface pin not found for externalization: $pin_path"
        return
    }
    if {[catch {make_bd_intf_pins_external $pin} result]} {
        warn "could not externalize $pin_path: $result"
        return
    }
    set ports [get_bd_intf_ports -quiet ${external_name}_0]
    if {[llength $ports] == 1} {
        set_property name $external_name $ports
    }
}

proc report_stage {stage report_dir} {
    file mkdir $report_dir
    report_utilization -file [file join $report_dir utilization_${stage}.rpt]
    report_timing_summary -file [file join $report_dir timing_summary_${stage}.rpt]
    report_ram_utilization -file [file join $report_dir ram_utilization_${stage}.rpt]
    report_drc -file [file join $report_dir drc_${stage}.rpt]
    report_clocks -file [file join $report_dir clocks_${stage}.rpt]
    if {[catch {report_cdc -file [file join $report_dir cdc_${stage}.rpt]} result]} {
        warn "report_cdc failed for $stage: $result"
    }
}

proc run_checked {run_name jobs} {
    launch_runs $run_name -jobs $jobs
    wait_on_run $run_name
    set status [get_property STATUS [get_runs $run_name]]
    if {![regexp {Complete} $status]} {
        fail "$run_name did not complete successfully; Vivado status: $status"
    }
}

set script_dir [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $script_dir .. .. ..]]

set target "project"
if {[llength $argv] > 0} {
    set target [string tolower [lindex $argv 0]]
}
if {[lsearch -exact {project synth bitstream} $target] < 0} {
    fail "unknown target '$target'; expected project, synth, or bitstream"
}

set project_name "ccsds_ldpc_pynq_z2"
set bd_name "ccsds_ldpc_pynq_z2_bd"
set part [get_env_or_default PYNQ_Z2_PART "xc7z020clg400-1"]
set clk_mhz [get_env_or_default PYNQ_Z2_CLK_MHZ "100.0"]
set lanes [get_env_or_default PYNQ_Z2_LANES "8"]
set jobs [get_env_or_default PYNQ_Z2_JOBS "4"]
set project_dir [file normalize [get_env_or_default PYNQ_Z2_PROJECT_DIR [file join $repo_root results pynq_z2 vivado $project_name]]]
set report_root [file normalize [file join $repo_root results pynq_z2 reports]]
file mkdir $report_root

puts "PYNQ-Z2 target: $target"
puts "Repository root: $repo_root"
puts "Project directory: $project_dir"
puts "Part fallback: $part"
puts "Fabric clock target: $clk_mhz MHz"
puts "Decoder LANES parameter: $lanes"

if {[llength [info commands version]] == 0 || [llength [info commands create_project]] == 0} {
    fail "this script must be run by Vivado, not plain tclsh"
}

set vivado_version [version -short]
set known_versions {2020.2 2021.1 2021.2 2022.1 2022.2 2023.1 2023.2 2024.1 2024.2 2025.1}
if {[lsearch -exact $known_versions $vivado_version] < 0} {
    warn "Vivado $vivado_version is not in the documented-tested list: $known_versions"
}

require_file [file join $repo_root rtl ldpc_sources.f]
require_file [file join $repo_root rtl ldpc_axis_decoder_ip.sv]

file mkdir $project_dir
create_project -force $project_name $project_dir -part $part
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

set board_part [find_pynq_z2_board_part]
if {$board_part ne ""} {
    puts "Using installed PYNQ-Z2 board definition: $board_part"
    set_property board_part $board_part [current_project]
} else {
    warn "PYNQ-Z2 board definition was not found. Falling back to part $part."
    warn "Install the TUL PYNQ-Z2 board files before generating hardware for a board boot image."
}

set rtl_files [read_source_manifest $repo_root rtl/ldpc_sources.f]
add_files -norecurse $rtl_files
update_compile_order -fileset sources_1

create_bd_design $bd_name

set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 processing_system7_0]
if {$board_part ne ""} {
    set automation_config [list make_external "FIXED_IO, DDR" apply_board_preset "1"]
    if {[catch {apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config $automation_config $ps7} result]} {
        warn "PS7 board automation failed: $result"
        maybe_make_external_intf processing_system7_0/DDR DDR
        maybe_make_external_intf processing_system7_0/FIXED_IO FIXED_IO
    }
} else {
    maybe_make_external_intf processing_system7_0/DDR DDR
    maybe_make_external_intf processing_system7_0/FIXED_IO FIXED_IO
}

set_cell_properties_if_present $ps7 [list \
    CONFIG.PCW_USE_M_AXI_GP0 1 \
    CONFIG.PCW_USE_S_AXI_HP0 1 \
    CONFIG.PCW_EN_CLK0_PORT 1 \
    CONFIG.PCW_EN_RST0_PORT 1 \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $clk_mhz \
    CONFIG.PCW_USE_FABRIC_INTERRUPT 0 \
]

set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma axi_dma_0]
set_cell_properties_if_present $dma [list \
    CONFIG.c_include_sg 0 \
    CONFIG.c_include_mm2s 1 \
    CONFIG.c_include_s2mm 1 \
    CONFIG.c_include_mm2s_dre 0 \
    CONFIG.c_include_s2mm_dre 0 \
    CONFIG.c_sg_length_width 14 \
    CONFIG.c_m_axis_mm2s_tdata_width 32 \
    CONFIG.c_s_axis_s2mm_tdata_width 32 \
]

set decoder [create_bd_cell -type module -reference ldpc_axis_decoder_ip ldpc_axis_decoder_0]
set_cell_properties_if_present $decoder [list \
    CONFIG.LANES $lanes \
    CONFIG.MAX_ITERS 8 \
    CONFIG.LLR_W 8 \
    CONFIG.MSG_W 8 \
]

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset proc_sys_reset_0]
set_cell_properties_if_present $rst [list CONFIG.C_EXT_RESET_HIGH 0]

set axi_lite_ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect axi_lite_interconnect]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 1] $axi_lite_ic

set axi_hp_ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect axi_hp_interconnect]
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1] $axi_hp_ic

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins proc_sys_reset_0/slowest_sync_clk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins proc_sys_reset_0/ext_reset_in]

foreach pin [list \
    processing_system7_0/M_AXI_GP0_ACLK \
    processing_system7_0/S_AXI_HP0_ACLK \
    axi_dma_0/s_axi_lite_aclk \
    axi_dma_0/m_axi_mm2s_aclk \
    axi_dma_0/m_axi_s2mm_aclk \
    ldpc_axis_decoder_0/aclk \
    axi_lite_interconnect/ACLK \
    axi_lite_interconnect/S00_ACLK \
    axi_lite_interconnect/M00_ACLK \
    axi_hp_interconnect/ACLK \
    axi_hp_interconnect/S00_ACLK \
    axi_hp_interconnect/S01_ACLK \
    axi_hp_interconnect/M00_ACLK \
] {
    connect_pin_if_present processing_system7_0/FCLK_CLK0 $pin
}

foreach pin [list \
    axi_dma_0/axi_resetn \
    ldpc_axis_decoder_0/aresetn \
    axi_lite_interconnect/ARESETN \
    axi_lite_interconnect/S00_ARESETN \
    axi_lite_interconnect/M00_ARESETN \
    axi_hp_interconnect/ARESETN \
    axi_hp_interconnect/S00_ARESETN \
    axi_hp_interconnect/S01_ARESETN \
    axi_hp_interconnect/M00_ARESETN \
] {
    connect_pin_if_present proc_sys_reset_0/peripheral_aresetn $pin
}

connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_lite_interconnect/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_lite_interconnect/M00_AXI] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] [get_bd_intf_pins axi_hp_interconnect/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] [get_bd_intf_pins axi_hp_interconnect/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_hp_interconnect/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins ldpc_axis_decoder_0/s_axis]
connect_bd_intf_net [get_bd_intf_pins ldpc_axis_decoder_0/m_axis] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]

assign_bd_address [get_bd_addr_segs axi_dma_0/S_AXI_LITE/Reg]
set dma_addr_seg [get_bd_addr_segs -quiet processing_system7_0/Data/SEG_axi_dma_0_Reg]
if {[llength $dma_addr_seg] == 1} {
    set_property offset 0x40400000 $dma_addr_seg
    set_property range 64K $dma_addr_seg
} else {
    warn "could not find generated AXI DMA address segment; inspect address editor output"
}

validate_bd_design
save_bd_design

set bd_file [file join $project_dir $project_name.srcs sources_1 bd $bd_name ${bd_name}.bd]
set wrapper_path [make_wrapper -files [get_files $bd_file] -top]
add_files -norecurse $wrapper_path
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

report_compile_order -fileset sources_1 -file [file join $report_root compile_order_project.rpt]

if {$target eq "synth" || $target eq "bitstream"} {
    run_checked synth_1 $jobs
    open_run synth_1
    report_stage synth [file join $report_root synth]
}

if {$target eq "bitstream"} {
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    wait_on_run impl_1
    set impl_status [get_property STATUS [get_runs impl_1]]
    if {![regexp {write_bitstream Complete} $impl_status] && ![regexp {Complete} $impl_status]} {
        fail "impl_1 write_bitstream did not complete successfully; Vivado status: $impl_status"
    }
    open_run impl_1
    report_stage impl [file join $report_root impl]
    report_route_status -file [file join $report_root impl route_status_impl.rpt]
}

puts "PYNQ-Z2 Vivado target '$target' completed."
