`timescale 1ns/1ps

import ar4ja_1024_pkg::*;
import ldpc_schedule_pkg::*;

module ldpc_decoder_top #(
    parameter int TX_N = ar4ja_1024_pkg::TX_N,
    parameter int FULL_N = ar4ja_1024_pkg::FULL_N,
    parameter int K_BITS = ar4ja_1024_pkg::INFO_N,
    parameter int CHECKS = ar4ja_1024_pkg::CHECKS,
    parameter int LLR_W = 8,
    parameter int MSG_W = 8,
    parameter int MAX_ITERS = 8,
    parameter int ALPHA_NUM = 3,
    parameter int ALPHA_DEN = 4,
    parameter int LANES = 8
) (
    input  logic clk,
    input  logic rst,

    input  logic                         llr_write_valid,
    output logic                         llr_write_ready,
    input  logic [$clog2(TX_N)-1:0]      llr_write_addr,
    input  logic signed [LLR_W-1:0]      llr_write_data,
    input  logic                         llr_load_clear,

    input  logic start,
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

    localparam int P = ((LANES == 1) || (LANES == 8) || (LANES == 16)) ? LANES : 1;
    localparam int MAX_ROW_WEIGHT = ar4ja_1024_pkg::MAX_ROW_WEIGHT;
    localparam int ROW_MSG_W = MAX_ROW_WEIGHT * MSG_W;
    localparam int ROW_BITS = $clog2(CHECKS);
    localparam int COL_BITS = $clog2(FULL_N);
    localparam int TX_ADDR_BITS = $clog2(TX_N);
    localparam int EDGE_BITS = $clog2(MAX_ROW_WEIGHT);
    localparam int DEGREE_BITS = $clog2(MAX_ROW_WEIGHT + 1);
    localparam int GROUPS = CHECKS / P;
    localparam int GROUP_BITS = (GROUPS > 1) ? $clog2(GROUPS) : 1;
    localparam int BANK_DEPTH = FULL_N / P;
    localparam int BANK_ADDR_BITS = (BANK_DEPTH > 1) ? $clog2(BANK_DEPTH) : 1;
    localparam int BANK_BITS = (P > 1) ? $clog2(P) : 1;
    localparam int PUNCTURED_GROUPS = ar4ja_1024_pkg::PUNCTURED_N / P;
    localparam int PUNCTURED_GROUP_BITS = (PUNCTURED_GROUPS > 1) ? $clog2(PUNCTURED_GROUPS) : 1;
    localparam int OUTPUT_WORDS = K_BITS / 32;
    localparam int OUTPUT_BITS = $clog2(OUTPUT_WORDS);
    localparam int Q_W = ((LLR_W > MSG_W) ? LLR_W : MSG_W) + 1;
    localparam int MAG_W = Q_W + 1;
    localparam int SCALE_W = MAG_W + 2;
    localparam int SAT_W = Q_W + 3;
    localparam logic signed [SAT_W-1:0] MSG_MIN_VALUE = -(1 <<< (MSG_W - 1));
    localparam logic signed [SAT_W-1:0] MSG_MAX_VALUE =  (1 <<< (MSG_W - 1)) - 1;
    localparam logic signed [SAT_W-1:0] LLR_MIN_VALUE = -(1 <<< (LLR_W - 1));
    localparam logic signed [SAT_W-1:0] LLR_MAX_VALUE =  (1 <<< (LLR_W - 1)) - 1;

    typedef enum logic [4:0] {
        S_IDLE,
        S_INIT_PUNCTURED,
        S_CLEAR_CHECK_MESSAGES,
        S_INITIAL_SYNDROME,
        S_GROUP_MESSAGE_READ,
        S_GROUP_MESSAGE_CAPTURE,
        S_GROUP_EDGE_READ_REQUEST,
        S_GROUP_EDGE_READ_CAPTURE,
        S_GROUP_COMPUTE,
        S_GROUP_EDGE_WRITE,
        S_GROUP_MESSAGE_WRITE,
        S_ITERATION_SYNDROME,
        S_FINALIZE_OUTPUT,
        S_DONE
    } state_t;

    state_t state;

    (* ram_style = "block" *) logic signed [LLR_W-1:0] posterior_mem [0:P-1][0:BANK_DEPTH-1];
    (* ram_style = "block" *) logic [ROW_MSG_W-1:0] message_mem [0:P-1][0:GROUPS-1];

    logic signed [LLR_W-1:0] posterior_read_data [0:P-1];
    logic [ROW_MSG_W-1:0] message_read_data [0:P-1];

    logic [TX_ADDR_BITS:0] load_count;
    logic llr_loaded_frame;
    logic llr_write_fire;
    logic start_fire;

    logic [GROUP_BITS-1:0] group_idx;
    logic [EDGE_BITS-1:0] edge_idx;
    logic [DEGREE_BITS-1:0] group_degree;
    logic [$clog2(MAX_ITERS+1)-1:0] iteration_idx;
    logic [PUNCTURED_GROUP_BITS-1:0] punctured_group_idx;
    logic [OUTPUT_BITS-1:0] output_word_idx;

    logic [FULL_N-1:0] hard_full;
    logic syndrome_any_failed;
    logic syndrome_group_failed;
    logic syndrome_done_pass;

    logic [ROW_BITS-1:0] lane_row [0:P-1];
    logic [DEGREE_BITS-1:0] lane_degree [0:P-1];
    logic [COL_BITS-1:0] lane_col [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic [BANK_BITS-1:0] lane_bank [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic [BANK_ADDR_BITS-1:0] lane_addr [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic signed [MSG_W-1:0] lane_old_msg [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic signed [MSG_W-1:0] lane_new_msg [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic signed [Q_W-1:0] lane_q [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic lane_sign [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic [MAG_W-1:0] lane_mag [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic [MAG_W-1:0] lane_min1_mag [0:P-1];
    logic [MAG_W-1:0] lane_min2_mag [0:P-1];
    logic [EDGE_BITS-1:0] lane_min1_idx [0:P-1];
    logic lane_sign_xor [0:P-1];

    logic signed [Q_W-1:0] lane_q_from_read [0:P-1];
    logic [MAG_W-1:0] lane_mag_from_q [0:P-1];
    logic lane_sign_from_q [0:P-1];

    logic signed [MSG_W-1:0] computed_new_msg [0:P-1][0:MAX_ROW_WEIGHT-1];
    logic [31:0] computed_msg_saturations;
    logic [ROW_MSG_W-1:0] computed_msg_row [0:P-1];

    logic signed [SAT_W-1:0] posterior_math [0:P-1];
    logic signed [LLR_W-1:0] posterior_clipped [0:P-1];
    logic posterior_saturated [0:P-1];
    logic [31:0] computed_posterior_saturations;

    int unsigned lane_loop;
    int unsigned edge_loop;

    assign busy = (state != S_IDLE) && (state != S_DONE);
    assign llr_write_fire = llr_write_valid && llr_write_ready;
    assign start_fire = start && (state == S_IDLE) && llr_loaded_frame;
    assign llr_write_ready =
        (state == S_IDLE) &&
        !llr_loaded_frame &&
        !start &&
        (llr_write_addr == load_count[TX_ADDR_BITS-1:0]);

    initial begin
        if (TX_N != ar4ja_1024_pkg::TX_N) $fatal(1, "ldpc_decoder_top supports only fixed TX_N");
        if (FULL_N != ar4ja_1024_pkg::FULL_N) $fatal(1, "ldpc_decoder_top supports only fixed FULL_N");
        if (CHECKS != ar4ja_1024_pkg::CHECKS) $fatal(1, "ldpc_decoder_top supports only fixed CHECKS");
        if ((K_BITS % 32) != 0) $fatal(1, "K_BITS must be divisible by 32");
        if (ALPHA_NUM != 3 || ALPHA_DEN != 4) $fatal(1, "only 3/4 normalization is implemented");
        if (!ldpc_schedule_pkg::schedule_lanes_supported(LANES)) $fatal(1, "unsupported LANES value");
        if ((ar4ja_1024_pkg::CHECKS % P) != 0) $fatal(1, "CHECKS must be divisible by LANES");
        if ((ar4ja_1024_pkg::FULL_N % P) != 0) $fatal(1, "FULL_N must be divisible by LANES");
        if ((ar4ja_1024_pkg::PUNCTURED_N % P) != 0) $fatal(1, "PUNCTURED_N must be divisible by LANES");
    end

    function automatic logic [BANK_BITS-1:0] posterior_bank(input logic [COL_BITS-1:0] variable_idx);
        begin
            if (P == 1) begin
                posterior_bank = '0;
            end else begin
                posterior_bank = variable_idx % P;
            end
        end
    endfunction

    function automatic logic [BANK_ADDR_BITS-1:0] posterior_addr(input logic [COL_BITS-1:0] variable_idx);
        begin
            posterior_addr = variable_idx / P;
        end
    endfunction

    function automatic logic signed [MSG_W-1:0] saturate_msg(input logic signed [SAT_W-1:0] value);
        begin
            if (value < MSG_MIN_VALUE) begin
                saturate_msg = MSG_MIN_VALUE[MSG_W-1:0];
            end else if (value > MSG_MAX_VALUE) begin
                saturate_msg = MSG_MAX_VALUE[MSG_W-1:0];
            end else begin
                saturate_msg = value[MSG_W-1:0];
            end
        end
    endfunction

    function automatic logic signed [LLR_W-1:0] saturate_llr(input logic signed [SAT_W-1:0] value);
        begin
            if (value < LLR_MIN_VALUE) begin
                saturate_llr = LLR_MIN_VALUE[LLR_W-1:0];
            end else if (value > LLR_MAX_VALUE) begin
                saturate_llr = LLR_MAX_VALUE[LLR_W-1:0];
            end else begin
                saturate_llr = value[LLR_W-1:0];
            end
        end
    endfunction

    function automatic logic msg_would_saturate(input logic signed [SAT_W-1:0] value);
        begin
            msg_would_saturate = (value < MSG_MIN_VALUE) || (value > MSG_MAX_VALUE);
        end
    endfunction

    function automatic logic llr_would_saturate(input logic signed [SAT_W-1:0] value);
        begin
            llr_would_saturate = (value < LLR_MIN_VALUE) || (value > LLR_MAX_VALUE);
        end
    endfunction

    function automatic logic [MAG_W-1:0] abs_q(input logic signed [Q_W-1:0] value);
        logic [Q_W-1:0] twos_mag;
        begin
            if (value[Q_W-1]) begin
                twos_mag = (~value[Q_W-1:0]) + Q_W'(1);
                abs_q = {{(MAG_W-Q_W){1'b0}}, twos_mag};
            end else begin
                abs_q = {{(MAG_W-Q_W){1'b0}}, value[Q_W-1:0]};
            end
        end
    endfunction

    always @* begin
        for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
            lane_q_from_read[lane_loop] =
                $signed({posterior_read_data[lane_bank[lane_loop][edge_idx]][LLR_W-1],
                         posterior_read_data[lane_bank[lane_loop][edge_idx]]}) -
                $signed({lane_old_msg[lane_loop][edge_idx][MSG_W-1],
                         lane_old_msg[lane_loop][edge_idx]});
            lane_sign_from_q[lane_loop] = lane_q_from_read[lane_loop][Q_W-1];
            lane_mag_from_q[lane_loop] = abs_q(lane_q_from_read[lane_loop]);
        end
    end

    always @* begin
        computed_msg_saturations = 32'd0;
        for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
            computed_msg_row[lane_loop] = '0;
            for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                logic [MAG_W-1:0] selected_min;
                logic [SCALE_W-1:0] scaled_mag;
                logic signed [SAT_W-1:0] signed_mag;
                logic signed [SAT_W-1:0] signed_msg;

                computed_new_msg[lane_loop][edge_loop] = '0;
                selected_min = '0;
                scaled_mag = '0;
                signed_mag = '0;
                signed_msg = '0;

                if (edge_loop < lane_degree[lane_loop]) begin
                    selected_min =
                        (edge_loop[EDGE_BITS-1:0] == lane_min1_idx[lane_loop]) ?
                        lane_min2_mag[lane_loop] :
                        lane_min1_mag[lane_loop];
                    scaled_mag = ({{(SCALE_W-MAG_W){1'b0}}, selected_min} *
                                  {{(SCALE_W-2){1'b0}}, 2'd3}) >> 2;
                    signed_mag = $signed({1'b0, scaled_mag[SAT_W-2:0]});
                    signed_msg =
                        (lane_sign_xor[lane_loop] ^ lane_sign[lane_loop][edge_loop]) ?
                        -signed_mag :
                        signed_mag;
                    computed_new_msg[lane_loop][edge_loop] = saturate_msg(signed_msg);
                    computed_msg_row[lane_loop][edge_loop * MSG_W +: MSG_W] =
                        computed_new_msg[lane_loop][edge_loop];
                    if (msg_would_saturate(signed_msg)) begin
                        computed_msg_saturations = computed_msg_saturations + 32'd1;
                    end
                end
            end
        end
    end

    always @* begin
        computed_posterior_saturations = 32'd0;
        for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
            posterior_math[lane_loop] =
                {{(SAT_W-Q_W){lane_q[lane_loop][edge_idx][Q_W-1]}}, lane_q[lane_loop][edge_idx]} +
                {{(SAT_W-MSG_W){lane_new_msg[lane_loop][edge_idx][MSG_W-1]}},
                 lane_new_msg[lane_loop][edge_idx]};
            posterior_clipped[lane_loop] = saturate_llr(posterior_math[lane_loop]);
            posterior_saturated[lane_loop] = llr_would_saturate(posterior_math[lane_loop]);
            if ((edge_idx < lane_degree[lane_loop]) && posterior_saturated[lane_loop]) begin
                computed_posterior_saturations = computed_posterior_saturations + 32'd1;
            end
        end
    end

    always @* begin
        syndrome_group_failed = 1'b0;
        for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
            logic row_failed;
            logic [ROW_BITS-1:0] syndrome_row;

            row_failed = 1'b0;
            syndrome_row = (group_idx * P) + lane_loop[ROW_BITS-1:0];
            for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                if (edge_loop < ar4ja_1024_pkg::row_weight(syndrome_row)) begin
                    row_failed =
                        row_failed ^
                        hard_full[ar4ja_1024_pkg::row_col(syndrome_row, edge_loop)];
                end
            end
            syndrome_group_failed = syndrome_group_failed | row_failed;
        end
        syndrome_done_pass = !(syndrome_any_failed || syndrome_group_failed);
    end

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= S_IDLE;
            done <= 1'b0;
            decoded_bits <= '0;
            syndrome_pass <= 1'b0;
            decoder_success <= 1'b0;
            decoder_fail <= 1'b0;
            iterations_used <= '0;
            cycles_elapsed <= 32'd0;
            saturation_count <= 32'd0;
            load_count <= '0;
            llr_loaded_frame <= 1'b0;
            group_idx <= '0;
            edge_idx <= '0;
            group_degree <= '0;
            iteration_idx <= '0;
            punctured_group_idx <= '0;
            output_word_idx <= '0;
            hard_full <= '0;
            syndrome_any_failed <= 1'b0;

            for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                posterior_read_data[lane_loop] <= '0;
                message_read_data[lane_loop] <= '0;
                lane_row[lane_loop] <= '0;
                lane_degree[lane_loop] <= '0;
                lane_min1_mag[lane_loop] <= '1;
                lane_min2_mag[lane_loop] <= '1;
                lane_min1_idx[lane_loop] <= '0;
                lane_sign_xor[lane_loop] <= 1'b0;
                for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                    lane_col[lane_loop][edge_loop] <= '0;
                    lane_bank[lane_loop][edge_loop] <= '0;
                    lane_addr[lane_loop][edge_loop] <= '0;
                    lane_old_msg[lane_loop][edge_loop] <= '0;
                    lane_new_msg[lane_loop][edge_loop] <= '0;
                    lane_q[lane_loop][edge_loop] <= '0;
                    lane_sign[lane_loop][edge_loop] <= 1'b0;
                    lane_mag[lane_loop][edge_loop] <= '0;
                end
            end
        end else begin
            done <= 1'b0;

            if (state != S_IDLE && state != S_DONE) begin
                cycles_elapsed <= cycles_elapsed + 32'd1;
            end

            if (llr_load_clear) begin
                load_count <= '0;
                llr_loaded_frame <= 1'b0;
            end else if (llr_write_fire) begin
                posterior_mem[posterior_bank({{(COL_BITS-TX_ADDR_BITS){1'b0}}, llr_write_addr})]
                             [posterior_addr({{(COL_BITS-TX_ADDR_BITS){1'b0}}, llr_write_addr})]
                    <= llr_write_data;
                hard_full[llr_write_addr] <= llr_write_data[LLR_W-1];
                if (llr_write_addr == TX_N - 1) begin
                    load_count <= TX_N[TX_ADDR_BITS:0];
                    llr_loaded_frame <= 1'b1;
                end else begin
                    load_count <= load_count + 1'b1;
                end
            end

            case (state)
                S_IDLE: begin
                    if (start_fire) begin
                        cycles_elapsed <= 32'd0;
                        saturation_count <= 32'd0;
                        iterations_used <= '0;
                        syndrome_pass <= 1'b0;
                        decoder_success <= 1'b0;
                        decoder_fail <= 1'b0;
                        punctured_group_idx <= '0;
                        load_count <= '0;
                        llr_loaded_frame <= 1'b0;
                        state <= S_INIT_PUNCTURED;
                    end
                end

                S_INIT_PUNCTURED: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        logic [COL_BITS-1:0] punctured_variable;

                        punctured_variable =
                            TX_N[COL_BITS-1:0] +
                            (({{(COL_BITS-PUNCTURED_GROUP_BITS){1'b0}}, punctured_group_idx}) * P) +
                            lane_loop[COL_BITS-1:0];
                        posterior_mem[posterior_bank(punctured_variable)]
                                     [posterior_addr(punctured_variable)] <= '0;
                        hard_full[punctured_variable] <= 1'b0;
                    end

                    if (punctured_group_idx == PUNCTURED_GROUPS - 1) begin
                        group_idx <= '0;
                        state <= S_CLEAR_CHECK_MESSAGES;
                    end else begin
                        punctured_group_idx <= punctured_group_idx + 1'b1;
                    end
                end

                S_CLEAR_CHECK_MESSAGES: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        message_mem[lane_loop][group_idx] <= '0;
                    end

                    if (group_idx == GROUPS - 1) begin
                        group_idx <= '0;
                        syndrome_any_failed <= 1'b0;
                        state <= S_INITIAL_SYNDROME;
                    end else begin
                        group_idx <= group_idx + 1'b1;
                    end
                end

                S_INITIAL_SYNDROME: begin
                    syndrome_any_failed <= syndrome_any_failed | syndrome_group_failed;
                    if (group_idx == GROUPS - 1) begin
                        syndrome_pass <= syndrome_done_pass;
                        if (syndrome_done_pass || MAX_ITERS == 0) begin
                            decoder_success <= syndrome_done_pass;
                            decoder_fail <= !syndrome_done_pass;
                            iterations_used <= '0;
                            output_word_idx <= '0;
                            state <= S_FINALIZE_OUTPUT;
                        end else begin
                            iteration_idx <= {{($bits(iteration_idx)-1){1'b0}}, 1'b1};
                            group_idx <= '0;
                            state <= S_GROUP_MESSAGE_READ;
                        end
                    end else begin
                        group_idx <= group_idx + 1'b1;
                    end
                end

                S_GROUP_MESSAGE_READ: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        message_read_data[lane_loop] <= message_mem[lane_loop][group_idx];
                    end
                    state <= S_GROUP_MESSAGE_CAPTURE;
                end

                S_GROUP_MESSAGE_CAPTURE: begin
                    group_degree <= ar4ja_1024_pkg::row_weight(group_idx * P);
                    edge_idx <= '0;
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        logic [ROW_BITS-1:0] captured_row;
                        logic [DEGREE_BITS-1:0] captured_degree;

                        captured_row = (group_idx * P) + lane_loop[ROW_BITS-1:0];
                        captured_degree = ar4ja_1024_pkg::row_weight(captured_row);
                        lane_row[lane_loop] <= captured_row;
                        lane_degree[lane_loop] <= captured_degree;
                        lane_sign_xor[lane_loop] <= 1'b0;
                        lane_min1_mag[lane_loop] <= '1;
                        lane_min2_mag[lane_loop] <= '1;
                        lane_min1_idx[lane_loop] <= '0;
                        for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                            logic [COL_BITS-1:0] captured_col;

                            captured_col = ar4ja_1024_pkg::row_col(captured_row, edge_loop);
                            lane_col[lane_loop][edge_loop] <= captured_col;
                            lane_bank[lane_loop][edge_loop] <= posterior_bank(captured_col);
                            lane_addr[lane_loop][edge_loop] <= posterior_addr(captured_col);
                            if (edge_loop < captured_degree) begin
                                lane_old_msg[lane_loop][edge_loop] <=
                                    message_read_data[lane_loop][edge_loop * MSG_W +: MSG_W];
                            end else begin
                                lane_old_msg[lane_loop][edge_loop] <= '0;
                            end
                            lane_new_msg[lane_loop][edge_loop] <= '0;
                            lane_q[lane_loop][edge_loop] <= '0;
                            lane_sign[lane_loop][edge_loop] <= 1'b0;
                            lane_mag[lane_loop][edge_loop] <= '0;
                        end
                    end
                    state <= S_GROUP_EDGE_READ_REQUEST;
                end

                S_GROUP_EDGE_READ_REQUEST: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        if (edge_idx < lane_degree[lane_loop]) begin
                            posterior_read_data[lane_bank[lane_loop][edge_idx]] <=
                                posterior_mem[lane_bank[lane_loop][edge_idx]]
                                             [lane_addr[lane_loop][edge_idx]];
                        end
                    end
                    state <= S_GROUP_EDGE_READ_CAPTURE;
                end

                S_GROUP_EDGE_READ_CAPTURE: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        if (edge_idx < lane_degree[lane_loop]) begin
                            lane_q[lane_loop][edge_idx] <= lane_q_from_read[lane_loop];
                            lane_sign[lane_loop][edge_idx] <= lane_sign_from_q[lane_loop];
                            lane_mag[lane_loop][edge_idx] <= lane_mag_from_q[lane_loop];
                            lane_sign_xor[lane_loop] <= lane_sign_xor[lane_loop] ^ lane_sign_from_q[lane_loop];
                            if (lane_mag_from_q[lane_loop] < lane_min1_mag[lane_loop]) begin
                                lane_min2_mag[lane_loop] <= lane_min1_mag[lane_loop];
                                lane_min1_mag[lane_loop] <= lane_mag_from_q[lane_loop];
                                lane_min1_idx[lane_loop] <= edge_idx;
                            end else if (lane_mag_from_q[lane_loop] < lane_min2_mag[lane_loop]) begin
                                lane_min2_mag[lane_loop] <= lane_mag_from_q[lane_loop];
                            end
                        end
                    end

                    if (edge_idx == group_degree - 1'b1) begin
                        edge_idx <= '0;
                        state <= S_GROUP_COMPUTE;
                    end else begin
                        edge_idx <= edge_idx + 1'b1;
                        state <= S_GROUP_EDGE_READ_REQUEST;
                    end
                end

                S_GROUP_COMPUTE: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                            lane_new_msg[lane_loop][edge_loop] <= computed_new_msg[lane_loop][edge_loop];
                        end
                    end
                    saturation_count <= saturation_count + computed_msg_saturations;
                    edge_idx <= '0;
                    state <= S_GROUP_EDGE_WRITE;
                end

                S_GROUP_EDGE_WRITE: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        if (edge_idx < lane_degree[lane_loop]) begin
                            posterior_mem[lane_bank[lane_loop][edge_idx]]
                                         [lane_addr[lane_loop][edge_idx]]
                                <= posterior_clipped[lane_loop];
                            hard_full[lane_col[lane_loop][edge_idx]] <=
                                posterior_clipped[lane_loop][LLR_W-1];
                        end
                    end
                    saturation_count <= saturation_count + computed_posterior_saturations;

                    if (edge_idx == group_degree - 1'b1) begin
                        edge_idx <= '0;
                        state <= S_GROUP_MESSAGE_WRITE;
                    end else begin
                        edge_idx <= edge_idx + 1'b1;
                    end
                end

                S_GROUP_MESSAGE_WRITE: begin
                    for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                        message_mem[lane_loop][group_idx] <= computed_msg_row[lane_loop];
                    end

                    if (group_idx == GROUPS - 1) begin
                        group_idx <= '0;
                        syndrome_any_failed <= 1'b0;
                        state <= S_ITERATION_SYNDROME;
                    end else begin
                        group_idx <= group_idx + 1'b1;
                        state <= S_GROUP_MESSAGE_READ;
                    end
                end

                S_ITERATION_SYNDROME: begin
                    syndrome_any_failed <= syndrome_any_failed | syndrome_group_failed;
                    if (group_idx == GROUPS - 1) begin
                        syndrome_pass <= syndrome_done_pass;
                        if (syndrome_done_pass || iteration_idx == MAX_ITERS[$bits(iteration_idx)-1:0]) begin
                            decoder_success <= syndrome_done_pass;
                            decoder_fail <= !syndrome_done_pass;
                            iterations_used <= iteration_idx;
                            output_word_idx <= '0;
                            state <= S_FINALIZE_OUTPUT;
                        end else begin
                            iteration_idx <= iteration_idx + 1'b1;
                            group_idx <= '0;
                            state <= S_GROUP_MESSAGE_READ;
                        end
                    end else begin
                        group_idx <= group_idx + 1'b1;
                    end
                end

                S_FINALIZE_OUTPUT: begin
                    decoded_bits[output_word_idx * 32 +: 32] <=
                        hard_full[output_word_idx * 32 +: 32];
                    if (output_word_idx == OUTPUT_WORDS - 1) begin
                        state <= S_DONE;
                    end else begin
                        output_word_idx <= output_word_idx + 1'b1;
                    end
                end

                S_DONE: begin
                    done <= 1'b1;
                    state <= S_IDLE;
                end

                default: begin
                    state <= S_IDLE;
                end
            endcase
        end
    end

`ifdef LDPC_ENABLE_ASSERTS
    always @(posedge clk) begin
        if (!rst) begin
            assert (state <= S_DONE);
            assert (group_idx < GROUPS);
            assert (edge_idx < MAX_ROW_WEIGHT);
            assert (!(start && state != S_IDLE));
            assert (!(llr_write_valid && llr_write_ready && state != S_IDLE));
            assert (!(state == S_GROUP_EDGE_WRITE && edge_idx >= group_degree));
            for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                assert ((lane_degree[lane_loop] == 0) ||
                        (lane_degree[lane_loop] == 3) ||
                        (lane_degree[lane_loop] == 6));
                for (edge_loop = 0; edge_loop < MAX_ROW_WEIGHT; edge_loop = edge_loop + 1) begin
                    assert (lane_col[lane_loop][edge_loop] < FULL_N);
                    assert (lane_bank[lane_loop][edge_loop] < P);
                    assert (lane_addr[lane_loop][edge_loop] < BANK_DEPTH);
                end
            end
            if (state == S_GROUP_EDGE_READ_REQUEST || state == S_GROUP_EDGE_WRITE) begin
                for (lane_loop = 0; lane_loop < P; lane_loop = lane_loop + 1) begin
                    for (edge_loop = lane_loop + 1; edge_loop < P; edge_loop = edge_loop + 1) begin
                        if ((edge_idx < lane_degree[lane_loop]) &&
                            (edge_idx < lane_degree[edge_loop])) begin
                            assert (lane_col[lane_loop][edge_idx] != lane_col[edge_loop][edge_idx]);
                            assert (lane_bank[lane_loop][edge_idx] != lane_bank[edge_loop][edge_idx]);
                        end
                    end
                end
            end
        end
    end
`endif

endmodule
