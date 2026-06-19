`timescale 1ns/1ps

module llr_input_loader #(
    parameter int TX_N = 2048,
    parameter int LLR_W = 8,
    parameter int WORD_W = 32
) (
    input  logic [TX_N*LLR_W-1:0] llr_flat_in,
    input  logic [$clog2(TX_N/4)-1:0] word_index,
    input  logic [WORD_W-1:0] word_data,
    input  logic load_word,
    output logic [TX_N*LLR_W-1:0] llr_flat_out
);

    integer lane;
    integer llr_index;

    always_comb begin
        llr_flat_out = llr_flat_in;
        if (load_word) begin
            for (lane = 0; lane < 4; lane = lane + 1) begin
                llr_index = (word_index * 4) + lane;
                llr_flat_out[llr_index*LLR_W +: LLR_W] = word_data[lane*LLR_W +: LLR_W];
            end
        end
    end

endmodule

