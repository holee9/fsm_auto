//-----------------------------------------------------------------------------
// Project      : FPGA Sequencer FSM
// File         : sequencer_fsm.sv
// Author       : [Your Name]
// Reviewer     : [Reviewer Name]
// Company      : [Your Company]
// Department   : [Your Department]
// Created      : [YYYY-MM-DD]
// Version      : 1.0
// Tool Version : [Tool/Simulator Version]
// Description  : 
//   - FPGA finite state machine for sequence control.
//   - Executes command sequences from LUT RAM.
//   - Supports repeat, timer, and exit signal handling.
//   - Used for panel, bias, flush, expose, readout, and AED control.
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

// Sequencer FSM Module
// - Controls sequence execution based on LUT RAM commands
// - Supports repeat, timer, and exit signal handling
// - LUT RAM read/write in RST state
// - State transitions based on command completion and internal timer
module sequencer_fsm (
    // Clock and Reset
    input  logic                   clk,
    input  logic                   reset_i,                    // Active high reset

    // LUT RAM Interface (RST state only)
    input  logic                   lut_wen_i,                  // LUT Write Enable
    input  logic [36:0]            lut_write_data_i,           // Data to write to LUT RAM
    input  logic                   lut_rden_i,                 // LUT Read Enable
    output logic [28:0]            lut_read_data_o,            // Data read from LUT RAM

    // Control Signals
    input  logic                   config_done_i,              // Configuration done signal
    input  logic                   exit_signal_i,              // Exit signal to stop sequence

    // FSM State and Status Outputs
    output logic [2:0]             current_state_o,            // Current FSM state
    output logic                   busy_o,                     // FSM busy indicator
    output logic                   sequence_done_o,            // Sequence completion flag

    // Command Enable Outputs
    output logic                   panel_enable_o,             // Panel stable state enable
    output logic                   bias_enable_o,              // Back bias state enable
    output logic                   flush_enable_o,             // Flush state enable
    output logic                   expose_enable_o,            // Expose time state enable
    output logic                   readout_enable_o,           // Readout state enable
    output logic                   aed_enable_o,               // AED detect state enable

    // Current Command Parameters
    output logic [7:0]             current_repeat_count_o,     // Current repeat count
    output logic [15:0]            current_data_length_o,      // Current data length
    output logic [0:0]             current_eof_o,              // Current EOF flag
    output logic [0:0]             current_sof_o               // Current SOF flag
);

    // LUT RAM Parameters
    localparam LUT_DEPTH = (2**8);
    localparam LUT_DATA_WIDTH = 37;
    (* ram_init_file = "init.mem" *) logic [LUT_DATA_WIDTH-1:0] internal_lut_ram [0:LUT_DEPTH-1];

    // FSM State Definitions
    localparam logic [2:0] RST = 3'd0;           // Reset state
    localparam logic [2:0] IDLE = 3'd1;          // Idle state
    localparam logic [2:0] PANEL_STABLE = 3'd2;  // Panel stable state
    localparam logic [2:0] BACK_BIAS = 3'd3;     // Back bias state
    localparam logic [2:0] FLUSH = 3'd4;         // Flush state
    localparam logic [2:0] AED_DETECT = 3'd5;    // AED detect state
    localparam logic [2:0] EXPOSE_TIME = 3'd6;   // Expose time state
    localparam logic [2:0] READOUT = 3'd7;       // Readout state

    // FSM Internal Registers
    logic [2:0]     current_state_reg;           // Current state register
    logic [7:0]     lut_addr_reg;                // LUT address register
    logic [7:0]     next_addr_reg;               // Next address register
    logic [7:0]     active_repeat_count;         // Active repeat counter
    logic [15:0]    data_length_reg;             // Data length register
    logic [15:0]    data_length_timer;           // Data length timer
    logic           sequence_done_reg;           // Sequence done register
    logic [0:0]     current_eof_reg;             // Current EOF register
    logic [0:0]     current_sof_reg;             // Current SOF register

    // LUT RAM Read Data Fields
    logic [2:0]     read_next_state;             // Next state from LUT
    logic [7:0]     read_repeat_count;           // Repeat count from LUT
    logic [15:0]    read_data_length;            // Data length from LUT
    logic [0:0]     read_eof;                    // EOF flag from LUT
    logic [0:0]     read_sof;                    // SOF flag from LUT
    logic [7:0]     read_next_address;           // Next address from LUT
    logic [36:0]    lut_read_data_int;           // Internal LUT read data

    // LUT RAM Field Assignments
    assign read_next_state    = lut_read_data_int[2:0];
    assign read_repeat_count  = lut_read_data_int[10:3];
    assign read_data_length   = lut_read_data_int[26:11];
    assign read_eof          = lut_read_data_int[27];
    assign read_sof          = lut_read_data_int[28];
    assign read_next_address  = lut_read_data_int[36:29];

    // Output Assignments
    assign current_state_o = current_state_reg;
    assign busy_o = (current_state_reg != RST && current_state_reg != IDLE);
    assign sequence_done_o = sequence_done_reg;
    assign current_repeat_count_o = active_repeat_count;
    assign current_data_length_o = data_length_timer;
    assign current_eof_o = current_eof_reg;
    assign current_sof_o = current_sof_reg;

    // State Enable Outputs
    assign panel_enable_o   = (current_state_reg == PANEL_STABLE);
    assign bias_enable_o    = (current_state_reg == BACK_BIAS);
    assign flush_enable_o   = (current_state_reg == FLUSH);
    assign expose_enable_o  = (current_state_reg == EXPOSE_TIME);
    assign readout_enable_o = (current_state_reg == READOUT);
    assign aed_enable_o     = (current_state_reg == AED_DETECT);

    // Main FSM State Machine
    always_ff @(posedge clk or posedge reset_i) begin
        if (reset_i) begin
            // Reset all registers
            current_state_reg     <= RST;
            next_addr_reg         <= 8'd0;
            lut_addr_reg          <= 8'd0;
            active_repeat_count   <= 8'd0;
            data_length_reg       <= 16'd0;
            data_length_timer     <= 16'd0;
            sequence_done_reg     <= 1'b0;
            current_eof_reg       <= 1'b0;
            current_sof_reg       <= 1'b0;
            lut_read_data_o       <= 29'd0;
        end else begin
            // Decrement data length timer in command states
            if ((current_state_reg != RST && current_state_reg != IDLE) && 
                data_length_timer > 0) begin
                data_length_timer <= data_length_timer - 1;
            end

            // FSM State Transitions
            case (current_state_reg)
                RST: begin
                    // Stay in RST until config_done_i is asserted
                    if (!config_done_i) begin
                        current_state_reg <= RST;
                    end else if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                // Command States: Handle repeat and timer
                PANEL_STABLE, BACK_BIAS, FLUSH, AED_DETECT, EXPOSE_TIME, READOUT: begin
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            // Repeat current command
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            // Command complete, go to IDLE
                            current_state_reg <= IDLE;
                        end
                    end
                end

                IDLE: begin
                    // Stay in IDLE, update address for next command
                    current_state_reg <= current_state_reg;
                    lut_addr_reg <= next_addr_reg;
                end

                default: begin
                    // Invalid state, go to IDLE
                    current_state_reg <= IDLE;
                end
            endcase
        end
    end

    // IDLE State Combinational Logic
    always_comb begin : idle_state_logic
        if (current_state_reg == IDLE) begin
            if (current_eof_reg) begin
                // Handle EOF command
                lut_addr_reg = next_addr_reg;
                current_state_reg = read_next_state;
                active_repeat_count = read_repeat_count;
                data_length_reg = read_data_length;
                data_length_timer = read_data_length;
                current_eof_reg = read_eof;
                current_sof_reg = read_sof;

                if (exit_signal_i) begin
                    // Exit signal active: increment address and assert sequence_done
                    next_addr_reg = next_addr_reg + 1'b1;
                    sequence_done_reg = 1'b1;
                end else begin
                    // Normal operation: use next_address from LUT
                    next_addr_reg = read_next_address;
                    sequence_done_reg = 1'b0;
                end
            end else begin
                // Normal command transition
                lut_addr_reg = next_addr_reg;
                current_state_reg = read_next_state;
                active_repeat_count = read_repeat_count;
                data_length_reg = read_data_length;
                data_length_timer = read_data_length;
                current_eof_reg = read_eof;
                current_sof_reg = read_sof;
                next_addr_reg = read_next_address;
            end
        end
    end

    // LUT RAM Read Data Assignment
    assign lut_read_data_int = internal_lut_ram[lut_addr_reg];

    // LUT RAM Write/Read Control (RST state only)
    always_ff @(posedge clk or posedge reset_i) begin
        if (reset_i) begin
            lut_addr_reg <= 8'd0;
        end else begin
            if (current_state_reg == RST) begin
                if (!config_done_i) begin
                    if (lut_wen_i) begin
                        // Write to LUT RAM
                        internal_lut_ram[lut_addr_reg] <= lut_write_data_i;
                        lut_addr_reg <= lut_addr_reg + 1'b1;
                    end else if (lut_rden_i) begin
                        // Read from LUT RAM
                        lut_read_data_o <= internal_lut_ram[lut_addr_reg];
                        lut_addr_reg <= lut_addr_reg + 1'b1;
                    end
                end else begin
                    // Reset address after configuration
                    lut_addr_reg <= 8'd0;
                end
            end
        end
    end

    // Initialize LUT RAM to zero
    initial begin
        integer i;
        for (i = 0; i < LUT_DEPTH; i = i + 1) begin
            internal_lut_ram[i] = '0;
        end
    end

endmodule