//-----------------------------------------------------------------------------
// Project      : FPGA Sequencer FSM
// File         : sequencer_fsm_tb.sv
// Author       : [Your Name]
// Reviewer     : [Reviewer Name]
// Company      : [Your Company]
// Department   : [Your Department]
// Created      : [YYYY-MM-DD]
// Version      : 1.0
// Tool Version : [Tool/Simulator Version]
// Description  : 
//   - Testbench for sequencer_fsm module.
//   - Verifies state transitions, LUT RAM operation, repeat/timer/exit logic.
//   - Monitors sequence_done and state outputs.
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

// Sequencer FSM Testbench
// - Tests FSM state transitions, LUT RAM operations, and sequence execution
// - Verifies repeat, timer, and exit signal handling
// - Monitors state changes and sequence completion
module sequencer_fsm_tb();

    // Clock period definition
    localparam CLOCK_PERIOD = 10;

    // DUT Interface Signals
    // Clock and Reset
    logic                   clk;
    logic                   reset_i;

    // LUT RAM Interface
    logic                   lut_wen_i;
    logic [36:0]            lut_write_data_i;
    logic                   lut_rden_i;
    wire  [36:0]            lut_read_data_o;

    // Control Signals
    logic                   config_done_i;
    logic                   exit_signal_i;

    // FSM Status Outputs
    wire  [2:0]             current_state_o;
    wire  logic             busy_o;
    wire  logic             sequence_done_o;

    // Command Enable Outputs
    wire  logic             panel_enable_o;
    wire  logic             bias_enable_o;
    wire  logic             flush_enable_o;
    wire  logic             expose_enable_o;
    wire  logic             readout_enable_o;
    wire  logic             aed_enable_o;

    // Current Command Parameters
    wire  [7:0]             current_repeat_count_o;
    wire  [15:0]            current_data_length_o;
    wire  [0:0]             current_eof_o;
    wire  [0:0]             current_sof_o;

    // FSM State Definitions
    localparam logic [2:0] RST = 3'd0;           // Reset state
    localparam logic [2:0] IDLE = 3'd1;          // Idle state
    localparam logic [2:0] PANEL_STABLE = 3'd2;  // Panel stable state
    localparam logic [2:0] BACK_BIAS = 3'd3;     // Back bias state
    localparam logic [2:0] FLUSH = 3'd4;         // Flush state
    localparam logic [2:0] AED_DETECT = 3'd5;    // AED detect state
    localparam logic [2:0] EXPOSE_TIME = 3'd6;   // Expose time state
    localparam logic [2:0] READOUT = 3'd7;       // Readout state

    // Instantiate DUT
    sequencer_fsm dut (
        .clk(clk),
        .reset_i(reset_i),
        .lut_wen_i(lut_wen_i),
        .lut_write_data_i(lut_write_data_i),
        .lut_rden_i(lut_rden_i),
        .config_done_i(config_done_i),
        .exit_signal_i(exit_signal_i),
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

    // Clock generation
    always #(CLOCK_PERIOD / 2) clk = ~clk;

    // Helper function to pack LUT entry data
    function automatic logic [36:0] pack_lut_entry(
        input logic [2:0] next_state_in,
        input logic [7:0] repeat_count_in,
        input logic [15:0] data_length_in,
        input logic [0:0] eof_in,
        input logic [0:0] sof_in,
        input logic [7:0] next_address_in
    );
        pack_lut_entry = (next_address_in << 29) |
                        (sof_in         << 28) |
                        (eof_in         << 27) |
                        (data_length_in << 11) |
                        (repeat_count_in << 3) |
                        (next_state_in  << 0);
    endfunction

    // Helper function to convert state encoding to string
    function string state_to_str(input logic [2:0] state);
        case (state)
            3'd0: state_to_str = "RST";
            3'd1: state_to_str = "IDLE";
            3'd2: state_to_str = "PANEL_STABLE";
            3'd3: state_to_str = "BACK_BIAS";
            3'd4: state_to_str = "FLUSH";
            3'd5: state_to_str = "AED_DETECT";
            3'd6: state_to_str = "EXPOSE_TIME";
            3'd7: state_to_str = "READOUT";
            default: state_to_str = "UNKNOWN";
        endcase
    endfunction

    // Monitor state changes and command parameters
    initial begin
        $display("Time\tState\tRepeat\tLen\tEOF\tSOF");
        forever begin
            @(posedge clk);
            $display("%0t\t%s\t%0d\t%0d\t%b\t%b",
                $time,
                state_to_str(current_state_o),
                current_repeat_count_o,
                current_data_length_o,
                current_eof_o,
                current_sof_o
            );
        end
    end

    // Main test sequence
    initial begin
        // Initialize signals
        clk = 1'b0;
        reset_i = 1'b1;
        lut_wen_i = 1'b0;
        lut_write_data_i = 37'd0;
        lut_rden_i = 1'b0;
        config_done_i = 1'b1;
        exit_signal_i = 1'b0;

        // Wait for reset
        repeat(2) @(posedge clk);
        #4 reset_i = 1'b0;
        @(posedge clk);

        // Enter RST state for LUT RAM configuration
        #4 reset_i = 1'b1;
        repeat(4) @(posedge clk);
        config_done_i = 1'b0;

        #4 reset_i = 1'b0;
        @(posedge clk);

        // Write LUT RAM entries
        lut_wen_i = 1'b1;

        // Write test sequence to LUT RAM
        // Format: state, repeat, len, eof, sof, next_addr
        lut_write_data_i = pack_lut_entry(PANEL_STABLE, 8'd0, 16'd5, 1'b0, 1'b0, 8'd1);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(BACK_BIAS, 8'd3, 16'd10, 1'b0, 1'b0, 8'd2);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(FLUSH, 8'd2, 16'd20, 1'b0, 1'b0, 8'd3);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(BACK_BIAS, 8'd3, 16'd10, 1'b0, 1'b0, 8'd4);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(FLUSH, 8'd2, 16'd20, 1'b0, 1'b0, 8'd5);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(EXPOSE_TIME, 8'd0, 16'd50, 1'b0, 1'b0, 8'd6);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(READOUT, 8'd0, 16'd40, 1'b1, 1'b0, 8'd7);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(IDLE, 8'd1, 16'd1, 1'b0, 1'b0, 8'd5);
        @(posedge clk);

        lut_write_data_i = pack_lut_entry(EXPOSE_TIME, 8'd0, 16'd50, 1'b0, 1'b0, 8'd9);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(READOUT, 8'd0, 16'd40, 1'b1, 1'b0, 8'd10);
        @(posedge clk);

        lut_write_data_i = pack_lut_entry(BACK_BIAS, 8'd0, 16'd10, 1'b0, 1'b0, 8'd11);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(FLUSH, 8'd1, 16'd20, 1'b1, 1'b0, 8'd12);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(IDLE, 8'd1, 16'd1, 1'b0, 1'b0, 8'd10);
        @(posedge clk);

        lut_write_data_i = pack_lut_entry(EXPOSE_TIME, 8'd0, 16'd50, 1'b0, 1'b0, 8'd14);
        @(posedge clk);
        lut_write_data_i = pack_lut_entry(READOUT, 8'd0, 16'd40, 1'b0, 1'b0, 8'd10);
        @(posedge clk);


        lut_wen_i = 1'b0;
        repeat(2) @(posedge clk);

        config_done_i = 1'b1;
        #10;

        repeat(500) @(posedge clk);
        exit_signal_i = 1'b1;

        wait (sequence_done_o == 1'b1);
        $display("Sequence completed successfully.");
        exit_signal_i = 1'b0;

        // Wait for sequence execution
        repeat(300) @(posedge clk);

        // Test exit signal handling
        exit_signal_i = 1'b1;
        wait (sequence_done_o == 1'b1);
        $display("Sequence completed successfully.");
        exit_signal_i = 1'b0;

        // Test second exit signal
        repeat(490) @(posedge clk);
        exit_signal_i = 1'b1;
        wait (sequence_done_o == 1'b1);
        $display("Sequence completed successfully.");
        exit_signal_i = 1'b0;

        // Continue monitoring
        repeat(5000) @(posedge clk);

        $finish;
    end

    // Waveform dump setup
    initial begin
        $dumpfile("sequencer_fsm_tb.vcd");
        $dumpvars(0, sequencer_fsm_tb);
        $display("Time\tState\tBusy\tSeqDone\tAddr\tRptCnt\tDataLen\tEOF\tSOF");
        $monitor("%0t\t%h\t%b\t%b\t%h\t%d\t%d\t%b\t%b",
                 $time, current_state_o, busy_o, sequence_done_o,
                 dut.lut_addr_reg, current_repeat_count_o, current_data_length_o,
                 current_eof_o, current_sof_o);
    end

    // Verify LUT RAM initialization
    initial begin
        $display("Checking LUT RAM initial values:");
        for (int i = 0; i < 6; i++) begin
            $display("LUT RAM[%0d] = %h", i, dut.internal_lut_ram[i]);
        end
    end

endmodule