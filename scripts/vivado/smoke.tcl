# scripts/vivado/smoke.tcl
# Minimal "is Vivado alive and does it know the target part?" check.
# Run via:  vivado -mode batch -source scripts/vivado/smoke.tcl
puts "Vivado is working."
puts "Version: [version -short]"

set part "xc7z020clg400-1"
set matches [get_parts -quiet $part]
if {[llength $matches] == 1} {
    puts "Target part available: $part"
} else {
    puts "ERROR: target part '$part' not found in this Vivado install"
    exit 1
}
exit 0
