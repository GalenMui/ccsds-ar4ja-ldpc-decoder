`timescale 1ns/1ps

// Reference single-port synchronous RAM template. The authoritative decoder
// core currently infers its banked posterior RAMs internally.
module posterior_memory #(
    parameter int DEPTH = 2560,
    parameter int DATA_W = 8
) (
    input  logic                         clk,

    input  logic                         read_enable,
    input  logic [$clog2(DEPTH)-1:0]     read_addr,
    output logic signed [DATA_W-1:0]     read_data,

    input  logic                         write_enable,
    input  logic [$clog2(DEPTH)-1:0]     write_addr,
    input  logic signed [DATA_W-1:0]     write_data
);

    logic signed [DATA_W-1:0] mem [0:DEPTH-1];

    always_ff @(posedge clk) begin
        if (write_enable) begin
            mem[write_addr] <= write_data;
        end
        if (read_enable) begin
            read_data <= mem[read_addr];
        end
    end

endmodule
