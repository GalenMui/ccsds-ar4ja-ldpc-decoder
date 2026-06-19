`timescale 1ns/1ps

module decoded_output_packer #(
    parameter int K_BITS = 1024
) (
    input  logic [5:0] word_index,
    input  logic decoder_success,
    input  logic syndrome_pass,
    input  logic [31:0] iterations_used,
    input  logic [31:0] cycles_elapsed,
    input  logic decoder_fail,
    input  logic [31:0] saturation_count,
    input  logic [K_BITS-1:0] decoded_bits,
    output logic [31:0] word_data
);

    always_comb begin
        case (word_index)
            6'd0: word_data = 32'h4c445043;
            6'd1: word_data = {31'd0, decoder_success};
            6'd2: word_data = {31'd0, syndrome_pass};
            6'd3: word_data = iterations_used;
            6'd4: word_data = cycles_elapsed;
            6'd5: word_data = {31'd0, decoder_fail};
            6'd6: word_data = saturation_count;
            6'd7: word_data = 32'd0;
            default: begin
                if (word_index >= 6'd8 && word_index < 6'd40) begin
                    word_data = decoded_bits[(word_index - 6'd8) * 32 +: 32];
                end else begin
                    word_data = 32'd0;
                end
            end
        endcase
    end

endmodule

