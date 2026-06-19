`timescale 1ns/1ps

module fixed_point_sat #(
    parameter int IN_W = 16,
    parameter int OUT_W = 8
) (
    input  logic signed [IN_W-1:0]  value,
    output logic signed [OUT_W-1:0] clipped,
    output logic                    saturated
);

    localparam integer MIN_VALUE = -(1 << (OUT_W - 1));
    localparam integer MAX_VALUE =  (1 << (OUT_W - 1)) - 1;

    always_comb begin
        if (value < MIN_VALUE) begin
            clipped = MIN_VALUE[OUT_W-1:0];
            saturated = 1'b1;
        end else if (value > MAX_VALUE) begin
            clipped = MAX_VALUE[OUT_W-1:0];
            saturated = 1'b1;
        end else begin
            clipped = value[OUT_W-1:0];
            saturated = 1'b0;
        end
    end

endmodule
