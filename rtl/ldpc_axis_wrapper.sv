`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module ldpc_axis_wrapper #(
    parameter int TX_N = ar4ja_1024_pkg::TX_N,
    parameter int K_BITS = ar4ja_1024_pkg::INFO_N,
    parameter int LLR_W = 8,
    parameter int MSG_W = 8,
    parameter int MAX_ITERS = 8
) (
    input  logic clk,
    input  logic rst,

    input  logic        s_axis_tvalid,
    output logic        s_axis_tready,
    input  logic [31:0] s_axis_tdata,
    input  logic        s_axis_tlast,

    output logic        m_axis_tvalid,
    input  logic        m_axis_tready,
    output logic [31:0] m_axis_tdata,
    output logic        m_axis_tlast,

    output logic        frame_error,
    output logic        early_tlast_error,
    output logic        missing_tlast_error
);

    localparam int LLR_PER_WORD = 32 / LLR_W;
    localparam int INPUT_WORDS = TX_N / LLR_PER_WORD;
    localparam int OUTPUT_WORDS = 40;

    typedef enum logic [2:0] {
        W_IDLE,
        W_LOAD,
        W_START,
        W_DECODE,
        W_OUTPUT
    } wrapper_state_t;

    wrapper_state_t state;
    logic [TX_N*LLR_W-1:0] llr_flat;
    logic decoder_start;
    logic decoder_busy;
    logic decoder_done;
    logic [K_BITS-1:0] decoder_bits;
    logic decoder_syndrome_pass;
    logic decoder_success;
    logic decoder_fail;
    logic [$clog2(MAX_ITERS+1)-1:0] decoder_iterations;
    logic [31:0] decoder_cycles;
    logic [31:0] decoder_saturation;

    logic [K_BITS-1:0] out_bits;
    logic out_success;
    logic out_syndrome_pass;
    logic out_fail;
    logic [31:0] out_iterations;
    logic [31:0] out_cycles;
    logic [31:0] out_saturation;

    integer input_word_count = 0;
    logic [5:0] output_word_count = 6'd0;
    integer lane;
    integer llr_index;

    assign s_axis_tready = (state == W_IDLE || state == W_LOAD);

    ldpc_decoder_top #(
        .LLR_W(LLR_W),
        .MSG_W(MSG_W),
        .MAX_ITERS(MAX_ITERS)
    ) decoder (
        .clk(clk),
        .rst(rst),
        .start(decoder_start),
        .llr_in_flat(llr_flat),
        .busy(decoder_busy),
        .done(decoder_done),
        .decoded_bits(decoder_bits),
        .syndrome_pass(decoder_syndrome_pass),
        .decoder_success(decoder_success),
        .decoder_fail(decoder_fail),
        .iterations_used(decoder_iterations),
        .cycles_elapsed(decoder_cycles),
        .saturation_count(decoder_saturation)
    );

    function automatic [31:0] output_word(input integer word_index);
        begin
            case (word_index)
                0: output_word = 32'h4c445043;
                1: output_word = {31'd0, out_success};
                2: output_word = {31'd0, out_syndrome_pass};
                3: output_word = out_iterations;
                4: output_word = out_cycles;
                5: output_word = {31'd0, out_fail};
                6: output_word = out_saturation;
                7: output_word = 32'd0;
                default: begin
                    if (word_index >= 8 && word_index < OUTPUT_WORDS) begin
                        output_word = out_bits[(word_index - 8) * 32 +: 32];
                    end else begin
                        output_word = 32'd0;
                    end
                end
            endcase
        end
    endfunction

    task automatic load_input_word(input integer word_index, input logic [31:0] word_data);
        begin
            for (lane = 0; lane < LLR_PER_WORD; lane = lane + 1) begin
                llr_index = (word_index * LLR_PER_WORD) + lane;
                // Lane 0 carries the lowest codeword index in the word.
                llr_flat[llr_index*LLR_W +: LLR_W] <= word_data[lane*LLR_W +: LLR_W];
            end
        end
    endtask

    task automatic prepare_error_output;
        begin
            out_bits <= '0;
            out_success <= 1'b0;
            out_syndrome_pass <= 1'b0;
            out_fail <= 1'b1;
            out_iterations <= 32'd0;
            out_cycles <= 32'd0;
            out_saturation <= 32'd0;
            output_word_count <= 0;
        end
    endtask

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= W_IDLE;
            llr_flat <= '0;
            decoder_start <= 1'b0;
            input_word_count <= 0;
            output_word_count <= 0;
            frame_error <= 1'b0;
            early_tlast_error <= 1'b0;
            missing_tlast_error <= 1'b0;
            out_bits <= '0;
            out_success <= 1'b0;
            out_syndrome_pass <= 1'b0;
            out_fail <= 1'b0;
            out_iterations <= 32'd0;
            out_cycles <= 32'd0;
            out_saturation <= 32'd0;
            m_axis_tvalid <= 1'b0;
            m_axis_tdata <= 32'd0;
            m_axis_tlast <= 1'b0;
        end else begin
            decoder_start <= 1'b0;

            case (state)
                W_IDLE: begin
                    m_axis_tvalid <= 1'b0;
                    m_axis_tlast <= 1'b0;
                    frame_error <= 1'b0;
                    early_tlast_error <= 1'b0;
                    missing_tlast_error <= 1'b0;
                    input_word_count <= 0;
                    output_word_count <= 0;
                    if (s_axis_tvalid && s_axis_tready) begin
                        load_input_word(0, s_axis_tdata);
                        input_word_count <= 1;
                        if (s_axis_tlast) begin
                            frame_error <= 1'b1;
                            early_tlast_error <= 1'b1;
                            prepare_error_output();
                            m_axis_tvalid <= 1'b1;
                            m_axis_tdata <= 32'h4c445043;
                            m_axis_tlast <= 1'b0;
                            state <= W_OUTPUT;
                        end else begin
                            state <= W_LOAD;
                        end
                    end
                end

                W_LOAD: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        load_input_word(input_word_count, s_axis_tdata);
                        if (input_word_count == INPUT_WORDS - 1) begin
                            if (s_axis_tlast) begin
                                state <= W_START;
                            end else begin
                                frame_error <= 1'b1;
                                missing_tlast_error <= 1'b1;
                                prepare_error_output();
                                m_axis_tvalid <= 1'b1;
                                m_axis_tdata <= 32'h4c445043;
                                m_axis_tlast <= 1'b0;
                                state <= W_OUTPUT;
                            end
                        end else begin
                            input_word_count <= input_word_count + 1;
                            if (s_axis_tlast) begin
                                frame_error <= 1'b1;
                                early_tlast_error <= 1'b1;
                                prepare_error_output();
                                m_axis_tvalid <= 1'b1;
                                m_axis_tdata <= 32'h4c445043;
                                m_axis_tlast <= 1'b0;
                                state <= W_OUTPUT;
                            end
                        end
                    end
                end

                W_START: begin
                    decoder_start <= 1'b1;
                    state <= W_DECODE;
                end

                W_DECODE: begin
                    if (decoder_done) begin
                        out_bits <= decoder_bits;
                        out_success <= decoder_success;
                        out_syndrome_pass <= decoder_syndrome_pass;
                        out_fail <= decoder_fail;
                        out_iterations <= {{(32-$bits(decoder_iterations)){1'b0}}, decoder_iterations};
                        out_cycles <= decoder_cycles;
                        out_saturation <= decoder_saturation;
                        output_word_count <= 0;
                        m_axis_tvalid <= 1'b1;
                        m_axis_tdata <= 32'h4c445043;
                        m_axis_tlast <= 1'b0;
                        state <= W_OUTPUT;
                    end
                end

                W_OUTPUT: begin
                    if (m_axis_tvalid && m_axis_tready) begin
                        if (output_word_count == OUTPUT_WORDS - 1) begin
                            output_word_count <= 0;
                            m_axis_tvalid <= 1'b0;
                            m_axis_tlast <= 1'b0;
                            state <= W_IDLE;
                        end else begin
                            output_word_count <= output_word_count + 1;
                            m_axis_tdata <= output_word(output_word_count + 1);
                            m_axis_tlast <= (output_word_count + 1 == OUTPUT_WORDS - 1);
                        end
                    end
                end
            endcase
        end
    end

endmodule
