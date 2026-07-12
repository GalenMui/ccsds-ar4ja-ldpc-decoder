`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// Gate B experiment: reproduce, verbatim, the internal banked-RAM pattern used
// by ldpc_decoder_top (g_posterior_banks / g_message_banks) so we can prove in
// isolation that Vivado infers block RAM for it -- fast -- before paying for a
// full decoder synth.
//
// The banks are kept INTERNAL (as in the real decoder); a trivial registered
// driver exercises every bank from a handful of scalar top-level ports so none
// are optimised away and each sees exactly one read + one write address stream.
//
// Params mirror the LANES=8 decoder: P=8, BANK_DEPTH=320 (=FULL_N/8),
// GROUPS=192 (=CHECKS/8), ROW_MSG_W=48 (=MAX_ROW_WEIGHT*MSG_W).
// -----------------------------------------------------------------------------
module bank_experiment #(
    parameter int P          = 8,
    parameter int LLR_W      = 8,
    parameter int BANK_DEPTH = 320,
    parameter int GROUPS      = 192,
    parameter int ROW_MSG_W  = 48
) (
    input  logic clk,

    // posterior bank stimulus
    input  logic                              p_we,
    input  logic                              p_re,
    input  logic [$clog2(BANK_DEPTH)-1:0]     p_waddr,
    input  logic [$clog2(BANK_DEPTH)-1:0]     p_raddr,
    input  logic signed [LLR_W-1:0]           p_wdata,
    output logic signed [LLR_W-1:0]           p_rdata,

    // message bank stimulus
    input  logic                              m_we,
    input  logic                              m_re,
    input  logic [$clog2(GROUPS)-1:0]         m_addr,
    input  logic [ROW_MSG_W-1:0]              m_wdata,
    output logic [ROW_MSG_W-1:0]              m_rdata
);
    localparam int BANK_ADDR_BITS = $clog2(BANK_DEPTH);

    // Per-bank posterior ports (identical shape to decoder_top).
    logic                       pmem_we    [0:P-1];
    logic [BANK_ADDR_BITS-1:0]  pmem_waddr [0:P-1];
    logic signed [LLR_W-1:0]    pmem_wdata [0:P-1];
    logic                       pmem_re    [0:P-1];
    logic [BANK_ADDR_BITS-1:0]  pmem_raddr [0:P-1];
    logic signed [LLR_W-1:0]    posterior_read_data [0:P-1];

    logic                       mmem_we    [0:P-1];
    logic [ROW_MSG_W-1:0]       mmem_wdata [0:P-1];
    logic                       mmem_re    [0:P-1];
    logic [ROW_MSG_W-1:0]       message_read_data [0:P-1];

    // Registered fan-out so every bank is exercised and none collapse.
    always_comb begin
        for (int b = 0; b < P; b = b + 1) begin
            pmem_we[b]    = p_we;
            pmem_re[b]    = p_re;
            pmem_waddr[b] = p_waddr;
            pmem_raddr[b] = p_raddr;
            pmem_wdata[b] = p_wdata + b[LLR_W-1:0];
            mmem_we[b]    = m_we;
            mmem_re[b]    = m_re;
            mmem_wdata[b] = m_wdata ^ {ROW_MSG_W{b[0]}};
        end
    end

    // XOR-reduce the P read ports back to a scalar output so all banks matter.
    always_comb begin
        p_rdata = '0;
        m_rdata = '0;
        for (int b = 0; b < P; b = b + 1) begin
            p_rdata = p_rdata ^ posterior_read_data[b];
            m_rdata = m_rdata ^ message_read_data[b];
        end
    end

    logic [$clog2(GROUPS)-1:0] group_idx;
    assign group_idx = m_addr;

    // ---- verbatim posterior banks ----
    genvar gp;
    generate
        for (gp = 0; gp < P; gp = gp + 1) begin : g_posterior_banks
            (* ram_style = "block" *)
            logic signed [LLR_W-1:0] bank_mem [0:BANK_DEPTH-1];
            always_ff @(posedge clk) begin
                if (pmem_we[gp]) begin
                    bank_mem[pmem_waddr[gp]] <= pmem_wdata[gp];
                end
                if (pmem_re[gp]) begin
                    posterior_read_data[gp] <= bank_mem[pmem_raddr[gp]];
                end
            end
        end
    endgenerate

    // ---- verbatim message banks ----
    genvar gm;
    generate
        for (gm = 0; gm < P; gm = gm + 1) begin : g_message_banks
            (* ram_style = "block" *)
            logic [ROW_MSG_W-1:0] bank_mem [0:GROUPS-1];
            always_ff @(posedge clk) begin
                if (mmem_we[gm]) begin
                    bank_mem[group_idx] <= mmem_wdata[gm];
                end
                if (mmem_re[gm]) begin
                    message_read_data[gm] <= bank_mem[group_idx];
                end
            end
        end
    endgenerate
endmodule
