`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module tb_ldpc_decoder_top;
    `include "vectors/decoder/decoder_meta.svh"

    localparam int LLR_W = DECODER_VECTOR_LLR_W;
    localparam int MSG_W = 8;
    localparam int MAX_ITERS = DECODER_VECTOR_MAX_ITERS;
    localparam int TIMEOUT_CYCLES = 100000;

    logic clk;
    logic rst;
    logic start;
    logic [TX_N*LLR_W-1:0] llr_in_flat;
    logic busy;
    logic done;
    logic [INFO_N-1:0] decoded_bits;
    logic syndrome_pass;
    logic decoder_success;
    logic decoder_fail;
    logic [$clog2(MAX_ITERS+1)-1:0] iterations_used;
    logic [31:0] cycles_elapsed;
    logic [31:0] saturation_count;

    logic [TX_N*LLR_W-1:0] llr_vectors [0:DECODER_VECTOR_COUNT-1];
    logic [INFO_N-1:0] payload_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] success_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] syndrome_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] fail_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] iterations_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] saturation_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] cycle_min_expected [0:DECODER_VECTOR_COUNT-1];
    logic [31:0] cycle_max_expected [0:DECODER_VECTOR_COUNT-1];

    integer vector_idx;
    integer wait_cycles;
    integer failures;

    ldpc_decoder_top #(
        .LLR_W(LLR_W),
        .MSG_W(MSG_W),
        .MAX_ITERS(MAX_ITERS)
    ) dut (
        .clk(clk),
        .rst(rst),
        .start(start),
        .llr_in_flat(llr_in_flat),
        .busy(busy),
        .done(done),
        .decoded_bits(decoded_bits),
        .syndrome_pass(syndrome_pass),
        .decoder_success(decoder_success),
        .decoder_fail(decoder_fail),
        .iterations_used(iterations_used),
        .cycles_elapsed(cycles_elapsed),
        .saturation_count(saturation_count)
    );

    always #5 clk = ~clk;

    initial begin
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
        start = 1'b0;
        llr_in_flat = '0;
        failures = 0;

        repeat (4) @(posedge clk);
        rst = 1'b0;

        for (vector_idx = 0; vector_idx < DECODER_VECTOR_COUNT; vector_idx = vector_idx + 1) begin
            @(posedge clk);
            llr_in_flat = llr_vectors[vector_idx];
            start = 1'b1;
            @(posedge clk);
            start = 1'b0;

            wait_cycles = 0;
            while (!done && wait_cycles < TIMEOUT_CYCLES) begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
            end

            if (!done) begin
                $display("FAIL vector=%0d timeout after %0d cycles", vector_idx, wait_cycles);
                failures = failures + 1;
            end else begin
                if (decoded_bits !== payload_expected[vector_idx] ||
                    decoder_success !== success_expected[vector_idx][0] ||
                    syndrome_pass !== syndrome_expected[vector_idx][0] ||
                    decoder_fail !== fail_expected[vector_idx][0] ||
                    iterations_used !== iterations_expected[vector_idx][$bits(iterations_used)-1:0] ||
                    saturation_count !== saturation_expected[vector_idx] ||
                    cycles_elapsed < cycle_min_expected[vector_idx] ||
                    cycles_elapsed > cycle_max_expected[vector_idx]) begin
                    $display(
                        "FAIL vector=%0d success=%0d/%0d syndrome=%0d/%0d fail=%0d/%0d iter=%0d/%0d sat=%0d/%0d cycles=%0d bounds=[%0d,%0d]",
                        vector_idx,
                        decoder_success,
                        success_expected[vector_idx][0],
                        syndrome_pass,
                        syndrome_expected[vector_idx][0],
                        decoder_fail,
                        fail_expected[vector_idx][0],
                        iterations_used,
                        iterations_expected[vector_idx],
                        saturation_count,
                        saturation_expected[vector_idx],
                        cycles_elapsed,
                        cycle_min_expected[vector_idx],
                        cycle_max_expected[vector_idx]
                    );
                    failures = failures + 1;
                end else begin
                    $display(
                        "PASS vector=%0d success=%0d iter=%0d sat=%0d cycles=%0d",
                        vector_idx,
                        decoder_success,
                        iterations_used,
                        saturation_count,
                        cycles_elapsed
                    );
                end
            end

            @(posedge clk);
        end

        if (failures != 0) begin
            $display("LDPC decoder simulation failed: %0d failures / %0d vectors", failures, DECODER_VECTOR_COUNT);
            $fatal(1);
        end
        $display("LDPC decoder simulation passed: %0d vectors", DECODER_VECTOR_COUNT);
        $finish;
    end

endmodule

