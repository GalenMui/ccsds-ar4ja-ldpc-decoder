`timescale 1ns/1ps

module check_node_unit #(
    parameter int MSG_W = 8,
    parameter int MAX_DEGREE = 6,
    parameter int ALPHA_NUM = 3,
    parameter int ALPHA_DEN = 4
) (
    input  logic [$clog2(MAX_DEGREE+1)-1:0] degree,
    input  logic signed [MSG_W-1:0]         v_to_c [0:MAX_DEGREE-1],
    output logic signed [MSG_W-1:0]         c_to_v [0:MAX_DEGREE-1],
    output logic [31:0]                     saturation_events
);

    localparam integer MIN_VALUE = -(1 << (MSG_W - 1));
    localparam integer MAX_VALUE =  (1 << (MSG_W - 1)) - 1;

    integer edge_idx;
    integer sign_product;
    integer abs_value;
    integer min1;
    integer min2;
    integer min1_idx;
    integer selected_min;
    integer signed_value;
    integer scaled_value;
    integer clipped_value;

    always_comb begin
        sign_product = 1;
        min1 = 32'h3fffffff;
        min2 = 32'h3fffffff;
        min1_idx = 0;
        saturation_events = 0;

        for (edge_idx = 0; edge_idx < MAX_DEGREE; edge_idx = edge_idx + 1) begin
            if (edge_idx < degree) begin
                if (v_to_c[edge_idx] < 0) begin
                    sign_product = -sign_product;
                    abs_value = -v_to_c[edge_idx];
                end else begin
                    abs_value = v_to_c[edge_idx];
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

        for (edge_idx = 0; edge_idx < MAX_DEGREE; edge_idx = edge_idx + 1) begin
            c_to_v[edge_idx] = '0;
            if (edge_idx < degree) begin
                selected_min = (edge_idx == min1_idx) ? min2 : min1;
                scaled_value = (selected_min * ALPHA_NUM) / ALPHA_DEN;
                if ((sign_product < 0 && v_to_c[edge_idx] >= 0) ||
                    (sign_product > 0 && v_to_c[edge_idx] < 0)) begin
                    signed_value = -scaled_value;
                end else begin
                    signed_value = scaled_value;
                end

                if (signed_value < MIN_VALUE) begin
                    clipped_value = MIN_VALUE;
                    saturation_events = saturation_events + 1;
                end else if (signed_value > MAX_VALUE) begin
                    clipped_value = MAX_VALUE;
                    saturation_events = saturation_events + 1;
                end else begin
                    clipped_value = signed_value;
                end
                c_to_v[edge_idx] = clipped_value[MSG_W-1:0];
            end
        end
    end

endmodule
