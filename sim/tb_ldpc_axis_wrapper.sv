`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module tb_ldpc_axis_wrapper;
    `include "vectors/decoder/decoder_meta.svh"

    localparam int LLR_W = DECODER_VECTOR_LLR_W;
    localparam int MAX_ITERS = DECODER_VECTOR_MAX_ITERS;
    localparam int INPUT_WORDS = 512;
    localparam int OUTPUT_WORDS = 40;
    parameter int LANES = 8;

    logic clk;
    logic rst;
    logic s_axis_tvalid;
    logic s_axis_tready;
    logic [31:0] s_axis_tdata;
    logic [3:0] s_axis_tkeep;
    logic s_axis_tlast;
    logic m_axis_tvalid;
    logic m_axis_tready;
    logic [31:0] m_axis_tdata;
    logic [3:0] m_axis_tkeep;
    logic m_axis_tlast;
    logic frame_error;
    logic early_tlast_error;
    logic missing_tlast_error;
    logic tkeep_error;

    logic [TX_N*LLR_W-1:0] llr_vectors [0:DECODER_VECTOR_COUNT-1];
    logic [INFO_N-1:0] payload_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] success_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] syndrome_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] fail_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] iterations_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] saturation_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] cycle_min_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] cycle_max_expected [0:DECODER_VECTOR_COUNT-1];

    integer failures;
    integer word_idx;
    integer wait_guard;
    integer current_vector;

    ldpc_axis_wrapper #(
        .LLR_W(LLR_W),
        .MAX_ITERS(MAX_ITERS),
        .LANES(LANES)
    ) dut (
        .clk(clk),
        .rst(rst),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tlast(s_axis_tlast),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tlast(m_axis_tlast),
        .frame_error(frame_error),
        .early_tlast_error(early_tlast_error),
        .missing_tlast_error(missing_tlast_error),
        .tkeep_error(tkeep_error)
    );

    always #5 clk = ~clk;

    function automatic [31:0] expected_output_word(input integer vector_idx, input integer out_idx);
        begin
            case (out_idx)
                0: expected_output_word = 32'h4c445043;
                1: expected_output_word = success_expected[vector_idx];
                2: expected_output_word = syndrome_expected[vector_idx];
                3: expected_output_word = iterations_expected[vector_idx];
                4: expected_output_word = 32'hffff_ffff;
                5: expected_output_word = fail_expected[vector_idx];
                6: expected_output_word = saturation_expected[vector_idx];
                7: expected_output_word = 32'd0;
                default: expected_output_word = payload_expected[vector_idx][(out_idx - 8) * 32 +: 32];
            endcase
        end
    endfunction

    task automatic drive_word_keep(
        input [31:0] data,
        input [3:0] keep,
        input logic last,
        input integer stall_mode
    );
        integer ready_wait;
        begin
            if (stall_mode != 0 && (word_idx % 7) == 3) begin
                @(negedge clk);
                s_axis_tvalid = 1'b0;
                s_axis_tkeep = 4'd0;
                s_axis_tlast = 1'b0;
            end
            @(negedge clk);
            s_axis_tdata = data;
            s_axis_tkeep = keep;
            s_axis_tlast = last;
            s_axis_tvalid = 1'b1;
            ready_wait = 0;
            do begin
                @(posedge clk);
                ready_wait = ready_wait + 1;
                if (ready_wait > 2000) begin
                    $display("FAIL axis input timeout word=%0d last=%0d", word_idx, last);
                    $fatal(1);
                end
            end while (!s_axis_tready);
            @(negedge clk);
            s_axis_tvalid = 1'b0;
            s_axis_tkeep = 4'd0;
            s_axis_tlast = 1'b0;
        end
    endtask

    task automatic drive_word(input [31:0] data, input logic last, input integer stall_mode);
        begin
            drive_word_keep(data, 4'hf, last, stall_mode);
        end
    endtask

    task automatic send_good_frame(input integer vector_idx, input integer stall_mode);
        begin
            for (word_idx = 0; word_idx < INPUT_WORDS; word_idx = word_idx + 1) begin
                drive_word(
                    llr_vectors[vector_idx][word_idx * 32 +: 32],
                    (word_idx == INPUT_WORDS - 1),
                    stall_mode
                );
            end
        end
    endtask

    task automatic collect_good_output(input integer vector_idx, input integer stall_mode);
        reg [31:0] expected;
        reg [31:0] stalled_data;
        reg stalled_last;
        reg stalled_active;
        begin
            word_idx = 0;
            wait_guard = 0;
            stalled_data = 32'd0;
            stalled_last = 1'b0;
            stalled_active = 1'b0;
            while (word_idx < OUTPUT_WORDS && wait_guard < 400000) begin
                @(negedge clk);
                m_axis_tready = (stall_mode == 0) ? 1'b1 : ((wait_guard % 5) != 2);
                if (m_axis_tvalid && !m_axis_tready) begin
                    if (stalled_active &&
                        (m_axis_tdata !== stalled_data ||
                         m_axis_tkeep !== 4'hf ||
                         m_axis_tlast !== stalled_last)) begin
                        $display("FAIL axis vector=%0d stalled output changed word=%0d", vector_idx, word_idx);
                        failures = failures + 1;
                    end
                    stalled_data = m_axis_tdata;
                    stalled_last = m_axis_tlast;
                    stalled_active = 1'b1;
                end else begin
                    stalled_active = 1'b0;
                end
                if (m_axis_tvalid && m_axis_tready) begin
                    if (m_axis_tkeep !== 4'hf) begin
                        $display("FAIL axis vector=%0d word=%0d bad tkeep=%0h",
                            vector_idx, word_idx, m_axis_tkeep);
                        failures = failures + 1;
                    end
                    expected = expected_output_word(vector_idx, word_idx);
                    if (word_idx == 4) begin
                        if (m_axis_tdata < cycle_min_expected[vector_idx] ||
                            m_axis_tdata > cycle_max_expected[vector_idx]) begin
                            $display("FAIL axis vector=%0d cycles=%0d bounds=[%0d,%0d]",
                                vector_idx, m_axis_tdata,
                                cycle_min_expected[vector_idx],
                                cycle_max_expected[vector_idx]);
                            failures = failures + 1;
                        end
                    end else if (m_axis_tdata !== expected) begin
                        $display("FAIL axis vector=%0d word=%0d got=%08x expected=%08x",
                            vector_idx, word_idx, m_axis_tdata, expected);
                        failures = failures + 1;
                    end
                    if ((word_idx == OUTPUT_WORDS - 1) != m_axis_tlast) begin
                        $display("FAIL axis vector=%0d word=%0d bad tlast=%0d",
                            vector_idx, word_idx, m_axis_tlast);
                        failures = failures + 1;
                    end
                    word_idx = word_idx + 1;
                end
                @(posedge clk);
                wait_guard = wait_guard + 1;
            end
            @(negedge clk);
            m_axis_tready = 1'b0;
            if (word_idx != OUTPUT_WORDS) begin
                $display("FAIL axis vector=%0d output timeout words=%0d", vector_idx, word_idx);
                failures = failures + 1;
            end else begin
                $display("PASS axis vector=%0d", vector_idx);
            end
        end
    endtask

    task automatic collect_error_output(
        input string name,
        input logic expect_early,
        input logic expect_missing,
        input logic expect_tkeep
    );
        begin
            word_idx = 0;
            wait_guard = 0;
            while (word_idx < OUTPUT_WORDS && wait_guard < 2000) begin
                @(negedge clk);
                m_axis_tready = 1'b1;
                if (m_axis_tvalid && m_axis_tready) begin
                    if (m_axis_tkeep !== 4'hf) begin
                        $display("FAIL %s word=%0d bad tkeep=%0h", name, word_idx, m_axis_tkeep);
                        failures = failures + 1;
                    end
                    if ((word_idx == OUTPUT_WORDS - 1) != m_axis_tlast) begin
                        $display("FAIL %s word=%0d bad tlast=%0d", name, word_idx, m_axis_tlast);
                        failures = failures + 1;
                    end
                    if (word_idx == 0 && m_axis_tdata !== 32'h4c445043) failures = failures + 1;
                    if (word_idx == 1 && m_axis_tdata !== 32'd0) failures = failures + 1;
                    if (word_idx == 5 && m_axis_tdata !== 32'd1) failures = failures + 1;
                    word_idx = word_idx + 1;
                end
                @(posedge clk);
                wait_guard = wait_guard + 1;
            end
            @(negedge clk);
            m_axis_tready = 1'b0;
            if (word_idx != OUTPUT_WORDS) begin
                $display("FAIL %s malformed output timeout", name);
                failures = failures + 1;
            end
            if (!frame_error ||
                early_tlast_error !== expect_early ||
                missing_tlast_error !== expect_missing ||
                tkeep_error !== expect_tkeep) begin
                $display("FAIL %s error flags frame=%0d early=%0d missing=%0d tkeep=%0d",
                    name, frame_error, early_tlast_error, missing_tlast_error, tkeep_error);
                failures = failures + 1;
            end else begin
                $display("PASS %s malformed frame", name);
            end
            @(posedge clk);
        end
    endtask

    initial begin
        $display("AXI wrapper testbench starting");
        $readmemh("vectors/decoder/llr.mem", llr_vectors);
        $readmemh("vectors/decoder/payload_expected.mem", payload_expected);
        $readmemh("vectors/decoder/success.mem", success_expected);
        $readmemh("vectors/decoder/syndrome_pass.mem", syndrome_expected);
        $readmemh("vectors/decoder/fail.mem", fail_expected);
        $readmemh("vectors/decoder/iterations.mem", iterations_expected);
        $readmemh("vectors/decoder/saturation.mem", saturation_expected);
        $readmemh("vectors/decoder/cycle_min.mem", cycle_min_expected);
        $readmemh("vectors/decoder/cycle_max.mem", cycle_max_expected);

        clk = 1'b0;
        rst = 1'b1;
        s_axis_tvalid = 1'b0;
        s_axis_tdata = 32'd0;
        s_axis_tkeep = 4'd0;
        s_axis_tlast = 1'b0;
        m_axis_tready = 1'b0;
        failures = 0;

        repeat (4) @(posedge clk);
        rst = 1'b0;

        send_good_frame(0, 0);
        $display("sent axis vector=0");
        collect_good_output(0, 0);

        send_good_frame(5, 1);
        $display("sent axis vector=5");
        collect_good_output(5, 1);

        send_good_frame(10, 0);
        $display("sent axis vector=10");
        collect_good_output(10, 0);
        send_good_frame(1, 0);
        $display("sent axis vector=1");
        collect_good_output(1, 0);

        drive_word(llr_vectors[0][0 +: 32], 1'b1, 0);
        collect_error_output("early_tlast", 1'b1, 1'b0, 1'b0);

        for (word_idx = 0; word_idx < 5; word_idx = word_idx + 1) begin
            drive_word(
                llr_vectors[0][word_idx * 32 +: 32],
                (word_idx == 4),
                0
            );
        end
        collect_error_output("early_tlast_late", 1'b1, 1'b0, 1'b0);

        send_good_frame(0, 0);
        $display("sent axis vector=0 after late early_tlast");
        collect_good_output(0, 0);

        drive_word_keep(llr_vectors[0][0 +: 32], 4'he, 1'b1, 0);
        collect_error_output("bad_tkeep", 1'b0, 1'b0, 1'b1);

        for (word_idx = 0; word_idx < INPUT_WORDS; word_idx = word_idx + 1) begin
            drive_word(llr_vectors[0][word_idx * 32 +: 32], 1'b0, 0);
        end
        collect_error_output("missing_tlast", 1'b0, 1'b1, 1'b0);
        word_idx = 0;
        drive_word(32'hdead_beef, 1'b1, 0);

        drive_word(llr_vectors[0][0 +: 32], 1'b0, 0);
        repeat (4) @(posedge clk);
        rst = 1'b1;
        repeat (4) @(posedge clk);
        rst = 1'b0;
        repeat (2) @(posedge clk);

        send_good_frame(0, 0);
        $display("sent axis vector=0 after malformed frame and reset");
        collect_good_output(0, 0);

        if (failures != 0) begin
            $display("AXI wrapper simulation failed: %0d failures", failures);
            $fatal(1);
        end
        $display("AXI wrapper simulation passed");
        $finish;
    end

endmodule
