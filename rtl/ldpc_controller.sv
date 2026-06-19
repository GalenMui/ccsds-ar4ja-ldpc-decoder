`timescale 1ns/1ps

module ldpc_controller #(
    parameter int MAX_ITERS = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic start,
    input  logic initial_syndrome_pass,
    input  logic iteration_syndrome_pass,
    output logic busy,
    output logic done
);

    typedef enum logic [1:0] {
        CTRL_IDLE,
        CTRL_BUSY,
        CTRL_DONE
    } ctrl_state_t;

    ctrl_state_t state;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= CTRL_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            case (state)
                CTRL_IDLE: begin
                    done <= 1'b0;
                    busy <= start;
                    if (start) begin
                        state <= CTRL_BUSY;
                    end
                end
                CTRL_BUSY: begin
                    busy <= 1'b1;
                    if (initial_syndrome_pass || iteration_syndrome_pass) begin
                        state <= CTRL_DONE;
                    end
                end
                CTRL_DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    if (!start) begin
                        state <= CTRL_IDLE;
                    end
                end
            endcase
        end
    end

endmodule

