`timescale 1ns / 1ps
module sequencer_fsm_tb();

    localparam CLOCK_PERIOD = 10;

    logic                   clk;
    logic                   reset_i;
    logic                   lut_wen_i;
    logic [28:0]            lut_write_data_i;
    logic                   lut_rden_i;
    wire  [28:0]            lut_read_data_o;
    wire  [2:0]             current_state_o;
    wire  logic             busy_o;
    wire  logic             sequence_done_o;
    wire  logic             panel_enable_o;
    wire  logic             bias_enable_o;
    wire  logic             flush_enable_o;
    wire  logic             expose_enable_o;
    wire  logic             readout_enable_o;
    wire  logic             aed_enable_o;
    wire  [7:0]             current_repeat_count_o;
    wire  [15:0]            current_data_length_o;
    wire  [0:0]             current_eof_o;
    wire  [0:0]             current_sof_o;

    sequencer_fsm dut (
        .clk(clk),
        .reset_i(reset_i),
        .lut_wen_i(lut_wen_i),
        .lut_write_data_i(lut_write_data_i),
        .lut_rden_i(lut_rden_i),
        .lut_read_data_o(lut_read_data_o),
        .current_state_o(current_state_o),
        .busy_o(busy_o),
        .sequence_done_o(sequence_done_o),
        .panel_enable_o(panel_enable_o),
        .bias_enable_o(bias_enable_o),
        .flush_enable_o(flush_enable_o),
        .expose_enable_o(expose_enable_o),
        .readout_enable_o(readout_enable_o),
        .aed_enable_o(aed_enable_o),
        .current_repeat_count_o(current_repeat_count_o),
        .current_data_length_o(current_data_length_o),
        .current_eof_o(current_eof_o),
        .current_sof_o(current_sof_o)
    );

    always #(CLOCK_PERIOD / 2) clk = ~clk;

    initial begin
        clk = 1'b0;
        reset_i = 1'b1;
        lut_wen_i = 1'b0;
        lut_write_data_i = 29'd0;
        lut_rden_i = 1'b0;

        repeat(2) @(posedge clk);
        reset_i = 1'b0;
        @(posedge clk);

        function automatic logic [28:0] pack_lut_entry(
            input logic [2:0] next_state_in,
            input logic [7:0] repeat_count_in,
            input logic [15:0] data_length_in,
            input logic [0:0] eof_in,
            input logic [0:0] sof_in
        );
            pack_lut_entry = (sof_in         << 28) |
                             (eof_in         << 27) |
                             (data_length_in << 11) |
                             (repeat_count_in << 3) |
                             (next_state_in  << 0);
        endfunction

        // Simulate loading LUT RAM via write port in RST state
        reset_i = 1'b1;
        @(posedge clk);

        lut_wen_i = 1'b1;
        // FSM State Parameters for TB Functions
        localparam logic [2:0] RST = 3'b0;
        localparam logic [2:0] IDLE = 3'b1;
        localparam logic [2:0] PANEL_STABLE = 3'b2;
        localparam logic [2:0] BACK_BIAS = 3'b3;
        localparam logic [2:0] FLUSH = 3'b4;
        localparam logic [2:0] AED_DETECT = 3'b5;
        localparam logic [2:0] EXPOSE_TIME = 3'b6;
        localparam logic [2:0] READOUT = 3'b7;

        lut_write_data_i = pack_lut_entry(PANEL_STABLE, 8'd2, 16'd50, 1'b0, 1'b0);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(BACK_BIAS, 8'd3, 16'd10, 1'b0, 1'b0);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(FLUSH, 8'd2, 16'd30, 1'b0, 1'b0);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(EXPOSE_TIME, 8'd1, 16'd50, 1'b0, 1'b0);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(READOUT, 8'd1, 16'd40, 1'b0, 1'b0);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(IDLE, 8'd1, 16'd20, 1'b1, 1'b0);
        @(posedge clk);

        lut_wen_i = 1'b0;
        reset_i = 1'b0;
        @(posedge clk);

        // Monitor and simulate sequence for a duration
        repeat(5000) @(posedge clk);

        $finish;
    end

    initial begin
        $dumpfile("sequencer_fsm_tb.vcd");
        $dumpvars(0, sequencer_fsm_tb);
        $display("Time\tState\tBusy\tSeqDone\tAddr\tRptCnt\tDataLen\tEOF\tSOF");
        $monitor("%0t\t%h\t%b\t%b\t%h\t%d\t%d\t%b\t%b",
                 $time, current_state_o, busy_o, sequence_done_o,
                 dut.lut_addr_reg, current_repeat_count_o, current_data_length_o,
                 current_eof_o, current_sof_o);
    end

endmodule