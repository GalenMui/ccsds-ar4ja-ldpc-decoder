`timescale 1ns/1ps

module message_memory #(
    parameter int ROWS = 1536,
    parameter int ROW_W = 48
) (
    input  logic                         clk,

    input  logic                         read_enable,
    input  logic [$clog2(ROWS)-1:0]      read_row,
    output logic [ROW_W-1:0]             read_data,

    input  logic                         write_enable,
    input  logic [$clog2(ROWS)-1:0]      write_row,
    input  logic [ROW_W-1:0]             write_data
);

    logic [ROW_W-1:0] mem [0:ROWS-1];

    always_ff @(posedge clk) begin
        if (write_enable) begin
            mem[write_row] <= write_data;
        end
        if (read_enable) begin
            read_data <= mem[read_row];
        end
    end

endmodule
