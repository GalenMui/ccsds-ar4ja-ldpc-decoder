`timescale 1ns/1ps

module variable_node_unit #(
    parameter int MSG_W = 8,
    parameter int MAX_DEGREE = 6
) (
    input  logic signed [MSG_W-1:0]         channel_llr,
    input  logic [$clog2(MAX_DEGREE+1)-1:0] degree,
    input  logic signed [MSG_W-1:0]         c_to_v [0:MAX_DEGREE-1],
    output logic signed [MSG_W-1:0]         posterior_llr,
    output logic signed [MSG_W-1:0]         v_to_c [0:MAX_DEGREE-1],
    output logic                            hard_bit,
    output logic [31:0]                     saturation_events
);

    localparam integer MIN_VALUE = -(1 << (MSG_W - 1));
    localparam integer MAX_VALUE =  (1 << (MSG_W - 1)) - 1;

    integer edge_idx;
    integer total;
    integer clipped_total;
    integer msg_value;
    integer clipped_msg;

    always_comb begin
        total = channel_llr;
        saturation_events = 0;
        for (edge_idx = 0; edge_idx < MAX_DEGREE; edge_idx = edge_idx + 1) begin
            if (edge_idx < degree) begin
                total = total + c_to_v[edge_idx];
            end
        end

        if (total < MIN_VALUE) begin
            clipped_total = MIN_VALUE;
            saturation_events = saturation_events + 1;
        end else if (total > MAX_VALUE) begin
            clipped_total = MAX_VALUE;
            saturation_events = saturation_events + 1;
        end else begin
            clipped_total = total;
        end

        posterior_llr = clipped_total[MSG_W-1:0];
        hard_bit = (clipped_total < 0);

        for (edge_idx = 0; edge_idx < MAX_DEGREE; edge_idx = edge_idx + 1) begin
            v_to_c[edge_idx] = '0;
            if (edge_idx < degree) begin
                msg_value = clipped_total - c_to_v[edge_idx];
                if (msg_value < MIN_VALUE) begin
                    clipped_msg = MIN_VALUE;
                    saturation_events = saturation_events + 1;
                end else if (msg_value > MAX_VALUE) begin
                    clipped_msg = MAX_VALUE;
                    saturation_events = saturation_events + 1;
                end else begin
                    clipped_msg = msg_value;
                end
                v_to_c[edge_idx] = clipped_msg[MSG_W-1:0];
            end
        end
    end

endmodule
