`timescale 1ns/1ps
//
// pynq_z2_top.sv
// -----------------------------------------------------------------------------
// Minimal PYNQ-Z2 board bring-up top for the CCSDS AR4JA LDPC decoder.
//
// PURPOSE
//   Provide a synthesizable, board-level wrapper whose ONLY external I/O are
//   real, verifiable PYNQ-Z2 board resources (system clock, a push button, and
//   the 4 user LEDs).  It instantiates the existing decoder IP top
//   (ldpc_axis_decoder_ip) so that the real decoder logic is placed, routed and
//   exercised on the fabric, and surfaces coarse liveness/status on the LEDs.
//
// WHAT THIS TOP DOES
//   * Brings the board clock/reset in through real board-level ports.
//   * Runs a free-running heartbeat counter -> LED0 (proves the design is
//     clocked and out of reset).
//   * Contains a SMALL internal bring-up stimulus generator that streams
//     pseudo-random words into the decoder's AXI-Stream slave port and always
//     accepts the master port.  This keeps the full decoder datapath alive
//     through synthesis/implementation instead of being constant-folded away.
//   * Surfaces decoder activity/status on LED1..LED3 (input handshake, output
//     handshake, and a sticky error indicator).
//
// WHAT THIS TOP DOES **NOT** DO / PROVE
//   * The internal stimulus is NOT valid CCSDS codeword data.  A lit "output
//     activity" or "error" LED therefore says nothing about decode correctness.
//     Functional correctness is proven only by the simulation testbenches and
//     the Python/RTL regression, NOT by this board top.
//   * There is NO connection to the Zynq PS, AXI DMA, or DDR here.  This is a
//     PL-only bring-up top.  Real data movement requires the PS/AXI-DMA block
//     design (see boards/pynq_z2/vivado/pynq_z2_build.tcl) and is future work.
//   * Timing closure at the full board clock is a known open item (see docs).
//
// PORTS ARE INTENTIONALLY MINIMAL so that every one maps to a pin that is
// documented in constraints/pynq_z2.xdc.  Do NOT widen the decoder buses out
// to package pins.
// -----------------------------------------------------------------------------

module pynq_z2_top #(
    // Decoder configuration (kept identical to the IP defaults so the board top
    // synthesizes the same core the rest of the flow targets).
    parameter int LLR_W     = 8,
    parameter int MSG_W     = 8,
    parameter int MAX_ITERS = 8,
    parameter int LANES     = 8
) (
    // 125 MHz single-ended fabric clock (PYNQ-Z2 "sysclk", pin H16).
    input  logic       sysclk,
    // Active-high reset push button (PYNQ-Z2 BTN0, pin D19).  Synchronized and
    // used as the design reset.  If you prefer a different button, update the
    // XDC accordingly.
    input  logic       rst_btn,
    // 4 user LEDs LD0..LD3.
    output logic [3:0] led
);

    // -------------------------------------------------------------------------
    // Reset synchronizer: de-bounce is not required for bring-up, but a 2-FF
    // synchronizer avoids metastability on the asynchronous button.  aresetn is
    // active-low as expected by the AXI-Stream IP.
    // -------------------------------------------------------------------------
    logic [1:0] rst_sync;
    logic       aresetn;

    always_ff @(posedge sysclk) begin
        rst_sync <= {rst_sync[0], rst_btn};
    end
    assign aresetn = ~rst_sync[1];

    // -------------------------------------------------------------------------
    // Heartbeat: free-running counter, MSB drives LED0 so a working, clocked
    // design produces a visible ~sub-Hz blink.
    // -------------------------------------------------------------------------
    localparam int HB_W = 26;
    logic [HB_W-1:0] heartbeat;

    always_ff @(posedge sysclk) begin
        if (!aresetn)
            heartbeat <= '0;
        else
            heartbeat <= heartbeat + 1'b1;
    end

    // -------------------------------------------------------------------------
    // Bring-up stimulus generator (NOT real CCSDS data).
    //
    // A 32-bit LFSR feeds s_axis_tdata.  We drive tvalid continuously and mark
    // tlast every INPUT_WORDS-1 beats so the wrapper's framing FSM advances
    // through real states.  The exact frame length does not need to match the
    // decoder's expected codeword length for bring-up; the goal is simply to
    // keep the datapath toggling so it is not optimized away.
    // -------------------------------------------------------------------------
    logic [31:0] lfsr;
    always_ff @(posedge sysclk) begin
        if (!aresetn)
            lfsr <= 32'hACE1_2345;              // non-zero seed
        else if (s_axis_tready)                 // advance only on accepted beats
            lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
    end

    // Emit a tlast roughly once per notional frame so the framing FSM cycles.
    localparam int STIM_FRAME_WORDS = 512;
    logic [$clog2(STIM_FRAME_WORDS)-1:0] stim_word_ctr;
    logic stim_tlast;
    always_ff @(posedge sysclk) begin
        if (!aresetn) begin
            stim_word_ctr <= '0;
        end else if (s_axis_tvalid && s_axis_tready) begin
            if (stim_word_ctr == STIM_FRAME_WORDS[$bits(stim_word_ctr)-1:0] - 1'b1)
                stim_word_ctr <= '0;
            else
                stim_word_ctr <= stim_word_ctr + 1'b1;
        end
    end
    assign stim_tlast = (stim_word_ctr == STIM_FRAME_WORDS[$bits(stim_word_ctr)-1:0] - 1'b1);

    // AXI-Stream nets between the stimulus/sink and the decoder IP.
    logic        s_axis_tvalid;
    logic        s_axis_tready;
    logic [31:0] s_axis_tdata;
    logic [3:0]  s_axis_tkeep;
    logic        s_axis_tlast;

    logic        m_axis_tvalid;
    logic        m_axis_tready;
    logic [31:0] m_axis_tdata;
    logic [3:0]  m_axis_tkeep;
    logic        m_axis_tlast;

    logic frame_error;
    logic early_tlast_error;
    logic missing_tlast_error;
    logic tkeep_error;

    assign s_axis_tvalid = 1'b1;                // always offering data
    assign s_axis_tdata  = lfsr;
    assign s_axis_tkeep  = 4'hf;
    assign s_axis_tlast  = stim_tlast;
    assign m_axis_tready = 1'b1;                // always draining output

    // -------------------------------------------------------------------------
    // Decoder IP instance (the real design under bring-up).
    // -------------------------------------------------------------------------
    ldpc_axis_decoder_ip #(
        .LLR_W    (LLR_W),
        .MSG_W    (MSG_W),
        .MAX_ITERS(MAX_ITERS),
        .LANES    (LANES)
    ) u_decoder (
        .aclk               (sysclk),
        .aresetn            (aresetn),
        .s_axis_tvalid      (s_axis_tvalid),
        .s_axis_tready      (s_axis_tready),
        .s_axis_tdata       (s_axis_tdata),
        .s_axis_tkeep       (s_axis_tkeep),
        .s_axis_tlast       (s_axis_tlast),
        .m_axis_tvalid      (m_axis_tvalid),
        .m_axis_tready      (m_axis_tready),
        .m_axis_tdata       (m_axis_tdata),
        .m_axis_tkeep       (m_axis_tkeep),
        .m_axis_tlast       (m_axis_tlast),
        .frame_error        (frame_error),
        .early_tlast_error  (early_tlast_error),
        .missing_tlast_error(missing_tlast_error),
        .tkeep_error        (tkeep_error)
    );

    // -------------------------------------------------------------------------
    // Status capture -> LEDs.
    //   LED0 : heartbeat (design is clocked and running)
    //   LED1 : input handshake activity (stretched)
    //   LED2 : output handshake activity (stretched, decoder produced output)
    //   LED3 : sticky error flag (any framing/tkeep error seen since reset)
    // The output-word bits (m_axis_tdata) are folded into the sticky/error
    // logic so the decoder output cannot be trimmed away.
    // -------------------------------------------------------------------------
    logic in_seen, out_seen, err_sticky;
    logic out_data_parity;

    always_ff @(posedge sysclk) begin
        if (!aresetn) begin
            in_seen         <= 1'b0;
            out_seen        <= 1'b0;
            err_sticky      <= 1'b0;
            out_data_parity <= 1'b0;
        end else begin
            if (s_axis_tvalid && s_axis_tready)
                in_seen <= 1'b1;
            if (m_axis_tvalid && m_axis_tready) begin
                out_seen        <= 1'b1;
                out_data_parity <= out_data_parity ^ (^{m_axis_tdata, m_axis_tlast, m_axis_tkeep});
            end
            err_sticky <= err_sticky | frame_error | early_tlast_error |
                          missing_tlast_error | tkeep_error;
        end
    end

    // Slow "activity" strobe from the heartbeat so brief pulses are visible.
    logic activity_window;
    assign activity_window = heartbeat[HB_W-1];

    assign led[0] = heartbeat[HB_W-1];
    assign led[1] = in_seen & activity_window;
    assign led[2] = out_seen ^ out_data_parity;   // ties out data into the LED cone
    assign led[3] = err_sticky;

endmodule
