`timescale 1ns / 1ps
module sequencer_fsm_tb;

    // FSM Inputs
    logic clk;
    logic reset_n;
    logic [7:0] command_id_i;
    logic task_done_i;
    logic adc_ready_i;
    logic sensor_stable_i;
    logic aed_detected_i;

    // FSM LUT RAM Access Inputs (for runtime updates, if needed in TB)
    logic lut_access_en_i;
    logic lut_read_write_mode_i;
    logic [28:0] lut_write_data_i;

    // FSM Outputs
    wire [2:0] current_state_o;
    wire busy_o;
    wire sequence_done_o;
    wire [7:0] current_repeat_count_o; // Assuming first field is repeat_count
    wire [15:0] current_data_length_o; // Assuming second field is data_length
    wire [0:0] current_eof_o; // Assuming third field is eof
    wire [0:0] current_sof_o; // Assuming fourth field is sof
    wire [28:0] lut_read_data_o;

    // Internal variables for state encoding to string for logging
    string state_names[] = {
        "IDLE",
        "RST",
        "PANEL_STABLE",
        "BACK_BIAS",
        "FLUSH",
        "EXPOSE_TIME",
        "READOUT",
        "AED_DETECT"
    };

    // File handle for dumping results
    integer outfile;

    // Instantiate the FSM module
    sequencer_fsm dut (
        .clk                    (clk),
        .reset_n                (reset_n),
        .command_id_i           (command_id_i),
        .task_done_i            (task_done_i),
        .adc_ready_i            (adc_ready_i),
        .sensor_stable_i        (sensor_stable_i),
        .aed_detected_i         (aed_detected_i),
        .lut_access_en_i        (lut_access_en_i),
        .lut_read_write_mode_i  (lut_read_write_mode_i),
        .lut_write_data_i       (lut_write_data_i),
        .current_state_o        (current_state_o),
        .busy_o                 (busy_o),
        .sequence_done_o        (sequence_done_o),
        .current_repeat_count_o (current_repeat_count_o),
        .current_data_length_o  (current_data_length_o),
        .current_eof_o          (current_eof_o),
        .current_sof_o          (current_sof_o),
        .lut_read_data_o        (lut_read_data_o)
    );

    // Initial LUT RAM Data Loading
    initial begin
        dut.lut_ram[0] = 29'd67375105;
        dut.lut_ram[1] = 29'd269746688;
        dut.lut_ram[2] = 29'd470024192;
        dut.lut_ram[3] = 29'd335806466;
        dut.lut_ram[4] = 29'd402923520;
        dut.lut_ram[255] = 29'd0;
    end

    // Clock generation
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk; // 10ns clock period
    end

    // Test sequence
    initial begin
        outfile = $fopen("sv_sim_results.csv", "w");
        if (outfile == 0) begin
            $error("Error: Could not open sv_sim_results.csv");
            $finish;
        end
        $fwrite(outfile, "clk_cycle,current_state_sv,busy_sv,sequence_done_sv,repeat_count_sv,data_length_sv,eof_sv,sof_sv\n");

        // Initial reset
        reset_n = 1'b0;
        command_id_i = 8'h00;
        task_done_i = 1'b0;
        adc_ready_i = 1'b0;
        sensor_stable_i = 1'b0;
        aed_detected_i = 1'b0;
        lut_access_en_i = 1'b0;
        lut_read_write_mode_i = 1'b0;
        lut_write_data_i = 29'h0;

        #10; // Apply reset for one clock cycle
        reset_n = 1'b1;

        // -----------------------------------------------------
        // Simulation Sequence - Inputs MUST MATCH Python Sim
        // -----------------------------------------------------
        // This section will be dynamically populated by Python during execution.
        // For now, it's a placeholder. Python will write actual inputs here.

        // Example (replace with generated inputs later):
        // @(posedge clk); command_id_i = 8'h00; task_done_i = 1'b0; // Cycle 0
        // @(posedge clk); command_id_i = 8'h00; task_done_i = 1'b1; // Cycle 1 (IDLE from RST)
        // @(posedge clk); command_id_i = 8'h03; task_done_i = 1'b0; // Cycle 2 (EXPOSE_TIME)
        // @(posedge clk); command_id_i = 8'h03; task_done_i = 1'b1; // Cycle 3 (IDLE from EXPOSE_TIME)

        // This is a dynamic section filled by Python before running SV sim.
                @(posedge clk); // Cycle 0
        command_id_i = 8'h1; task_done_i = 1'b0; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0; lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = 34'd0;
        @(posedge clk); // Cycle 1
        command_id_i = 8'h1; task_done_i = 1'b1; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0; lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = 34'd0;
        @(posedge clk); // Cycle 2
        command_id_i = 8'h0; task_done_i = 1'b0; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0; lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = 34'd0;
        @(posedge clk); // Cycle 3 (default inputs)
        command_id_i = 8'h00; task_done_i = 1'b0; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0;
        lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = 34'h0;
        @(posedge clk); // Cycle 4 (default inputs)
        command_id_i = 8'h00; task_done_i = 1'b0; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0;
        lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = 34'h0;

        $fclose(outfile);
        $display("SystemVerilog simulation complete. Results saved to sv_sim_results.csv");
        $finish; // End simulation
    end

endmodule