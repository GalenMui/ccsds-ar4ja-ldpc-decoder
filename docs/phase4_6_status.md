# Phase 4-6 Status

The behavioral flooding decoder has been replaced by a memory-oriented layered
normalized min-sum baseline.

Current active RTL:

- `rtl/ar4ja_1024_pkg.sv`
- `rtl/posterior_memory.sv`
- `rtl/message_memory.sv`
- `rtl/ldpc_decoder_top.sv`
- `rtl/ldpc_axis_wrapper.sv`
- `rtl/ldpc_axis_decoder_ip.sv`
- `rtl/syndrome_checker.sv` for standalone syndrome tests

Removed obsolete helper modules:

- `check_node_unit.sv`
- `variable_node_unit.sv`
- `ldpc_controller.sv`
- `llr_input_loader.sv`
- `decoded_output_packer.sv`
- `fixed_point_sat.sv`
- `hard_decision_unit.sv`

Latest expected verification command:

```sh
python3 scripts/run_regression.py
```

Vendor synthesis remains unmeasured until Vivado is available with a selected
FPGA part.
