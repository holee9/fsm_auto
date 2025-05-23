`timescale 1ns / 1ps

module sequencer_fsm (
    input  logic                   clk,
    input  logic                   reset_i,
    input  logic                   lut_wen_i, // LUT Write Enable (active high, only in RST state)
    input  logic [28:0]            lut_write_data_i, // Data to write to LUT RAM
    input  logic                   lut_rden_i, // LUT Read Enable (active high, only in RST state)
    output logic [28:0]            lut_read_data_o, // Data read from LUT RAM (FSM outputs its requested address's data)
    output logic [2:0]             current_state_o,
    output logic                   busy_o,
    output logic                   sequence_done_o,
    output logic                   panel_enable_o,
    output logic                   bias_enable_o,
    output logic                   flush_enable_o,
    output logic                   expose_enable_o,
    output logic                   readout_enable_o,
    output logic                   aed_enable_o,
    output logic [7:0]             current_repeat_count_o,
    output logic [15:0]            current_data_length_o,
    output logic [0:0]             current_eof_o,
    output logic [0:0]             current_sof_o
);

    // Internal LUT RAM for simulation and to drive 'lut_read_data_o'
    localparam LUT_DEPTH = (2**8);
    localparam LUT_DATA_WIDTH = 29;
    (* ram_init_file = "init.mem" *) logic [LUT_DATA_WIDTH-1:0] internal_lut_ram [0:LUT_DEPTH-1];

    // FSM State Parameters
    localparam logic [2:0] RST = 3'd0; // 
    localparam logic [2:0] IDLE = 3'd1; // 
    localparam logic [2:0] PANEL_STABLE = 3'd2; // 
    localparam logic [2:0] BACK_BIAS = 3'd3; // 
    localparam logic [2:0] FLUSH = 3'd4; // 
    localparam logic [2:0] AED_DETECT = 3'd5; // 
    localparam logic [2:0] EXPOSE_TIME = 3'd6; // 
    localparam logic [2:0] READOUT = 3'd7; // 

    // FSM Internal Registers
    logic [2:0]  current_state_reg;
    logic [7:0] lut_addr_reg;
    logic [7:0] active_repeat_count;
    logic [15:0] data_length_timer;
    logic                       sequence_done_reg;
    logic [0:0]     current_eof_reg;
    logic [0:0]     current_sof_reg;

    // Internal signals derived from lut_read_data_o (parameters of the NEXT command)
    // WARNING: This assumes 'lut_read_data_o' is effectively acting as an input from the external LUT RAM.
    // In a typical design, this would be an input port (e.g., 'lut_read_data_i').
    logic [2:0]  read_next_state;
    logic [7:0] read_repeat_count;
    logic [15:0] read_data_length;
    logic [0:0]     read_eof;
    logic [0:0]     read_sof;
    logic [28:0] lut_read_data_int;

    assign read_next_state  = lut_read_data_int[2:0];
    assign read_repeat_count = lut_read_data_int[10:3];
    assign read_data_length = lut_read_data_int[26:11];
    assign read_eof         = lut_read_data_int[27:27];
    assign read_sof         = lut_read_data_int[28:28];

    // Output Assignments
    assign current_state_o = current_state_reg;
    assign busy_o = (current_state_reg != RST && current_state_reg != IDLE);
    assign sequence_done_o = sequence_done_reg;
    assign current_repeat_count_o = active_repeat_count;
    assign current_data_length_o = data_length_timer;
    assign current_eof_o = current_eof_reg;
    assign current_sof_o = current_sof_reg;

    assign panel_enable_o   = (current_state_reg == PANEL_STABLE);
    assign bias_enable_o    = (current_state_reg == BACK_BIAS);
    assign flush_enable_o   = (current_state_reg == FLUSH);
    assign expose_enable_o  = (current_state_reg == EXPOSE_TIME);
    assign readout_enable_o = (current_state_reg == READOUT);
    assign aed_enable_o     = (current_state_reg == AED_DETECT);

    always_ff @(posedge clk or posedge reset_i) begin
        if (reset_i) begin // Active high reset
            current_state_reg     <= RST;
            lut_addr_reg          <= 8'd0;
            active_repeat_count   <= 8'd0;
            data_length_timer     <= 16'd0;
            sequence_done_reg     <= 1'b0;
            current_eof_reg       <= 1'b0;
            current_sof_reg       <= 1'b0;
            lut_read_data_o       <= 29'd0; // Reset output data
        end else begin
            sequence_done_reg <= 1'b0; // Default de-assert sequence done
            current_sof_reg   <= 1'b0; // Default de-assert current SOF after one cycle
            
            // data_length_timer logic (decrements only in command states, not IDLE/RST)
            if ((current_state_reg != RST && current_state_reg != IDLE) && data_length_timer > 0) begin
                data_length_timer <= data_length_timer - 1;
            end

            case (current_state_reg)
                RST : begin

                    // if (lut_wen_i || lut_rden_i) begin
                    //     lut_addr_reg <= lut_addr_reg + 1'b1; // Auto-increment address for config
                    // end

                    // Transition out of RST immediately after reset de-assertion to the first command
                    // Parameters for address 0x00 should be available on lut_read_data_o at this point.
                    current_state_reg   <= read_next_state; // Transition to first command state based on lut_read_data_o (for addr 0x00)
                    active_repeat_count <= read_repeat_count;
                    data_length_timer   <= read_data_length;
                    current_eof_reg     <= read_eof;
                    current_sof_reg     <= read_sof; // Assert SOF for the very first command (from LUT 0x00)
                    // lut_addr_reg        <= 8'd1; // Prepare for next address (0x01) for the second command
                    lut_addr_reg        <= 8'd0; // Prepare for next address (0x01) for the second command
                    
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                PANEL_STABLE : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                BACK_BIAS : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                FLUSH : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                AED_DETECT : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                EXPOSE_TIME : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                READOUT : begin // 
                    // Stays in this state until 'data_length_timer' is 0.
                    // WARNING: This FSM transitions solely based on 'data_length_timer'.
                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.
                    if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                IDLE : begin // Transition state after a command completion
                    // In IDLE, the FSM prepares for the next command by loading parameters from 'lut_read_data_o',
                    // which is assumed to reflect the data at 'lut_addr_reg' (driven by external LUT RAM).
                    if (current_eof_reg) begin // Current command (just completed) was the end of the sequence
                        sequence_done_reg <= 1'b1; // Signal sequence completion for one cycle
                        
                        // Repeat logic based on active_repeat_count.
                        // No 'exit_signal_i' input as per fixed port list.
                        if (active_repeat_count > 0 && active_repeat_count != 8'd1) begin
                            active_repeat_count <= active_repeat_count - 1; // Decrement repeat count
                            lut_addr_reg        <= 8'd0; // Loop back to start (address 0x00)
                            current_state_reg   <= read_next_state; // Go to next state from LUT 0
                            data_length_timer   <= read_data_length;
                            current_eof_reg     <= read_eof;
                            current_sof_reg     <= read_sof;
                        end else begin // No more repeats (active_repeat_count is 1 or 0 and not infinite loop case)
                            // Transition to the first command at address 0x00 and reset repeat count
                            lut_addr_reg        <= 8'd0;
                            current_state_reg   <= read_next_state; // Go to next state from LUT 0
                            active_repeat_count <= read_repeat_count; // Reset repeat count for the new sequence
                            data_length_timer   <= read_data_length;
                            current_eof_reg     <= read_eof;
                            current_sof_reg     <= read_sof;
                        end
                    end else begin // Current command was NOT the end of the sequence
                        lut_addr_reg        <= lut_addr_reg + 1'b1; // Increment logical address
                        current_state_reg   <= read_next_state; // Go to next state from the incremented LUT address
                        active_repeat_count <= read_repeat_count; // Load repeat count for the new command
                        data_length_timer   <= read_data_length;
                        current_eof_reg     <= read_eof;
                        current_sof_reg     <= read_sof;
                    end
                end

                default : begin // Should not happen in a well-defined FSM
                    current_state_reg <= IDLE;
                end
            endcase
        end
    end

    // Combinatorial assignment for lut_read_data_o (FSM's output representing data from current lut_addr_reg)
    assign lut_read_data_int = internal_lut_ram[lut_addr_reg];
    
    // Logic to write to internal LUT RAM (controlled by lut_wen_i)
    always_ff @(posedge clk) begin
        if (current_state_reg == RST && lut_wen_i) begin
            internal_lut_ram[lut_addr_reg] <= lut_write_data_i;
        end else if (current_state_reg == RST && lut_rden_i) begin
            lut_read_data_o <= internal_lut_ram[lut_addr_reg];
        end

        if (current_state_reg == RST) begin
            if (lut_wen_i || lut_rden_i) begin
                lut_addr_reg <= lut_addr_reg + 1'b1; // Auto-increment address for config
            end
        end
    end

    // LUT RAM initialization (for simulation purposes)
    initial begin
        integer i;
        for (i = 0; i < LUT_DEPTH; i = i + 1) begin
            internal_lut_ram[i] = '0;
        end
    end

endmodule