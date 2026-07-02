`timescale 1ns/1ps

module ldpc_axis_decoder_ip #(
    parameter int LLR_W = 8,
    parameter int MSG_W = 8,
    parameter int MAX_ITERS = 8
) (
    input  logic        aclk,
    input  logic        aresetn,

    input  logic        s_axis_tvalid,
    output logic        s_axis_tready,
    input  logic [31:0] s_axis_tdata,
    input  logic        s_axis_tlast,

    output logic        m_axis_tvalid,
    input  logic        m_axis_tready,
    output logic [31:0] m_axis_tdata,
    output logic        m_axis_tlast,

    output logic        frame_error,
    output logic        early_tlast_error,
    output logic        missing_tlast_error
);

    logic rst;

    assign rst = ~aresetn;

    ldpc_axis_wrapper #(
        .LLR_W(LLR_W),
        .MSG_W(MSG_W),
        .MAX_ITERS(MAX_ITERS)
    ) axis_wrapper (
        .clk(aclk),
        .rst(rst),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tlast(s_axis_tlast),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tlast(m_axis_tlast),
        .frame_error(frame_error),
        .early_tlast_error(early_tlast_error),
        .missing_tlast_error(missing_tlast_error)
    );

endmodule
