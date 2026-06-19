`timescale 1ns/1ps

module message_memory #(
    parameter int CHECKS = 1536,
    parameter int MAX_ROW_WEIGHT = 6,
    parameter int MSG_W = 8
) (
    input  logic                              clk,
    input  logic                              write_enable,
    input  logic [$clog2(CHECKS)-1:0]         row_index,
    input  logic [$clog2(MAX_ROW_WEIGHT)-1:0] edge_index,
    input  logic signed [MSG_W-1:0]           write_data,
    output logic signed [MSG_W-1:0]           read_data
);

    logic signed [MSG_W-1:0] mem [0:CHECKS-1][0:MAX_ROW_WEIGHT-1];

    always_ff @(posedge clk) begin
        if (write_enable) begin
            mem[row_index][edge_index] <= write_data;
        end
        read_data <= mem[row_index][edge_index];
    end

endmodule

