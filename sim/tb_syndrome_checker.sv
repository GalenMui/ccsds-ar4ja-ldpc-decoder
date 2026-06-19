`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module tb_syndrome_checker;
    `include "vectors/syndrome/syndrome_meta.svh"

    logic [TX_N-1:0] codeword_bits;
    logic [CHECKS-1:0] syndrome;
    logic syndrome_pass;

    logic [TX_N-1:0] tx_vectors [0:SYNDROME_VECTOR_COUNT-1];
    logic [CHECKS-1:0] syndrome_vectors [0:SYNDROME_VECTOR_COUNT-1];
    logic pass_vectors [0:SYNDROME_VECTOR_COUNT-1];

    integer vector_idx;
    integer failures;
    integer bit_idx;
    integer first_bad;

    syndrome_checker dut (
        .codeword_bits(codeword_bits),
        .syndrome(syndrome),
        .syndrome_pass(syndrome_pass)
    );

    initial begin
        $readmemh("vectors/syndrome/tx.mem", tx_vectors);
        $readmemh("vectors/syndrome/syndrome.mem", syndrome_vectors);
        $readmemb("vectors/syndrome/pass.mem", pass_vectors);

        failures = 0;
        for (vector_idx = 0; vector_idx < SYNDROME_VECTOR_COUNT; vector_idx = vector_idx + 1) begin
            codeword_bits = tx_vectors[vector_idx];
            #1;

            if (syndrome !== syndrome_vectors[vector_idx] ||
                syndrome_pass !== pass_vectors[vector_idx]) begin
                failures = failures + 1;
                first_bad = -1;
                for (bit_idx = 0; bit_idx < CHECKS; bit_idx = bit_idx + 1) begin
                    if (first_bad < 0 && syndrome[bit_idx] !== syndrome_vectors[vector_idx][bit_idx]) begin
                        first_bad = bit_idx;
                    end
                end
                $display(
                    "FAIL vector=%0d pass got=%0d expected=%0d first_bad_syndrome=%0d",
                    vector_idx,
                    syndrome_pass,
                    pass_vectors[vector_idx],
                    first_bad
                );
            end else begin
                $display("PASS vector=%0d syndrome_weight=%0d", vector_idx, count_ones(syndrome));
            end
        end

        if (failures != 0) begin
            $display(
                "Syndrome checker simulation failed: %0d failures / %0d vectors",
                failures,
                SYNDROME_VECTOR_COUNT
            );
            $fatal(1);
        end
        $display("Syndrome checker simulation passed: %0d vectors", SYNDROME_VECTOR_COUNT);
        $finish;
    end

    function automatic integer count_ones(input logic [CHECKS-1:0] bits);
        integer idx;
        begin
            count_ones = 0;
            for (idx = 0; idx < CHECKS; idx = idx + 1) begin
                if (bits[idx]) begin
                    count_ones = count_ones + 1;
                end
            end
        end
    endfunction

endmodule

