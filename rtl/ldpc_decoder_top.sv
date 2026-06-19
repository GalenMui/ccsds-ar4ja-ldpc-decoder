`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module ldpc_decoder_top #(
    parameter int TX_N = ar4ja_1024_pkg::TX_N,
    parameter int FULL_N = ar4ja_1024_pkg::FULL_N,
    parameter int K_BITS = ar4ja_1024_pkg::INFO_N,
    parameter int CHECKS = ar4ja_1024_pkg::CHECKS,
    parameter int LLR_W = 8,
    parameter int MSG_W = 8,
    parameter int MAX_ITERS = 8,
    parameter int ALPHA_NUM = 3,
    parameter int ALPHA_DEN = 4
) (
    input  logic clk,
    input  logic rst,

    input  logic start,
    input  logic [TX_N*LLR_W-1:0] llr_in_flat,
    output logic busy,
    output logic done,

    output logic [K_BITS-1:0] decoded_bits,
    output logic syndrome_pass,
    output logic decoder_success,
    output logic decoder_fail,
    output logic [$clog2(MAX_ITERS+1)-1:0] iterations_used,
    output logic [31:0] cycles_elapsed,
    output logic [31:0] saturation_count
);

    typedef enum logic [2:0] {
        S_IDLE,
        S_INIT,
        S_INITIAL_CHECK,
        S_CHECK,
        S_VAR,
        S_HARD_CHECK,
        S_DONE
    } state_t;

    localparam integer MIN_MSG = -(1 << (MSG_W - 1));
    localparam integer MAX_MSG =  (1 << (MSG_W - 1)) - 1;

    state_t state;
    logic [TX_N*LLR_W-1:0] llr_latched;
    logic signed [MSG_W-1:0] channel_llr [0:FULL_N-1];
    logic signed [MSG_W-1:0] posterior_llr [0:FULL_N-1];
    logic signed [MSG_W-1:0] v_to_c [0:CHECKS-1][0:ar4ja_1024_pkg::MAX_ROW_WEIGHT-1];
    logic signed [MSG_W-1:0] c_to_v [0:CHECKS-1][0:ar4ja_1024_pkg::MAX_ROW_WEIGHT-1];
    logic [FULL_N-1:0] hard_full;
    integer total_accum [0:FULL_N-1];

    integer init_col_idx;
    integer init_row_idx;
    integer init_edge_idx;
    integer row_idx;
    integer edge_idx;
    integer degree;
    integer sign_product;
    integer abs_value;
    integer min1;
    integer min2;
    integer min1_idx;
    integer selected_min;
    integer scaled_value;
    integer signed_value;
    integer clipped_value;
    integer total_value;
    integer msg_value;
    integer saturation_next;
    integer syndrome_any;
    integer row_syndrome;
    integer syndrome_calc;

    function automatic integer clip_msg(input integer value);
        begin
            if (value < MIN_MSG) begin
                clip_msg = MIN_MSG;
            end else if (value > MAX_MSG) begin
                clip_msg = MAX_MSG;
            end else begin
                clip_msg = value;
            end
        end
    endfunction

    function automatic integer llr_value_for_col(input integer col);
        reg signed [LLR_W-1:0] raw_llr;
        begin
            if (col < TX_N) begin
                // llr_in_flat packs codeword index 0 at bits [LLR_W-1:0].
                raw_llr = llr_latched[col*LLR_W +: LLR_W];
                llr_value_for_col = clip_msg(raw_llr);
            end else begin
                // Punctured variables are internal unknowns, so their channel
                // evidence is neutral rather than forced to a hard zero bit.
                llr_value_for_col = 0;
            end
        end
    endfunction

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= S_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            decoded_bits <= '0;
            syndrome_pass <= 1'b0;
            decoder_success <= 1'b0;
            decoder_fail <= 1'b0;
            iterations_used <= '0;
            cycles_elapsed <= 32'd0;
            saturation_count <= 32'd0;
            row_idx <= 0;
        end else begin
            if (busy && !done) begin
                cycles_elapsed <= cycles_elapsed + 32'd1;
            end

            case (state)
                S_IDLE: begin
                    busy <= 1'b0;
                    done <= 1'b0;
                    syndrome_pass <= 1'b0;
                    decoder_success <= 1'b0;
                    decoder_fail <= 1'b0;
                    if (start) begin
                        llr_latched <= llr_in_flat;
                        cycles_elapsed <= 32'd0;
                        saturation_count <= 32'd0;
                        iterations_used <= '0;
                        busy <= 1'b1;
                        state <= S_INIT;
                    end
                end

                S_INIT: begin
                    for (init_col_idx = 0; init_col_idx < FULL_N; init_col_idx = init_col_idx + 1) begin
                        clipped_value = llr_value_for_col(init_col_idx);
                        channel_llr[init_col_idx] <= clipped_value[MSG_W-1:0];
                        posterior_llr[init_col_idx] <= clipped_value[MSG_W-1:0];
                        hard_full[init_col_idx] <= (clipped_value < 0);
                    end
                    for (init_row_idx = 0; init_row_idx < CHECKS; init_row_idx = init_row_idx + 1) begin
                        for (
                            init_edge_idx = 0;
                            init_edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                            init_edge_idx = init_edge_idx + 1
                        ) begin
                            c_to_v[init_row_idx][init_edge_idx] <= '0;
                            if (init_edge_idx < ar4ja_1024_pkg::row_weight(init_row_idx)) begin
                                clipped_value =
                                    llr_value_for_col(ar4ja_1024_pkg::row_col(init_row_idx, init_edge_idx));
                                v_to_c[init_row_idx][init_edge_idx] <= clipped_value[MSG_W-1:0];
                            end else begin
                                v_to_c[init_row_idx][init_edge_idx] <= '0;
                            end
                        end
                    end
                    state <= S_INITIAL_CHECK;
                end

                S_INITIAL_CHECK: begin
                    syndrome_any = 0;
                    for (init_row_idx = 0; init_row_idx < CHECKS; init_row_idx = init_row_idx + 1) begin
                        row_syndrome = 0;
                        for (
                            init_edge_idx = 0;
                            init_edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                            init_edge_idx = init_edge_idx + 1
                        ) begin
                            if (init_edge_idx < ar4ja_1024_pkg::row_weight(init_row_idx)) begin
                                row_syndrome =
                                    row_syndrome ^
                                    hard_full[ar4ja_1024_pkg::row_col(init_row_idx, init_edge_idx)];
                            end
                        end
                        syndrome_any = syndrome_any | row_syndrome;
                    end
                    syndrome_calc = (syndrome_any == 0);
                    syndrome_pass <= syndrome_calc[0];
                    if (syndrome_calc || MAX_ITERS == 0) begin
                        for (init_col_idx = 0; init_col_idx < K_BITS; init_col_idx = init_col_idx + 1) begin
                            decoded_bits[init_col_idx] <= hard_full[init_col_idx];
                        end
                        decoder_success <= syndrome_calc[0];
                        decoder_fail <= ~syndrome_calc[0];
                        state <= S_DONE;
                    end else begin
                        iterations_used <= {{($bits(iterations_used)-1){1'b0}}, 1'b1};
                        row_idx <= 0;
                        state <= S_CHECK;
                    end
                end

                S_CHECK: begin
                    saturation_next = saturation_count;
                    degree = ar4ja_1024_pkg::row_weight(row_idx);
                    sign_product = 1;
                    min1 = 32'h3fffffff;
                    min2 = 32'h3fffffff;
                    min1_idx = 0;

                    for (
                        edge_idx = 0;
                        edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                        edge_idx = edge_idx + 1
                    ) begin
                        if (edge_idx < degree) begin
                            if (v_to_c[row_idx][edge_idx] < 0) begin
                                sign_product = -sign_product;
                                abs_value = -v_to_c[row_idx][edge_idx];
                            end else begin
                                abs_value = v_to_c[row_idx][edge_idx];
                            end

                            if (abs_value < min1) begin
                                min2 = min1;
                                min1 = abs_value;
                                min1_idx = edge_idx;
                            end else if (abs_value < min2) begin
                                min2 = abs_value;
                            end
                        end
                    end

                    for (
                        edge_idx = 0;
                        edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                        edge_idx = edge_idx + 1
                    ) begin
                        if (edge_idx < degree) begin
                            selected_min = (edge_idx == min1_idx) ? min2 : min1;
                            scaled_value = (selected_min * ALPHA_NUM) / ALPHA_DEN;
                            if ((sign_product < 0 && v_to_c[row_idx][edge_idx] >= 0) ||
                                (sign_product > 0 && v_to_c[row_idx][edge_idx] < 0)) begin
                                signed_value = -scaled_value;
                            end else begin
                                signed_value = scaled_value;
                            end
                            clipped_value = clip_msg(signed_value);
                            if (clipped_value != signed_value) begin
                                saturation_next = saturation_next + 1;
                            end
                            c_to_v[row_idx][edge_idx] <= clipped_value[MSG_W-1:0];
                        end
                    end
                    saturation_count <= saturation_next[31:0];

                    if (row_idx == CHECKS - 1) begin
                        state <= S_VAR;
                    end else begin
                        row_idx <= row_idx + 1;
                    end
                end

                S_VAR: begin
                    saturation_next = saturation_count;

                    for (init_col_idx = 0; init_col_idx < FULL_N; init_col_idx = init_col_idx + 1) begin
                        total_accum[init_col_idx] = channel_llr[init_col_idx];
                    end

                    for (init_row_idx = 0; init_row_idx < CHECKS; init_row_idx = init_row_idx + 1) begin
                        for (
                            init_edge_idx = 0;
                            init_edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                            init_edge_idx = init_edge_idx + 1
                        ) begin
                            if (init_edge_idx < ar4ja_1024_pkg::row_weight(init_row_idx)) begin
                                init_col_idx = ar4ja_1024_pkg::row_col(init_row_idx, init_edge_idx);
                                total_accum[init_col_idx] =
                                    total_accum[init_col_idx] + c_to_v[init_row_idx][init_edge_idx];
                            end
                        end
                    end

                    for (init_col_idx = 0; init_col_idx < FULL_N; init_col_idx = init_col_idx + 1) begin
                        clipped_value = clip_msg(total_accum[init_col_idx]);
                        if (clipped_value != total_accum[init_col_idx]) begin
                            saturation_next = saturation_next + 1;
                        end
                        total_accum[init_col_idx] = clipped_value;
                        posterior_llr[init_col_idx] <= clipped_value[MSG_W-1:0];
                        hard_full[init_col_idx] <= (clipped_value < 0);
                    end

                    for (init_row_idx = 0; init_row_idx < CHECKS; init_row_idx = init_row_idx + 1) begin
                        for (
                            init_edge_idx = 0;
                            init_edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                            init_edge_idx = init_edge_idx + 1
                        ) begin
                            if (init_edge_idx < ar4ja_1024_pkg::row_weight(init_row_idx)) begin
                                init_col_idx = ar4ja_1024_pkg::row_col(init_row_idx, init_edge_idx);
                                msg_value = total_accum[init_col_idx] - c_to_v[init_row_idx][init_edge_idx];
                                signed_value = clip_msg(msg_value);
                                if (signed_value != msg_value) begin
                                    saturation_next = saturation_next + 1;
                                end
                                v_to_c[init_row_idx][init_edge_idx] <= signed_value[MSG_W-1:0];
                            end
                        end
                    end
                    saturation_count <= saturation_next[31:0];

                    state <= S_HARD_CHECK;
                end

                S_HARD_CHECK: begin
                    syndrome_any = 0;
                    for (init_row_idx = 0; init_row_idx < CHECKS; init_row_idx = init_row_idx + 1) begin
                        row_syndrome = 0;
                        for (
                            init_edge_idx = 0;
                            init_edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                            init_edge_idx = init_edge_idx + 1
                        ) begin
                            if (init_edge_idx < ar4ja_1024_pkg::row_weight(init_row_idx)) begin
                                row_syndrome =
                                    row_syndrome ^
                                    hard_full[ar4ja_1024_pkg::row_col(init_row_idx, init_edge_idx)];
                            end
                        end
                        syndrome_any = syndrome_any | row_syndrome;
                    end
                    syndrome_calc = (syndrome_any == 0);
                    syndrome_pass <= syndrome_calc[0];
                    if (syndrome_calc || iterations_used == MAX_ITERS[$bits(iterations_used)-1:0]) begin
                        for (init_col_idx = 0; init_col_idx < K_BITS; init_col_idx = init_col_idx + 1) begin
                            decoded_bits[init_col_idx] <= hard_full[init_col_idx];
                        end
                        decoder_success <= syndrome_calc[0];
                        decoder_fail <= ~syndrome_calc[0];
                        state <= S_DONE;
                    end else begin
                        iterations_used <= iterations_used + 1'b1;
                        row_idx <= 0;
                        state <= S_CHECK;
                    end
                end

                S_DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    if (!start) begin
                        state <= S_IDLE;
                    end
                end

                default: begin
                    state <= S_IDLE;
                end
            endcase
        end
    end

endmodule
