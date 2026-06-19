`timescale 1ns/1ps

import ar4ja_1024_pkg::*;

module syndrome_checker #(
    parameter int TX_N_PARAM = ar4ja_1024_pkg::TX_N,
    parameter int FULL_N_PARAM = ar4ja_1024_pkg::FULL_N,
    parameter int M_PARAM = ar4ja_1024_pkg::M,
    parameter int CHECKS_PARAM = ar4ja_1024_pkg::CHECKS
) (
    input  logic [TX_N_PARAM-1:0]     codeword_bits,
    output logic [CHECKS_PARAM-1:0]   syndrome,
    output logic                      syndrome_pass
);

    logic [FULL_N_PARAM-1:0] full_codeword_bits;
    integer i;
    integer edge_idx;
    integer row_idx;

    always_comb begin
        full_codeword_bits = '0;

        for (i = 0; i < TX_N_PARAM; i = i + 1) begin
            full_codeword_bits[i] = codeword_bits[i];
        end

        for (i = 0; i < M_PARAM; i = i + 1) begin
            // Reconstruct full-codeword columns 2048..2559 from the third
            // check block. This matches the Python PUNCTURE_SOLVE policy.
            full_codeword_bits[TX_N_PARAM + i] = 1'b0;
            for (
                edge_idx = 0;
                edge_idx < ar4ja_1024_pkg::MAX_PUNCTURE_WEIGHT;
                edge_idx = edge_idx + 1
            ) begin
                if (edge_idx < ar4ja_1024_pkg::puncture_weight(i)) begin
                    full_codeword_bits[TX_N_PARAM + i] =
                        full_codeword_bits[TX_N_PARAM + i] ^
                        codeword_bits[ar4ja_1024_pkg::puncture_col(i, edge_idx)];
                end
            end
        end

        syndrome = '0;
        for (row_idx = 0; row_idx < CHECKS_PARAM; row_idx = row_idx + 1) begin
            for (
                edge_idx = 0;
                edge_idx < ar4ja_1024_pkg::MAX_ROW_WEIGHT;
                edge_idx = edge_idx + 1
            ) begin
                if (edge_idx < ar4ja_1024_pkg::row_weight(row_idx)) begin
                    syndrome[row_idx] =
                        syndrome[row_idx] ^
                        full_codeword_bits[ar4ja_1024_pkg::row_col(row_idx, edge_idx)];
                end
            end
        end

        syndrome_pass = ~(|syndrome);
    end

endmodule
