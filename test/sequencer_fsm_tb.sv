`timescale 1ns / 1ps

module sequencer_fsm_tb;

    // Testbench Signals
    logic clk;
    logic reset_i;
    logic lut_wen_i;
    logic [28:0] lut_write_data_i;
    logic lut_rden_i;

    // DUT Outputs (connected to TB wires/logics)
    logic [2:0] current_state_o;
    logic busy_o;
    logic sequence_done_o;
    logic [28:0] lut_read_data_o;
    logic panel_enable_o;
    logic bias_enable_o;
    logic flush_enable_o;
    logic expose_enable_o;
    logic readout_enable_o;
    logic aed_enable_o;
    logic [7:0] current_repeat_count_o;
    logic [15:0] current_data_length_o;
    logic [0:0] current_eof_o;
    logic [0:0] current_sof_o;

    // Instantiate Device Under Test (DUT)
    sequencer_fsm dut (
        .clk(clk),
        .reset_i(reset_i),
        .lut_wen_i(lut_wen_i),
        .lut_write_data_i(lut_write_data_i),
        .lut_rden_i(lut_rden_i),
        .current_state_o(current_state_o),
        .busy_o(busy_o),
        .sequence_done_o(sequence_done_o),
        .lut_read_data_o(lut_read_data_o),
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

    // Clock Generation
    always #5 clk = ~clk; // 10ns period, 100MHz clock

    // Main Test Sequence
    initial begin
        clk = 1'b0;
        reset_i = 1'b1; // Assert reset
        lut_wen_i = 1'b0;
        lut_rden_i = 1'b0;
        lut_write_data_i = '0;

        #100; // Hold reset for a while

        // --- LUT RAM Configuration (during RST state) ---
        $display("\n--- Initializing LUT RAM ---");
        reset_i = 1'b1; // Ensure reset is high for LUT write
        lut_wen_i = 1'b1; // Enable LUT write
        lut_rden_i = 1'b0; // Disable LUT read during write

        // Write LUT Entry 0x0: State=PANEL_STABLE, Repeat=5, DataLen=100, EOF=0, SOF=0
        lut_write_data_i = {8'd5, 16'd100, 1'd0, 1'd0, 3'd2};
        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment
        // Write LUT Entry 0x1: State=BACK_BIAS, Repeat=1, DataLen=0, EOF=0, SOF=0
        lut_write_data_i = {8'd1, 16'd0, 1'd0, 1'd0, 3'd3};
        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment
        // Write LUT Entry 0x2: State=FLUSH, Repeat=3, DataLen=256, EOF=0, SOF=0
        lut_write_data_i = {8'd3, 16'd256, 1'd0, 1'd0, 3'd4};
        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment
        // Write LUT Entry 0x3: State=EXPOSE_TIME, Repeat=1, DataLen=5000, EOF=0, SOF=0
        lut_write_data_i = {8'd1, 16'd5000, 1'd0, 1'd0, 3'd6};
        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment
        // Write LUT Entry 0x4: State=READOUT, Repeat=1, DataLen=4096, EOF=1, SOF=0
        lut_write_data_i = {8'd1, 16'd4096, 1'd1, 1'd0, 3'd7};
        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment
        lut_wen_i = 1'b0; // Disable LUT write
        $display("--- LUT RAM Initialized ---\n");

        // De-assert reset to start FSM operation
        reset_i = 1'b0;
        @(posedge clk); // Wait for FSM to transition out of RST

        // --- Monitor FSM State and Outputs ---
        $display("Time\tState\tBusy\tSeqDone\tPanel\tBias\tFlush\tExpose\tReadout\tAED\tRPT\tDATA\tEOF\tSOF\tLUT_ADDR");
        $monitor("%0t\t%s\t%b\t%b\t%b\t%b\t%b\t%b\t%b\t%b\t%d\t%d\t%b\t%b\t%h",
                 $time,
                 state_name_from_encoding(current_state_o),
                 busy_o, sequence_done_o,
                 panel_enable_o, bias_enable_o, flush_enable_o, expose_enable_o, readout_enable_o, aed_enable_o,
                 current_repeat_count_o, current_data_length_o, current_eof_o, current_sof_o,
                 dut.lut_addr_reg);

        #20000; // Run simulation for a substantial amount of time
        $display("\n--- Simulation Timeout ---");
        $finish;
    end

    function string state_name_from_encoding(logic [2:0] encoding);
        case(encoding)
            RST: state_name_from_encoding = "RST";
            IDLE: state_name_from_encoding = "IDLE";
            PANEL_STABLE: state_name_from_encoding = "PANEL_STABLE";
            BACK_BIAS: state_name_from_encoding = "BACK_BIAS";
            FLUSH: state_name_from_encoding = "FLUSH";
            AED_DETECT: state_name_from_encoding = "AED_DETECT";
            EXPOSE_TIME: state_name_from_encoding = "EXPOSE_TIME";
            READOUT: state_name_from_encoding = "READOUT";
            default: state_name_from_encoding = "UNKNOWN";
        endcase
    endfunction

endmodule