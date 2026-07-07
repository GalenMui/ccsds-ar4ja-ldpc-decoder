`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module ldpc_axis_wrapper #(
    parameter int TX_N = ar4ja_1024_pkg::TX_N,
    parameter int K_BITS = ar4ja_1024_pkg::INFO_N,
    parameter int LLR_W = 8,
    parameter int MSG_W = 8,
    parameter int MAX_ITERS = 8,
    parameter int LANES = 8
) (
    input  logic clk,
    input  logic rst,

    input  logic        s_axis_tvalid,
    output logic        s_axis_tready,
    input  logic [31:0] s_axis_tdata,
    input  logic [3:0]  s_axis_tkeep,
    input  logic        s_axis_tlast,

    output logic        m_axis_tvalid,
    input  logic        m_axis_tready,
    output logic [31:0] m_axis_tdata,
    output logic [3:0]  m_axis_tkeep,
    output logic        m_axis_tlast,

    output logic        frame_error,
    output logic        early_tlast_error,
    output logic        missing_tlast_error,
    output logic        tkeep_error
);

    localparam int LLR_PER_WORD = 32 / LLR_W;
    localparam int INPUT_WORDS = TX_N / LLR_PER_WORD;
    localparam int INPUT_WORD_BITS = $clog2(INPUT_WORDS);
    localparam int LANE_BITS = $clog2(LLR_PER_WORD);
    localparam int PAYLOAD_OUTPUT_WORDS = K_BITS / 32;
    localparam int OUTPUT_WORDS = 8 + PAYLOAD_OUTPUT_WORDS;
    localparam int OUTPUT_WORD_BITS = $clog2(OUTPUT_WORDS);
    localparam logic [3:0] KEEP_ALL = 4'hf;

    typedef enum logic [2:0] {
        W_IDLE,
        W_UNPACK,
        W_START,
        W_DECODE,
        W_OUTPUT,
        W_DRAIN
    } wrapper_state_t;

    wrapper_state_t state;

    logic [31:0] input_word_hold;
    logic input_last_hold;
    logic [INPUT_WORD_BITS-1:0] input_word_count;
    logic [LANE_BITS-1:0] lane_count;
    logic drain_after_output;

    logic core_llr_write_valid;
    logic core_llr_write_ready;
    logic [$clog2(TX_N)-1:0] core_llr_write_addr;
    logic signed [LLR_W-1:0] core_llr_write_data;
    logic core_llr_load_clear;
    logic core_start;
    logic core_busy;
    logic core_done;
    logic [K_BITS-1:0] core_bits;
    logic core_syndrome_pass;
    logic core_success;
    logic core_fail;
    logic [$clog2(MAX_ITERS+1)-1:0] core_iterations;
    logic [31:0] core_cycles;
    logic [31:0] core_saturation;

    logic [K_BITS-1:0] out_bits;
    logic out_success;
    logic out_syndrome_pass;
    logic out_fail;
    logic [31:0] out_iterations;
    logic [31:0] out_cycles;
    logic [31:0] out_saturation;
    logic [OUTPUT_WORD_BITS-1:0] output_word_count;

    assign s_axis_tready = (state == W_IDLE) || (state == W_DRAIN);
    assign core_llr_write_valid = (state == W_UNPACK);
    assign core_llr_write_addr =
        (({{($clog2(TX_N)-INPUT_WORD_BITS){1'b0}}, input_word_count}) << LANE_BITS) +
        {{($clog2(TX_N)-LANE_BITS){1'b0}}, lane_count};
    assign core_llr_write_data = input_word_hold[lane_count * LLR_W +: LLR_W];

    initial begin
        if ((32 % LLR_W) != 0) $fatal(1, "LLR_W must divide the 32-bit AXI word");
        if ((TX_N % LLR_PER_WORD) != 0) $fatal(1, "TX_N must be divisible by LLRs per AXI word");
        if ((K_BITS % 32) != 0) $fatal(1, "K_BITS must be divisible by 32");
    end

    ldpc_decoder_top #(
        .TX_N(TX_N),
        .K_BITS(K_BITS),
        .LLR_W(LLR_W),
        .MSG_W(MSG_W),
        .MAX_ITERS(MAX_ITERS),
        .LANES(LANES)
    ) decoder (
        .clk(clk),
        .rst(rst),
        .llr_write_valid(core_llr_write_valid),
        .llr_write_ready(core_llr_write_ready),
        .llr_write_addr(core_llr_write_addr),
        .llr_write_data(core_llr_write_data),
        .llr_load_clear(core_llr_load_clear),
        .start(core_start),
        .busy(core_busy),
        .done(core_done),
        .decoded_bits(core_bits),
        .syndrome_pass(core_syndrome_pass),
        .decoder_success(core_success),
        .decoder_fail(core_fail),
        .iterations_used(core_iterations),
        .cycles_elapsed(core_cycles),
        .saturation_count(core_saturation)
    );

    function automatic [31:0] output_word(input logic [OUTPUT_WORD_BITS-1:0] word_index);
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
                default: output_word = out_bits[(word_index - 8) * 32 +: 32];
            endcase
        end
    endfunction

    task automatic prepare_error_output(input logic drain_after);
        begin
            out_bits <= '0;
            out_success <= 1'b0;
            out_syndrome_pass <= 1'b0;
            out_fail <= 1'b1;
            out_iterations <= 32'd0;
            out_cycles <= 32'd0;
            out_saturation <= 32'd0;
            output_word_count <= '0;
            m_axis_tvalid <= 1'b1;
            m_axis_tdata <= 32'h4c445043;
            m_axis_tkeep <= KEEP_ALL;
            m_axis_tlast <= (OUTPUT_WORDS == 1);
            drain_after_output <= drain_after;
            input_word_count <= '0;
            lane_count <= '0;
            input_last_hold <= 1'b0;
        end
    endtask

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= W_IDLE;
            input_word_hold <= 32'd0;
            input_last_hold <= 1'b0;
            input_word_count <= '0;
            lane_count <= '0;
            drain_after_output <= 1'b0;
            core_llr_load_clear <= 1'b0;
            core_start <= 1'b0;
            frame_error <= 1'b0;
            early_tlast_error <= 1'b0;
            missing_tlast_error <= 1'b0;
            tkeep_error <= 1'b0;
            out_bits <= '0;
            out_success <= 1'b0;
            out_syndrome_pass <= 1'b0;
            out_fail <= 1'b0;
            out_iterations <= 32'd0;
            out_cycles <= 32'd0;
            out_saturation <= 32'd0;
            output_word_count <= '0;
            m_axis_tvalid <= 1'b0;
            m_axis_tdata <= 32'd0;
            m_axis_tkeep <= 4'd0;
            m_axis_tlast <= 1'b0;
        end else begin
            core_start <= 1'b0;
            core_llr_load_clear <= 1'b0;

            case (state)
                W_IDLE: begin
                    m_axis_tvalid <= 1'b0;
                    m_axis_tlast <= 1'b0;
                    output_word_count <= '0;
                    if (s_axis_tvalid && s_axis_tready) begin
                        frame_error <= 1'b0;
                        early_tlast_error <= 1'b0;
                        missing_tlast_error <= 1'b0;
                        tkeep_error <= 1'b0;
                        input_word_hold <= s_axis_tdata;
                        input_last_hold <= s_axis_tlast;
                        lane_count <= '0;
                        if (s_axis_tkeep != KEEP_ALL) begin
                            frame_error <= 1'b1;
                            tkeep_error <= 1'b1;
                            core_llr_load_clear <= 1'b1;
                            prepare_error_output(!s_axis_tlast);
                            state <= W_OUTPUT;
                        end else if (s_axis_tlast && input_word_count != INPUT_WORDS - 1) begin
                            frame_error <= 1'b1;
                            early_tlast_error <= 1'b1;
                            core_llr_load_clear <= 1'b1;
                            prepare_error_output(1'b0);
                            state <= W_OUTPUT;
                        end else begin
                            state <= W_UNPACK;
                        end
                    end
                end

                W_UNPACK: begin
                    if (core_llr_write_ready) begin
                        if (lane_count == LLR_PER_WORD - 1) begin
                            lane_count <= '0;
                            if (input_word_count == INPUT_WORDS - 1) begin
                                if (input_last_hold) begin
                                    state <= W_START;
                                end else begin
                                    frame_error <= 1'b1;
                                    missing_tlast_error <= 1'b1;
                                    core_llr_load_clear <= 1'b1;
                                    prepare_error_output(1'b1);
                                    state <= W_OUTPUT;
                                end
                            end else if (input_last_hold) begin
                                frame_error <= 1'b1;
                                early_tlast_error <= 1'b1;
                                core_llr_load_clear <= 1'b1;
                                prepare_error_output(1'b0);
                                state <= W_OUTPUT;
                            end else begin
                                input_word_count <= input_word_count + 1'b1;
                                state <= W_IDLE;
                            end
                        end else begin
                            lane_count <= lane_count + 1'b1;
                        end
                    end
                end

                W_START: begin
                    input_word_count <= '0;
                    core_start <= 1'b1;
                    state <= W_DECODE;
                end

                W_DECODE: begin
                    if (core_done) begin
                        out_bits <= core_bits;
                        out_success <= core_success;
                        out_syndrome_pass <= core_syndrome_pass;
                        out_fail <= core_fail;
                        out_iterations <= {{(32-$bits(core_iterations)){1'b0}}, core_iterations};
                        out_cycles <= core_cycles;
                        out_saturation <= core_saturation;
                        output_word_count <= '0;
                        drain_after_output <= 1'b0;
                        m_axis_tvalid <= 1'b1;
                        m_axis_tdata <= 32'h4c445043;
                        m_axis_tkeep <= KEEP_ALL;
                        m_axis_tlast <= (OUTPUT_WORDS == 1);
                        state <= W_OUTPUT;
                    end
                end

                W_OUTPUT: begin
                    if (m_axis_tvalid && m_axis_tready) begin
                        if (output_word_count == OUTPUT_WORDS - 1) begin
                            output_word_count <= '0;
                            m_axis_tvalid <= 1'b0;
                            m_axis_tkeep <= 4'd0;
                            m_axis_tlast <= 1'b0;
                            state <= drain_after_output ? W_DRAIN : W_IDLE;
                        end else begin
                            output_word_count <= output_word_count + 1'b1;
                            m_axis_tdata <= output_word(output_word_count + 1'b1);
                            m_axis_tkeep <= KEEP_ALL;
                            m_axis_tlast <= (output_word_count + 1'b1 == OUTPUT_WORDS - 1);
                        end
                    end
                end

                W_DRAIN: begin
                    if (s_axis_tvalid && s_axis_tready && s_axis_tlast) begin
                        input_word_count <= '0;
                        lane_count <= '0;
                        drain_after_output <= 1'b0;
                        core_llr_load_clear <= 1'b1;
                        state <= W_IDLE;
                    end
                end

                default: begin
                    state <= W_IDLE;
                end
            endcase
        end
    end

`ifdef LDPC_ENABLE_ASSERTS
    logic [31:0] stalled_tdata;
    logic [3:0] stalled_tkeep;
    logic stalled_tlast;

    always @(posedge clk) begin
        if (rst) begin
            stalled_tdata <= 32'd0;
            stalled_tkeep <= 4'd0;
            stalled_tlast <= 1'b0;
        end else begin
            if (m_axis_tvalid && !m_axis_tready) begin
                if (stalled_tdata !== 32'd0 || stalled_tkeep !== 4'd0 || stalled_tlast !== 1'b0) begin
                    assert (m_axis_tdata == stalled_tdata);
                    assert (m_axis_tkeep == stalled_tkeep);
                    assert (m_axis_tlast == stalled_tlast);
                end
                stalled_tdata <= m_axis_tdata;
                stalled_tkeep <= m_axis_tkeep;
                stalled_tlast <= m_axis_tlast;
            end else begin
                stalled_tdata <= 32'd0;
                stalled_tkeep <= 4'd0;
                stalled_tlast <= 1'b0;
            end
            assert (!(m_axis_tlast && !m_axis_tvalid));
            assert (!(m_axis_tvalid && m_axis_tkeep != KEEP_ALL));
            assert (!(core_start && frame_error));
        end
    end
`endif

endmodule
