`timescale 1ns/1ps

module hard_decision_unit #(
    parameter int MSG_W = 8
) (
    input  logic signed [MSG_W-1:0] llr,
    output logic                    hard_bit
);

    // Stable tie-break: zero LLR resolves to bit 0.
    always_comb begin
        hard_bit = (llr < 0);
    end

endmodule

