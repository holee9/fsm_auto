`timescale 1ns / 1ps

module sequencer_fsm (
    // input ports
    input  logic                   clk,
    input  logic                   reset_i,
    input  logic                   lut_wen_i, // LUT Write Enable (active high, only in RST state)
    input  logic [36:0]            lut_write_data_i, // Data to write to LUT RAM
    input  logic                   lut_rden_i, // LUT Read Enable (active high, only in RST state)
    input  logic                   config_done_i,    // Add configuration done input signal
    input  logic                   exit_signal_i, // Exit signal to stop the FSM
    // output ports
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
    localparam LUT_DATA_WIDTH = 37;
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
    logic [2:0]     current_state_reg;
    logic [7:0]     lut_addr_reg;
    logic [7:0]     next_addr_reg;
    logic [7:0]     active_repeat_count;
    logic [15:0]    data_length_reg;
    logic [15:0]    data_length_timer;
    logic           sequence_done_reg;
    logic [0:0]     current_eof_reg;
    logic [0:0]     current_sof_reg;

    logic [2:0]     read_next_state;
    logic [7:0]     read_repeat_count;
    logic [15:0]    read_data_length;
    logic [0:0]     read_eof;
    logic [0:0]     read_sof;
    logic [7:0]     read_next_address;
    logic [36:0]    lut_read_data_int;

    assign read_next_state  = lut_read_data_int[2:0];
    assign read_repeat_count = lut_read_data_int[10:3];
    assign read_data_length = lut_read_data_int[26:11];
    assign read_eof         = lut_read_data_int[27];
    assign read_sof         = lut_read_data_int[28];
    assign read_next_address = lut_read_data_int[36:29];

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
            next_addr_reg         <= 8'd0;
            lut_addr_reg          <= 8'd0;
            active_repeat_count   <= 8'd0;
            data_length_reg       <= 16'd0;
            data_length_timer     <= 16'd0;
            sequence_done_reg     <= 1'b0;
            current_eof_reg       <= 1'b0;
            current_sof_reg       <= 1'b0;
            lut_read_data_o       <= 29'd0; // Reset output data
        end else begin
            // sequence_done_reg <= 1'b0; // Default de-assert sequence done
            // current_sof_reg   <= 1'b0; // Default de-assert current SOF after one cycle
            
            // data_length_timer logic (decrements only in command states, not IDLE/RST)
            if ((current_state_reg != RST && current_state_reg != IDLE) && data_length_timer > 0) begin
                data_length_timer <= data_length_timer - 1;
            end

            case (current_state_reg)
                RST : begin
                    if (!config_done_i) begin
                        current_state_reg <= RST;
                    end else if (data_length_timer == 0) begin
                        current_state_reg <= IDLE;
                    end
                end

                PANEL_STABLE : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                PANEL_STABLE : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                BACK_BIAS : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                FLUSH : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                AED_DETECT : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                EXPOSE_TIME : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                READOUT : begin // 
                    if (data_length_timer == 0) begin
                        if (active_repeat_count > 0) begin
                            active_repeat_count <= active_repeat_count - 1;
                            current_state_reg   <= current_state_reg;
                            data_length_timer   <= data_length_reg;
                        end else begin
                            current_state_reg <= IDLE;
                        end
                    end
                end

                IDLE : begin 
                    current_state_reg <= current_state_reg;
                    lut_addr_reg <= next_addr_reg;

                //     if (current_eof_reg) begin // Current command (just completed) was the end of the sequence
                //         // sequence_done_reg <= 1'b1; // Signal sequence completion for one cycle
                //         lut_addr_reg        <= next_addr_reg;
                //         current_state_reg   <= read_next_state; // Go to next state from the incremented LUT address
                //         active_repeat_count <= read_repeat_count; // Load repeat count for the new command
                //         data_length_reg     <= read_data_length;
                //         data_length_timer   <= read_data_length;
                //         current_eof_reg     <= read_eof;
                //         current_sof_reg     <= read_sof;
                //         if (exit_signal_i) begin
                //             next_addr_reg <= next_addr_reg + 1'b1;
                //             sequence_done_reg <= 1'b1; // Signal sequence completion for one cycle
                //         end else begin
                //             next_addr_reg <= read_next_address;
                //         end
                //      end else begin // Current command was NOT the end of the sequence
                //         lut_addr_reg        <= next_addr_reg;
                //         current_state_reg   <= read_next_state; // Go to next state from the incremented LUT address
                //         active_repeat_count <= read_repeat_count; // Load repeat count for the new command
                //         data_length_reg     <= read_data_length;
                //         data_length_timer   <= read_data_length;
                //         current_eof_reg     <= read_eof;
                //         current_sof_reg     <= read_sof;
                //         next_addr_reg       <= read_next_address;
                //     end
                 end

                default : begin // Should not happen in a well-defined FSM
                    current_state_reg <= IDLE;
                end
            endcase
        end
    end


    always_comb begin : idel_state
        if (current_state_reg == IDLE) begin    
            if (current_eof_reg) begin
                lut_addr_reg        = next_addr_reg;
                current_state_reg   = read_next_state; 
                active_repeat_count = read_repeat_count; 
                data_length_reg     = read_data_length;
                data_length_timer   = read_data_length;
                current_eof_reg     = read_eof;
                current_sof_reg     = read_sof;
                if (exit_signal_i) begin
                    next_addr_reg = next_addr_reg + 1'b1;
                    sequence_done_reg = 1'b1;
                end else begin
                    next_addr_reg = read_next_address;
                    sequence_done_reg = 1'b0;
                end
            end else begin
                lut_addr_reg        = next_addr_reg;
                current_state_reg   = read_next_state;
                active_repeat_count = read_repeat_count;
                data_length_reg     = read_data_length;
                data_length_timer   = read_data_length;
                current_eof_reg     = read_eof;
                current_sof_reg     = read_sof;
                next_addr_reg       = read_next_address;
            end
        end
    end

    assign lut_read_data_int = internal_lut_ram[lut_addr_reg];
    
    always_ff @(posedge clk or posedge reset_i) begin
        if (reset_i) begin
            lut_addr_reg <= 8'd0;
        end else begin
            if (current_state_reg == RST) begin
                if (!config_done_i) begin
                    if (lut_wen_i) begin
                        internal_lut_ram[lut_addr_reg] <= lut_write_data_i;
                        lut_addr_reg <= lut_addr_reg + 1'b1;
                    end else if (lut_rden_i) begin
                        lut_read_data_o <= internal_lut_ram[lut_addr_reg];
                        lut_addr_reg <= lut_addr_reg + 1'b1;
                    end
                end else begin
                    lut_addr_reg <= 8'd0;
                end
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