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

    localparam int MAX_ROW_WEIGHT = ar4ja_1024_pkg::MAX_ROW_WEIGHT;
    localparam int ROW_MSG_W = MAX_ROW_WEIGHT * MSG_W;
    localparam int ROW_BITS = $clog2(CHECKS);
    localparam int COL_BITS = $clog2(FULL_N);
    localparam int TX_ADDR_BITS = $clog2(TX_N);
    localparam int EDGE_BITS = $clog2(MAX_ROW_WEIGHT);
    localparam int DEGREE_BITS = $clog2(MAX_ROW_WEIGHT + 1);
    localparam int PUNCTURED_BITS = $clog2(ar4ja_1024_pkg::PUNCTURED_N);
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
        S_ROW_MESSAGE_READ,
        S_ROW_MESSAGE_CAPTURE,
        S_ROW_EDGE_READ_REQUEST,
        S_ROW_EDGE_READ_CAPTURE,
        S_ROW_COMPUTE,
        S_ROW_EDGE_WRITE,
        S_ROW_MESSAGE_WRITE,
        S_ITERATION_SYNDROME,
        S_FINALIZE_OUTPUT,
        S_DONE
    } state_t;

    state_t state;

    logic [TX_ADDR_BITS:0] load_count;
    logic llr_loaded_frame;
    logic llr_write_fire;
    logic start_fire;

    logic [ROW_BITS-1:0] row_idx;
    logic [EDGE_BITS-1:0] edge_idx;
    logic [DEGREE_BITS-1:0] row_degree;
    logic [$clog2(MAX_ITERS+1)-1:0] iteration_idx;
    logic [PUNCTURED_BITS-1:0] punctured_idx;
    logic [OUTPUT_BITS-1:0] output_word_idx;

    logic [FULL_N-1:0] hard_full;
    logic syndrome_any_failed;
    logic syndrome_row_failed;
    logic syndrome_done_pass;

    logic [COL_BITS-1:0] row_col_reg [0:MAX_ROW_WEIGHT-1];
    logic signed [MSG_W-1:0] row_old_msg [0:MAX_ROW_WEIGHT-1];
    logic signed [MSG_W-1:0] row_new_msg [0:MAX_ROW_WEIGHT-1];
    logic signed [Q_W-1:0] row_q [0:MAX_ROW_WEIGHT-1];
    logic row_sign [0:MAX_ROW_WEIGHT-1];
    logic [MAG_W-1:0] row_mag [0:MAX_ROW_WEIGHT-1];
    logic [MAG_W-1:0] min1_mag;
    logic [MAG_W-1:0] min2_mag;
    logic [EDGE_BITS-1:0] min1_idx;
    logic row_sign_xor;

    logic post_read_enable;
    logic [COL_BITS-1:0] post_read_addr;
    logic signed [LLR_W-1:0] post_read_data;
    logic post_write_enable;
    logic [COL_BITS-1:0] post_write_addr;
    logic signed [LLR_W-1:0] post_write_data;

    logic msg_read_enable;
    logic [ROW_BITS-1:0] msg_read_row;
    logic [ROW_MSG_W-1:0] msg_read_data;
    logic msg_write_enable;
    logic [ROW_BITS-1:0] msg_write_row;
    logic [ROW_MSG_W-1:0] msg_write_data;

    logic signed [Q_W-1:0] q_from_read;
    logic [MAG_W-1:0] mag_from_q;
    logic sign_from_q;

    logic signed [MSG_W-1:0] computed_new_msg [0:MAX_ROW_WEIGHT-1];
    logic [31:0] computed_msg_saturations;
    logic signed [SAT_W-1:0] posterior_math;
    logic signed [LLR_W-1:0] posterior_clipped;
    logic posterior_saturated;

    int unsigned loop_idx;

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
    end

    posterior_memory #(
        .DEPTH(FULL_N),
        .DATA_W(LLR_W)
    ) posterior_ram (
        .clk(clk),
        .read_enable(post_read_enable),
        .read_addr(post_read_addr),
        .read_data(post_read_data),
        .write_enable(post_write_enable),
        .write_addr(post_write_addr),
        .write_data(post_write_data)
    );

    message_memory #(
        .ROWS(CHECKS),
        .ROW_W(ROW_MSG_W)
    ) check_message_ram (
        .clk(clk),
        .read_enable(msg_read_enable),
        .read_row(msg_read_row),
        .read_data(msg_read_data),
        .write_enable(msg_write_enable),
        .write_row(msg_write_row),
        .write_data(msg_write_data)
    );

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

    always @* begin
        post_read_enable = 1'b0;
        post_read_addr = '0;
        post_write_enable = 1'b0;
        post_write_addr = '0;
        post_write_data = '0;
        msg_read_enable = 1'b0;
        msg_read_row = '0;
        msg_write_enable = 1'b0;
        msg_write_row = '0;
        msg_write_data = '0;

        if (state == S_IDLE && llr_write_fire) begin
            post_write_enable = 1'b1;
            post_write_addr = {{(COL_BITS-TX_ADDR_BITS){1'b0}}, llr_write_addr};
            post_write_data = llr_write_data;
        end else if (state == S_INIT_PUNCTURED) begin
            post_write_enable = 1'b1;
            post_write_addr = TX_N[COL_BITS-1:0] + {{(COL_BITS-PUNCTURED_BITS){1'b0}}, punctured_idx};
            post_write_data = '0;
        end else if (state == S_ROW_EDGE_WRITE) begin
            post_write_enable = 1'b1;
            post_write_addr = row_col_reg[edge_idx];
            post_write_data = posterior_clipped;
        end

        if (state == S_ROW_EDGE_READ_REQUEST) begin
            post_read_enable = 1'b1;
            post_read_addr = row_col_reg[edge_idx];
        end

        if (state == S_ROW_MESSAGE_READ) begin
            msg_read_enable = 1'b1;
            msg_read_row = row_idx;
        end

        if (state == S_CLEAR_CHECK_MESSAGES) begin
            msg_write_enable = 1'b1;
            msg_write_row = row_idx;
            msg_write_data = '0;
        end else if (state == S_ROW_MESSAGE_WRITE) begin
            msg_write_enable = 1'b1;
            msg_write_row = row_idx;
            for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
                msg_write_data[loop_idx * MSG_W +: MSG_W] = row_new_msg[loop_idx];
            end
        end
    end

    always @* begin
        q_from_read =
            $signed({post_read_data[LLR_W-1], post_read_data}) -
            $signed({row_old_msg[edge_idx][MSG_W-1], row_old_msg[edge_idx]});
        sign_from_q = q_from_read[Q_W-1];
        if (sign_from_q) begin
            mag_from_q = -q_from_read;
        end else begin
            mag_from_q = q_from_read;
        end
    end

    always @* begin
        computed_msg_saturations = 32'd0;
        for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
            logic [MAG_W-1:0] selected_min;
            logic [SCALE_W-1:0] scaled_mag;
            logic signed [SAT_W-1:0] signed_mag;
            logic signed [SAT_W-1:0] signed_msg;

            computed_new_msg[loop_idx] = '0;
            selected_min = '0;
            scaled_mag = '0;
            signed_mag = '0;
            signed_msg = '0;

            if (loop_idx < row_degree) begin
                selected_min = (loop_idx[EDGE_BITS-1:0] == min1_idx) ? min2_mag : min1_mag;
                scaled_mag = ({{(SCALE_W-MAG_W){1'b0}}, selected_min} * SCALE_W'(ALPHA_NUM)) >> 2;
                signed_mag = $signed({1'b0, scaled_mag[SAT_W-2:0]});
                signed_msg = (row_sign_xor ^ row_sign[loop_idx]) ? -signed_mag : signed_mag;
                computed_new_msg[loop_idx] = saturate_msg(signed_msg);
                if (msg_would_saturate(signed_msg)) begin
                    computed_msg_saturations = computed_msg_saturations + 32'd1;
                end
            end
        end
    end

    always @* begin
        posterior_math =
            {{(SAT_W-Q_W){row_q[edge_idx][Q_W-1]}}, row_q[edge_idx]} +
            {{(SAT_W-MSG_W){row_new_msg[edge_idx][MSG_W-1]}}, row_new_msg[edge_idx]};
        posterior_clipped = saturate_llr(posterior_math);
        posterior_saturated = llr_would_saturate(posterior_math);
    end

    always @* begin
        syndrome_row_failed = 1'b0;
        for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
            if (loop_idx < ar4ja_1024_pkg::row_weight(row_idx)) begin
                syndrome_row_failed =
                    syndrome_row_failed ^
                    hard_full[ar4ja_1024_pkg::row_col(row_idx, loop_idx)];
            end
        end
        syndrome_done_pass = !(syndrome_any_failed || syndrome_row_failed);
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
            row_idx <= '0;
            edge_idx <= '0;
            row_degree <= '0;
            iteration_idx <= '0;
            punctured_idx <= '0;
            output_word_idx <= '0;
            hard_full <= '0;
            syndrome_any_failed <= 1'b0;
            row_sign_xor <= 1'b0;
            min1_mag <= '1;
            min2_mag <= '1;
            min1_idx <= '0;
            for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
                row_col_reg[loop_idx] <= '0;
                row_old_msg[loop_idx] <= '0;
                row_new_msg[loop_idx] <= '0;
                row_q[loop_idx] <= '0;
                row_sign[loop_idx] <= 1'b0;
                row_mag[loop_idx] <= '0;
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
                        punctured_idx <= '0;
                        load_count <= '0;
                        llr_loaded_frame <= 1'b0;
                        state <= S_INIT_PUNCTURED;
                    end
                end

                S_INIT_PUNCTURED: begin
                    hard_full[TX_N + punctured_idx] <= 1'b0;
                    if (punctured_idx == ar4ja_1024_pkg::PUNCTURED_N - 1) begin
                        row_idx <= '0;
                        state <= S_CLEAR_CHECK_MESSAGES;
                    end else begin
                        punctured_idx <= punctured_idx + 1'b1;
                    end
                end

                S_CLEAR_CHECK_MESSAGES: begin
                    if (row_idx == CHECKS - 1) begin
                        row_idx <= '0;
                        syndrome_any_failed <= 1'b0;
                        state <= S_INITIAL_SYNDROME;
                    end else begin
                        row_idx <= row_idx + 1'b1;
                    end
                end

                S_INITIAL_SYNDROME: begin
                    syndrome_any_failed <= syndrome_any_failed | syndrome_row_failed;
                    if (row_idx == CHECKS - 1) begin
                        syndrome_pass <= syndrome_done_pass;
                        if (syndrome_done_pass || MAX_ITERS == 0) begin
                            decoder_success <= syndrome_done_pass;
                            decoder_fail <= !syndrome_done_pass;
                            iterations_used <= '0;
                            output_word_idx <= '0;
                            state <= S_FINALIZE_OUTPUT;
                        end else begin
                            iteration_idx <= {{($bits(iteration_idx)-1){1'b0}}, 1'b1};
                            row_idx <= '0;
                            state <= S_ROW_MESSAGE_READ;
                        end
                    end else begin
                        row_idx <= row_idx + 1'b1;
                    end
                end

                S_ROW_MESSAGE_READ: begin
                    state <= S_ROW_MESSAGE_CAPTURE;
                end

                S_ROW_MESSAGE_CAPTURE: begin
                    row_degree <= ar4ja_1024_pkg::row_weight(row_idx);
                    row_sign_xor <= 1'b0;
                    min1_mag <= '1;
                    min2_mag <= '1;
                    min1_idx <= '0;
                    edge_idx <= '0;
                    for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
                        row_col_reg[loop_idx] <= ar4ja_1024_pkg::row_col(row_idx, loop_idx);
                        row_old_msg[loop_idx] <= msg_read_data[loop_idx * MSG_W +: MSG_W];
                        row_new_msg[loop_idx] <= '0;
                        row_q[loop_idx] <= '0;
                        row_sign[loop_idx] <= 1'b0;
                        row_mag[loop_idx] <= '0;
                    end
                    state <= S_ROW_EDGE_READ_REQUEST;
                end

                S_ROW_EDGE_READ_REQUEST: begin
                    state <= S_ROW_EDGE_READ_CAPTURE;
                end

                S_ROW_EDGE_READ_CAPTURE: begin
                    row_q[edge_idx] <= q_from_read;
                    row_sign[edge_idx] <= sign_from_q;
                    row_mag[edge_idx] <= mag_from_q;
                    row_sign_xor <= row_sign_xor ^ sign_from_q;
                    if (mag_from_q < min1_mag) begin
                        min2_mag <= min1_mag;
                        min1_mag <= mag_from_q;
                        min1_idx <= edge_idx;
                    end else if (mag_from_q < min2_mag) begin
                        min2_mag <= mag_from_q;
                    end

                    if (edge_idx == row_degree - 1'b1) begin
                        edge_idx <= '0;
                        state <= S_ROW_COMPUTE;
                    end else begin
                        edge_idx <= edge_idx + 1'b1;
                        state <= S_ROW_EDGE_READ_REQUEST;
                    end
                end

                S_ROW_COMPUTE: begin
                    for (loop_idx = 0; loop_idx < MAX_ROW_WEIGHT; loop_idx = loop_idx + 1) begin
                        row_new_msg[loop_idx] <= computed_new_msg[loop_idx];
                    end
                    saturation_count <= saturation_count + computed_msg_saturations;
                    edge_idx <= '0;
                    state <= S_ROW_EDGE_WRITE;
                end

                S_ROW_EDGE_WRITE: begin
                    hard_full[row_col_reg[edge_idx]] <= posterior_clipped[LLR_W-1];
                    if (posterior_saturated) begin
                        saturation_count <= saturation_count + 32'd1;
                    end

                    if (edge_idx == row_degree - 1'b1) begin
                        edge_idx <= '0;
                        state <= S_ROW_MESSAGE_WRITE;
                    end else begin
                        edge_idx <= edge_idx + 1'b1;
                    end
                end

                S_ROW_MESSAGE_WRITE: begin
                    if (row_idx == CHECKS - 1) begin
                        row_idx <= '0;
                        syndrome_any_failed <= 1'b0;
                        state <= S_ITERATION_SYNDROME;
                    end else begin
                        row_idx <= row_idx + 1'b1;
                        state <= S_ROW_MESSAGE_READ;
                    end
                end

                S_ITERATION_SYNDROME: begin
                    syndrome_any_failed <= syndrome_any_failed | syndrome_row_failed;
                    if (row_idx == CHECKS - 1) begin
                        syndrome_pass <= syndrome_done_pass;
                        if (syndrome_done_pass || iteration_idx == MAX_ITERS[$bits(iteration_idx)-1:0]) begin
                            decoder_success <= syndrome_done_pass;
                            decoder_fail <= !syndrome_done_pass;
                            iterations_used <= iteration_idx;
                            output_word_idx <= '0;
                            state <= S_FINALIZE_OUTPUT;
                        end else begin
                            iteration_idx <= iteration_idx + 1'b1;
                            row_idx <= '0;
                            state <= S_ROW_MESSAGE_READ;
                        end
                    end else begin
                        row_idx <= row_idx + 1'b1;
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
    always_ff @(posedge clk) begin
        if (!rst) begin
            assert (state <= S_DONE);
            assert (row_idx < CHECKS);
            assert (edge_idx < MAX_ROW_WEIGHT);
            assert (!(start && state != S_IDLE));
            assert (!(llr_write_valid && llr_write_ready && state != S_IDLE));
            assert (!(state == S_ROW_EDGE_WRITE && edge_idx >= row_degree));
        end
    end
`endif

endmodule
