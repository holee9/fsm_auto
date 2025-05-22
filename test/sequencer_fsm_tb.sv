`timescale 1ns / 1ps

module sequencer_fsm_tb;

    // Clock and Reset signals
    logic clk;
    logic reset_i;
    logic exit_signal_i; // External signal for infinite loop exit

    // LUT RAM interface signals
    logic lut_wen_i; // LUT Write Enable (active high, only in RST state)
    logic [28:0] lut_write_data_i; // Data to write to LUT RAM
    logic lut_rden_i; // LUT Read Enable (active high, only in RST state)
    wire [28:0] lut_read_data_o; // Data read from LUT RAM

    // FSM Outputs
    wire [2:0] current_state_o;
    wire busy_o;
    wire sequence_done_o;
    wire panel_enable_o;
    wire bias_enable_o;
    wire flush_enable_o;
    wire expose_enable_o;
    wire readout_enable_o;
    wire aed_enable_o;
    wire [7:0] current_repeat_count_o;
    wire [15:0] current_data_length_o;
    wire [0:0] current_eof_o;
    wire [0:0] current_sof_o;

    // Instantiate FSM module
    sequencer_fsm u_fsm (
        .clk(clk),
        .reset_i(reset_i),
        .exit_signal_i(exit_signal_i),
        .lut_wen_i(lut_wen_i),
        .lut_write_data_i(lut_write_data_i),
        .lut_rden_i(lut_rden_i),
        .lut_read_data_o(lut_read_data_o),
        .current_state_o(current_state_o),
        .busy_o(busy_o),
        .sequence_done_o(sequence_done_o)
        ,.panel_enable_o(panel_enable_o)
        ,.bias_enable_o(bias_enable_o)
        ,.flush_enable_o(flush_enable_o)
        ,.expose_enable_o(expose_enable_o)
        ,.readout_enable_o(readout_enable_o)
        ,.aed_enable_o(aed_enable_o)
        ,.current_repeat_count_o(current_repeat_count_o)
        ,.current_data_length_o(current_data_length_o)
        ,.current_eof_o(current_eof_o)
        ,.current_sof_o(current_sof_o)
    );

    // Clock Generation
    initial begin
        clk = 0;
        forever #5 clk = ~clk; // 10ns period, 100MHz clock
    end

    // Test Scenario
    initial begin
        $dumpfile("sequencer_fsm_tb.vcd");
        $dumpvars(0, {fsm_module_name}_tb);

        // 1. Initial Reset
        reset_i = 1;
        lut_wen_i = 0;
        lut_rden_i = 0;
        lut_write_data_i = '0;
        exit_signal_i = 0;
        #20; // Hold reset for 20ns (2 clock cycles)

        // 2. Configure LUT RAM (using RST state auto-increment)
        // FSM remains in RST while configuring, lut_addr_reg auto-increments with lut_wen_i/lut_rden_i
        lut_wen_i = 1; // Enable LUT write
        lut_write_data_i = 29'd134742416; // Address 0x0
        #10; // Write data and auto-increment lut_addr_reg
        lut_write_data_i = 29'd202375208; // Address 0x1
        #10; // Write data and auto-increment lut_addr_reg
        lut_write_data_i = 29'd269222912; // Address 0x2
        #10; // Write data and auto-increment lut_addr_reg
        lut_write_data_i = 29'd402917328; // Address 0x3
        #10; // Write data and auto-increment lut_addr_reg
        lut_write_data_i = 29'd470025394; // Address 0x4
        #10; // Write data and auto-increment lut_addr_reg
        lut_wen_i = 0; // Disable LUT write
        #10;

        // 3. De-assert reset to start FSM sequence
        reset_i = 0;
        #10;
        $display("\n--- FSM Sequence Started ---");
        $display("Time\tState\tAddr\tDataLen\tRepeat\tEOF\tSOF\tBusy\tSeqDone\tExitSig");
        for (int i = 0; i < 200; i++) begin // Run for a fixed number of cycles to observe behavior
            $display("%-4d\t%h\t%h\t%h\t%h\t%b\t%b\t%b\t%b\t%b", 
                $time, current_state_o, u_fsm.lut_addr_reg, u_fsm.data_length_timer, u_fsm.active_repeat_count,
                current_eof_o, current_sof_o, busy_o, sequence_done_o, exit_signal_i);
            if ($time == 150) begin // Example: Assert exit_signal_i at 150ns (after some sequence iterations)
                exit_signal_i = 1;
                $display("\n*** ASSERTING exit_signal_i ***\n");
            end else if ($time == 160) begin
                exit_signal_i = 0;
                $display("\n*** DE-ASSERTING exit_signal_i ***\n");
            end
            #10; // Wait for next clock edge
        end

        $display("\n--- Simulation Finished ---");
        $finish;
    end

endmodule