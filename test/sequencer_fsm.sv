`timescale 1ns / 1ps

module sequencer_fsm (
    input logic clk,
    input logic reset_i,
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
    // Simulated internal task completion signals
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
        end else begin
            case (current_state_reg)
                RST: begin
                    // Reset de-asserted: transition to the first sequence state (from LUT[0x00])
                    current_state_reg <= lut_ram[8'h00][28:26]; 
                    lut_addr_reg <= 8'h00; // Reset address for sequence execution
                end
                IDLE: begin
                    // In IDLE, increment lut_addr_reg and determine next state
                    if (current_eof) begin // If the *current* command (that just completed) was EOF
                        lut_addr_reg <= 8'h00; // Loop back to start of sequence
                        current_state_reg <= lut_ram[8'h00][28:26]; // Go to state from LUT[0x00]
                    end else begin
                        lut_addr_reg <= lut_addr_reg + 1; // Increment for the next command
                        // In the next cycle, lut_addr_reg will be updated, so current_state_reg will then read lut_ram[new_lut_addr_reg]
                        current_state_reg <= lut_ram[lut_addr_reg + 1][28:26]; // Go to next state from LUT for (current lut_addr_reg + 1)
                    end
                end
                PANEL_STABLE: begin
                    if (internal_sensor_stable) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= PANEL_STABLE; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                BACK_BIAS: begin
                    if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= BACK_BIAS; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                FLUSH: begin
                    if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= FLUSH; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                AED_DETECT: begin
                    if (internal_aed_detected) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= AED_DETECT; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                EXPOSE_TIME: begin
                    if (internal_task_done) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= EXPOSE_TIME; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                READOUT: begin
                    if ((internal_task_done && internal_adc_ready)) begin
                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition
                    end else begin
                        current_state_reg <= READOUT; // Stay in current state
                    end
                    lut_addr_reg <= lut_addr_reg; 
                end
                default: begin
                    current_state_reg <= RST; // Fallback to RST on unexpected state
                    lut_addr_reg <= 8'h00;
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

    // Internal Signal Generation Logic (Simulated for verification)
    logic [7:0] task_timer;
    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset
        if (reset_i) begin // Reset asserted
            task_timer <= '0;
            internal_task_done <= 1'b0;
            internal_adc_ready <= 1'b0;
            internal_sensor_stable <= 1'b0;
            internal_aed_detected <= 1'b0;
        end else begin
            internal_task_done <= 1'b0;
            internal_adc_ready <= 1'b0;
            internal_sensor_stable <= 1'b0;
            internal_aed_detected <= 1'b0;
            case (current_state_reg)
                RST, BACK_BIAS, FLUSH, EXPOSE_TIME: begin
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
                    else if (task_timer >= 8'd40) begin
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
    // sequence_done_o is asserted when in IDLE and the command just completed was EOF (current_eof == 1'b1).
    // It will be asserted for one cycle before looping back to the first command.
    assign sequence_done_o = (current_state_reg == IDLE && current_eof == 1'b1);
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