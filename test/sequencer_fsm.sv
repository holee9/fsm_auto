`timescale 1ns / 1ps

module sequencer_fsm (
    input logic clk,
    input logic reset_i,
    input logic exit_signal_i;,
    input logic lut_wen_i; // LUT Write Enable (active high, only in RST state),
    input logic [28:0] lut_write_data_i; // Data to write to LUT RAM,
    input logic lut_rden_i; // LUT Read Enable (active high, only in RST state),
    output logic [28:0] lut_read_data_o; // Data read from LUT RAM,
    output logic [2:0] current_state_o,
    output logic busy_o,
    output logic sequence_done_o,
    output logic panel_enable_o,
    output logic bias_enable_o,
    output logic flush_enable_o,
    output logic expose_enable_o,
    output logic readout_enable_o,
    output logic aed_enable_o,
    output logic [7:0] current_repeat_count_o,
    output logic [15:0] current_data_length_o,
    output logic current_eof_o,
    output logic current_sof_o
);

    localparam RST = 3'd0;
    localparam IDLE = 3'd1;
    localparam PANEL_STABLE = 3'd2;
    localparam BACK_BIAS = 3'd3;
    localparam FLUSH = 3'd4;
    localparam AED_DETECT = 3'd5;
    localparam EXPOSE_TIME = 3'd6;
    localparam READOUT = 3'd7;

    logic [2:0] current_state_reg;

    // LUT Address Register. This points to the current LUT entry being processed.
    logic [7:0] lut_addr_reg; 
    logic [8:0] data_length_timer; // Timer for data_length parameter
    logic [1:0] active_repeat_count; // Counter for repeat_count parameter
    // Simulated internal task completion signals - These are for simulation purposes only, not external inputs.
    logic internal_task_done;
    logic internal_adc_ready;
    logic internal_sensor_stable;
    logic internal_aed_detected;

    logic [7:0] current_repeat_count;
    logic [15:0] current_data_length;
    logic [0:0] current_eof;
    logic [0:0] current_sof;

    // LUT RAM Declaration
    logic [28:0] lut_ram [0:255];

    // LUT data for current address (combinatorial read for FSM internal use)
    logic [28:0] lut_read_current_addr_internal;
    assign lut_read_current_addr_internal = lut_ram[lut_addr_reg]; 

    logic [2:0] next_state_from_lut;
    assign next_state_from_lut = lut_read_current_addr_internal[28:26];

    // FSM State Register and LUT Address Management
    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset
        if (reset_i) begin // Reset asserted (active high)
            current_state_reg <= RST; // Go to RST state on reset assertion
            lut_addr_reg <= 8'h00; // Initialize LUT address for RAM config
            data_length_timer <= '0;
            active_repeat_count <= '0;
        end else begin
            case (current_state_reg)
                RST: begin
                    // Reset de-asserted: transition to the first sequence state (from LUT[0x00])
                    current_state_reg <= lut_ram[8'h00][28:26]; 
                    lut_addr_reg <= 8'h00; // Reset address for sequence execution
                    data_length_timer <= lut_ram[8'h00][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for the first command
                    active_repeat_count <= lut_ram[8'h00][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for the first command
                end
                IDLE: begin
                    // In IDLE, process repeat and EOF logic, then determine next state and address
                    if (active_repeat_count > 0) begin // If current command needs to be repeated
                        active_repeat_count <= active_repeat_count - 1; // Decrement repeat counter
                        // Stay at the same lut_addr_reg to re-execute the command
                        current_state_reg <= next_state_from_lut; // Go back to the command state
                        data_length_timer <= current_data_length; // Re-initialize data_length_timer
                    end else if (current_repeat_count == 0 && exit_signal_i) begin // Infinite repeat and exit signal is asserted
                        lut_addr_reg <= lut_addr_reg + 1; // Move to the next command
                        current_state_reg <= lut_ram[lut_addr_reg + 1][28:26]; // Transition to the next state
                        data_length_timer <= lut_ram[lut_addr_reg + 1][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for the next command
                        active_repeat_count <= lut_ram[lut_addr_reg + 1][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for the next command
                    end else if (current_eof) begin // End of sequence, loop back to 0x00
                        lut_addr_reg <= 8'h00; // Loop back to start of sequence
                        current_state_reg <= lut_ram[8'h00][28:26]; // Go to state from LUT[0x00]
                        data_length_timer <= lut_ram[8'h00][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for first command
                        active_repeat_count <= lut_ram[8'h00][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for first command
                    end else begin // Proceed to the next command in sequence
                        lut_addr_reg <= lut_addr_reg + 1; // Increment for the next command
                        current_state_reg <= lut_ram[lut_addr_reg + 1][28:26]; // Go to next state from LUT for (current lut_addr_reg + 1)
                        data_length_timer <= lut_ram[lut_addr_reg + 1][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for next command
                        active_repeat_count <= lut_ram[lut_addr_reg + 1][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for next command
                    end
                end
                PANEL_STABLE: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= PANEL_STABLE; // Stay in current state
                    end else if (internal_sensor_stable) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= PANEL_STABLE; // Stay in current state
                    end
                end
                BACK_BIAS: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= BACK_BIAS; // Stay in current state
                    end else if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= BACK_BIAS; // Stay in current state
                    end
                end
                FLUSH: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= FLUSH; // Stay in current state
                    end else if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= FLUSH; // Stay in current state
                    end
                end
                AED_DETECT: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= AED_DETECT; // Stay in current state
                    end else if (internal_aed_detected) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= AED_DETECT; // Stay in current state
                    end
                end
                EXPOSE_TIME: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= EXPOSE_TIME; // Stay in current state
                    end else if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= EXPOSE_TIME; // Stay in current state
                    end
                end
                READOUT: begin
                    if (data_length_timer > 0) begin
                        data_length_timer <= data_length_timer - 1; // Decrement timer
                        current_state_reg <= READOUT; // Stay in current state
                    end else if ((internal_task_done && internal_adc_ready)) begin
                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE
                        // lut_addr_reg and counters will be updated in IDLE
                    end else begin
                        current_state_reg <= READOUT; // Stay in current state
                    end
                end
                default: begin
                    current_state_reg <= RST; // Fallback to RST on unexpected state
                    lut_addr_reg <= 8'h00;
                    data_length_timer <= '0;
                    active_repeat_count <= '0;
                end
            endcase
        end
    end

    // lut_addr_reg auto-increment in RST state for LUT RAM configuration
    always_ff @(posedge clk) begin
        if (current_state_reg == RST && (lut_wen_i || lut_rden_i)) begin
            lut_addr_reg <= lut_addr_reg + 1;
        end
    end

    // FSM Parameter Assignments (from LUT RAM data - combinatorial, based on lut_addr_reg)
    always_comb begin
        current_sof = lut_read_current_addr_internal[0:0];
        current_eof = lut_read_current_addr_internal[1:1];
        current_data_length = lut_read_current_addr_internal[17:2];
        current_repeat_count = lut_read_current_addr_internal[25:18];
    end

    // These are LSB positions and widths for data_length and repeat_count within LUT entry. Generated for internal use.
    localparam DATA_LENGTH_LSB = 2;
    localparam DATA_LENGTH_WIDTH = 16;
    localparam REPEAT_COUNT_LSB = 18;
    localparam REPEAT_COUNT_WIDTH = 8;

    // Internal Signal Generation Logic (Simulated for verification)
    // Note: 'task_timer' here simulates how long a task takes, independent of data_length_timer.
    // The actual FSM transition depends on 'data_length_timer == 0' AND the corresponding internal_task_done signal.
    logic [7:0] task_timer;
    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset
        if (reset_i) begin // Reset asserted
            task_timer <= '0;
            internal_task_done <= 1'b0;
            internal_adc_ready <= 1'b0;
            internal_sensor_stable <= 1'b0;
            internal_aed_detected <= 1'b0;
        end else begin
            // Reset signals before new evaluation each cycle
            internal_task_done <= 1'b0;
            internal_adc_ready <= 1'b0;
            internal_sensor_stable <= 1'b0;
            internal_aed_detected <= 1'b0;
            case (current_state_reg)
                RST, IDLE: begin
                    task_timer <= '0; // Reset timer when in RST or IDLE
                end
                BACK_BIAS, FLUSH, EXPOSE_TIME: begin
                    if (task_timer >= 8'd20) begin
                        internal_task_done <= 1'b1;
                        task_timer <= '0;
                    end else begin
                        task_timer <= task_timer + 1;
                    end
                end
                PANEL_STABLE: begin
                    if (task_timer >= 8'd15) begin
                        internal_sensor_stable <= 1'b1;
                        task_timer <= '0;
                    end else begin
                        task_timer <= task_timer + 1;
                    end
                end
                READOUT: begin
                    if (task_timer >= 8'd50) begin
                        internal_task_done <= 1'b1;
                        internal_adc_ready <= 1'b1;
                        task_timer <= '0;
                    end else if (task_timer >= 8'd40) begin
                        internal_adc_ready <= 1'b1;
                        task_timer <= task_timer + 1;
                    end else begin
                        internal_adc_ready <= 1'b0;
                        task_timer <= task_timer + 1;
                    end
                end
                AED_DETECT: begin
                    if (task_timer >= 8'd10) begin
                        internal_aed_detected <= 1'b1;
                        task_timer <= '0;
                    end else begin
                        task_timer <= task_timer + 1;
                    end
                end
                default: task_timer <= '0;
            endcase
        end
    end

    // FSM Outputs Assignments
    assign current_state_o = current_state_reg;
    // Busy if not in RST or IDLE. In this model, IDLE is a transient state between commands, so FSM is always 'busy' once sequence starts.
    assign busy_o = (current_state_reg != RST); 
    // sequence_done_o is asserted when in IDLE, the command just completed was EOF, AND the command is not repeating.
    // It will be asserted for one cycle before looping back to the first command.
    assign sequence_done_o = (current_state_reg == IDLE && current_eof == 1'b1 && active_repeat_count == 0 && current_repeat_count == 0);
    assign panel_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign bias_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign flush_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign expose_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign readout_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign aed_enable_o = (
        current_state_reg == PANEL_STABLE
        || current_state_reg == BACK_BIAS
        || current_state_reg == FLUSH
        || current_state_reg == AED_DETECT
        || current_state_reg == EXPOSE_TIME
        || current_state_reg == READOUT
    ) ? 1'b1 : 1'b0;
    assign current_repeat_count_o = current_repeat_count;
    assign current_data_length_o = current_data_length;
    assign current_eof_o = current_eof;
    assign current_sof_o = current_sof;

    // LUT RAM Read/Write Control (Only possible when FSM is in RST state, using auto-incrementing lut_addr_reg)
    assign lut_read_data_o = lut_ram[lut_addr_reg]; // External read output always reflects lut_addr_reg

    always_ff @(posedge clk) begin
        if (current_state_reg == RST && lut_wen_i) begin // Only allow write when in RST state and write enable is high
            lut_ram[lut_addr_reg] <= lut_write_data_i; 
        end
    end

endmodule