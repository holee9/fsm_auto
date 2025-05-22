module sequencer_fsm (
    input logic clk,
    input logic reset_n,
    input logic 7 downto 0 command_id_i,
    input logic task_done_i,
    input logic adc_ready_i,
    input logic sensor_stable_i,
    input logic aed_detected_i,
    output logic 2 downto 0 current_state_o,
    output logic busy_o,
    output logic sequence_done_o,
    output logic 7 downto 0 current_repeat_count_o,
    output logic 15 downto 0 current_data_length_o,
    output logic current_eof_o,
    output logic current_sof_o,
    input  logic                               lut_access_en_i,    // LUT RAM Access Enable (1 pulse per read/write cycle),
    input  logic                               lut_read_write_mode_i, // 0: Read, 1: Write,
    input  logic [29-1:0]        lut_write_data_i,   // Data to write to LUT RAM,
    output logic [29-1:0]        lut_read_data_o     // Data read from LUT RAM
);

    // --- State Encoding Parameters ---
    localparam IDLE = 3'b000;
    localparam RST = 3'b001;
    localparam BACK_BIAS = 3'b010;
    localparam FLUSH = 3'b011;
    localparam EXPOSE_TIME = 3'b100;
    localparam READOUT = 3'b101;
    localparam AED_DETECT = 3'b110;
    localparam PANEL_STABLE = 3'b111;


    // --- FSM State Registers ---
    logic [2:0] current_state;
    logic [2:0] next_state;

    // --- Parameter Registers (updated from LUT RAM) ---
    logic [25:0] current_param_combined_reg; // Holds combined parameter value
    logic [7:0] param_repeat_count_reg;
    logic [15:0] param_data_length_reg;
    logic [0:0] param_eof_reg;
    logic [0:0] param_sof_reg;


    // --- FSM LUT RAM (Behavioral Model - will be synthesized to BRAM/LUT-RAM) ---
    // Each entry stores: {next_state_encoding, combined_param_value}
    localparam int LUT_RAM_DEPTH = 256;
    logic [28:0] lut_ram [LUT_RAM_DEPTH-1:0];

    // --- LUT RAM Address and Control Registers ---
    logic [8-1:0] lut_current_addr_reg; // Current address for LUT RAM R/W
    logic                               lut_internal_active;  // True when LUT RAM access is permitted/active

    // LUT RAM access is only enabled when FSM is in RST state AND external access_en is high
    assign lut_internal_active = (current_state == RST) && lut_access_en_i;

    // LUT RAM Read Data Output: always reading from lut_current_addr_reg when internal_active, else '0
    assign lut_read_data_o = lut_internal_active && !lut_read_write_mode_i ? lut_ram[lut_current_addr_reg] : '0; 

    // --- Synchronous Logic (State, Parameters, and LUT RAM R/W) ---
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            current_state <= IDLE;
            current_param_combined_reg <= '0;
            param_repeat_count_reg <= '0;
            param_data_length_reg <= '0;
            param_eof_reg <= '0;
            param_sof_reg <= '0;
            lut_current_addr_reg <= '0;
            for (int i = 0; i < LUT_RAM_DEPTH; i++) begin
                lut_ram[i] <= {IDLE, {8'd0, 16'd0, 1'd0, 1'd0}};
            end
        end else begin
            // FSM State Update
            current_state <= next_state;
            // LUT RAM Address Increment and Write Logic
            if (lut_internal_active) begin
                if (lut_read_write_mode_i) begin // Write mode
                    lut_ram[lut_current_addr_reg] <= lut_write_data_i;
                end
                // Increment address after R/W, wrapping around
                lut_current_addr_reg <= lut_current_addr_reg + 1;
            end else if (next_state == RST && current_state != RST) begin
                // Reset LUT RAM address when entering RST state
                lut_current_addr_reg <= '0;
            end
            // FSM Parameter Registers Update
            if (current_state == IDLE) begin // Update parameters when transitioning FROM IDLE
                current_param_combined_reg <= lut_param_read;
                param_repeat_count_reg <= lut_param_read[7:0];
                param_data_length_reg <= lut_param_read[23:8];
                param_eof_reg <= lut_param_read[24:24];
                param_sof_reg <= lut_param_read[25:25];
            end
        end
    end

    logic [2:0] lut_next_state_read; 
    logic [25:0] lut_param_read; 
    assign {lut_next_state_read, lut_param_read} = lut_ram[command_id_i];

    // --- Next State Logic (Combinational) ---
    always_comb begin
        next_state = current_state; // Default to current state (safety)
        case (current_state)
            IDLE: begin
                next_state = lut_next_state_read; // Determined by LUT RAM lookup
            end
            RST: begin
                if (task_done_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = RST;
                end
            end
            BACK_BIAS: begin
                if (task_done_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = BACK_BIAS;
                end
            end
            FLUSH: begin
                if (task_done_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = FLUSH;
                end
            end
            EXPOSE_TIME: begin
                if (task_done_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = EXPOSE_TIME;
                end
            end
            READOUT: begin
                if (task_done_i == '1' && adc_ready_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = READOUT;
                end
            end
            AED_DETECT: begin
                if (aed_detected_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = AED_DETECT;
                end
            end
            PANEL_STABLE: begin
                if (sensor_stable_i == '1') begin
                    next_state = IDLE;
                end
                if (True) begin
                    next_state = PANEL_STABLE;
                end
            end
            default: begin
                next_state = IDLE; // Fallback for unknown states
            end
        endcase
    end

    // --- Output Logic (Combinational) ---
    always_comb begin
        current_state_o = current_state;
        busy_o = (current_state != IDLE);
        sequence_done_o = (current_state == EXPOSE_TIME && next_state == IDLE && param_eof_reg == 1'b1);
        current_repeat_count_o = param_repeat_count_reg;
        current_data_length_o = param_data_length_reg;
        current_eof_o = param_eof_reg;
        current_sof_o = param_sof_reg;
        case (current_state)
            IDLE: begin
            end
            RST: begin
            end
            BACK_BIAS: begin
            end
            FLUSH: begin
            end
            EXPOSE_TIME: begin
            end
            READOUT: begin
            end
            AED_DETECT: begin
            end
            PANEL_STABLE: begin
            end
            default: begin
                // All outputs default to 0 for unknown states (handled above)
            end
        endcase
    end

endmodule