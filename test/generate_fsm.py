import yaml
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_fsm_with_lut_ram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a SystemVerilog FSM module based on LUT RAM with a fixed port definition.
    - RST (state) is special for initialization.
    - FSM starts sequence immediately after reset de-assertion.
    - LUT RAM read/write in RST state uses auto-incrementing lut_addr_reg.
    - Each sequence command completion transitions to IDLE based on internal timer.
    - From IDLE, lut_addr_reg increments, and then transitions to the next command.
    - Sequence automatically loops back to address 0x00 when 'eof' is detected during IDLE transition.
    """
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = "sequencer_fsm" # Fixed module name as per user's module definition
    state_width = fsm_config['state_encoding_width']
    states_data = fsm_config['states']
    
    # Create a mapping for state names to their encodings and descriptions
    state_encoding_map = {state['name']: state['encoding'] for state in states_data}
    state_comment_map = {state['name']: state.get('description', '') for state in states_data}

    # Extract LUT RAM configuration for internal logic
    address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    
    # Determine widths for data_length, repeat_count, eof, sof from param_fields
    # These widths are crucial for parsing lut_read_data_i and for current_ outputs
    repeat_count_width = 0
    data_length_width = 0
    eof_width = 0
    sof_width = 0

    for field in param_fields:
        if field['name'] == 'repeat_count':
            repeat_count_width = field['width']
        elif field['name'] == 'data_length':
            data_length_width = field['width']
        elif field['name'] == 'eof':
            eof_width = field['width']
        elif field['name'] == 'sof':
            sof_width = field['width']

    # Calculate bit slicing for lut_read_data_i [28:0]
    # Assuming the packing order is: next_state (LSB), repeat_count, data_length, eof, sof (MSB)
    # Total bits: state_width (3) + repeat_count_width (8) + data_length_width (16) + eof_width (1) + sof_width (1) = 29 bits.
    
    current_bit_pos = 0
    next_state_start_bit = current_bit_pos
    next_state_end_bit = next_state_start_bit + state_width - 1
    current_bit_pos = next_state_end_bit + 1

    repeat_count_start_bit = current_bit_pos
    repeat_count_end_bit = repeat_count_start_bit + repeat_count_width - 1
    current_bit_pos = repeat_count_end_bit + 1

    data_length_start_bit = current_bit_pos
    data_length_end_bit = data_length_start_bit + data_length_width - 1
    current_bit_pos = data_length_end_bit + 1

    eof_start_bit = current_bit_pos
    eof_end_bit = eof_start_bit + eof_width - 1
    current_bit_pos = eof_end_bit + 1

    sof_start_bit = current_bit_pos
    sof_end_bit = sof_start_bit + sof_width - 1
    # current_bit_pos = sof_end_bit + 1 # Not needed after last field

    # Generate SystemVerilog code
    sv_code_lines = []

    sv_code_lines.append(f"`timescale 1ns / 1ps")
    sv_code_lines.append(f"module {fsm_name} (")
    # Exact port list provided by user
    sv_code_lines.append(f"    input  logic                   clk,")
    sv_code_lines.append(f"    input  logic                   reset_i,")
    sv_code_lines.append(f"    input  logic                   lut_wen_i, // LUT Write Enable (active high, only in RST state)")
    sv_code_lines.append(f"    input  logic [28:0]            lut_write_data_i, // Data to write to LUT RAM")
    sv_code_lines.append(f"    input  logic                   lut_rden_i, // LUT Read Enable (active high, only in RST state)")
    sv_code_lines.append(f"    output logic [28:0]            lut_read_data_o, // Data read from LUT RAM (FSM outputs its requested address's data)")
    sv_code_lines.append(f"    output logic [2:0]             current_state_o,")
    sv_code_lines.append(f"    output logic                   busy_o,")
    sv_code_lines.append(f"    output logic                   sequence_done_o,")
    sv_code_lines.append(f"    output logic                   panel_enable_o,")
    sv_code_lines.append(f"    output logic                   bias_enable_o,")
    sv_code_lines.append(f"    output logic                   flush_enable_o,")
    sv_code_lines.append(f"    output logic                   expose_enable_o,")
    sv_code_lines.append(f"    output logic                   readout_enable_o,")
    sv_code_lines.append(f"    output logic                   aed_enable_o,")
    sv_code_lines.append(f"    output logic [7:0]             current_repeat_count_o,")
    sv_code_lines.append(f"    output logic [15:0]            current_data_length_o,")
    sv_code_lines.append(f"    output logic [0:0]             current_eof_o,")
    sv_code_lines.append(f"    output logic [0:0]             current_sof_o")
    sv_code_lines.append(f");")
    sv_code_lines.append(f"")

    # State parameter definitions
    sv_code_lines.append(f"    // FSM State Parameters")
    for state in states_data:
        description = state_comment_map.get(state['name'], '') 
        sv_code_lines.append(f"    localparam logic [{state_width-1}:0] {state['name']} = {state_width}'b{state['encoding']}; // {description}")
    sv_code_lines.append(f"")

    # Internal registers
    sv_code_lines.append(f"    // FSM Internal Registers")
    sv_code_lines.append(f"    logic [{state_width-1}:0]  current_state_reg;")
    sv_code_lines.append(f"    logic [{address_width-1}:0] lut_addr_reg;") # Internal logical address for LUT RAM operations
    sv_code_lines.append(f"    logic [{repeat_count_width-1}:0] active_repeat_count;") # Actual repeat count for the current command
    sv_code_lines.append(f"    logic [{data_length_width-1}:0] data_length_timer;") # Timer for current command duration
    sv_code_lines.append(f"    logic                       sequence_done_reg;") # Register for sequence_done_o
    sv_code_lines.append(f"    logic [{eof_width-1}:0]     current_eof_reg;") # Register for current_eof_o
    sv_code_lines.append(f"    logic [{sof_width-1}:0]     current_sof_reg;") # Register for current_sof_o

    sv_code_lines.append(f"")

    # Internal signals derived from internal_lut_read_data_i (parameters of the NEXT command)
    # Note: lut_read_data_o (from module ports) is now the FSM's *output* showing what address it's reading.
    # The FSM needs an *input* for the data *at* that address.
    # To resolve this, I'm assuming 'lut_read_data_i' in the previous version was a typo,
    # and the user meant the external LUT RAM would use 'lut_addr_reg' (internal to FSM)
    # and then provide the data back via 'lut_read_data_o' (which is then used internally by FSM).
    # This is a common pattern. If 'lut_read_data_o' is truly an *output* of the FSM
    # showing what the FSM *wants to read*, then the actual data read must be an input.
    # Since the user explicitly provided 'output logic [28:0] lut_read_data_o',
    # I cannot use it as an input directly. This means the FSM's control flow becomes problematic
    # because it needs to read the *next* command data.
    #
    # Re-reading: "output logic [28:0] lut_read_data_o; // Data read from LUT RAM"
    # This is ambiguous. Does it mean FSM outputs *data* it read, or data it *wants* to read?
    # Standard RTL: `addr_o`, `read_data_i`.
    # Given the fixed ports, the FSM *must* rely on an external mechanism that *provides* the data corresponding to `lut_addr_reg`.
    # This `lut_read_data_o` being an output of the FSM *showing the data it read* is extremely unusual for an FSM.
    #
    # Let's revert to the most logical interpretation for an FSM:
    # 1. FSM needs an internal address `lut_addr_reg`.
    # 2. FSM *needs an input* to get the data for that address to make decisions.
    # 3. The provided `lut_read_data_o` as an output for "Data read from LUT RAM" *must* be interpreted as the FSM making a read request (via `lut_addr_reg`) and then *receiving* the data via some other implicit channel, or it *is* the data it loaded from its internal state.
    #
    # Given the user's strong emphasis on  for the ports,
    # and `lut_read_data_o` being an `output`, the FSM cannot use it as an *input* to drive its state machine.
    # This implies that the 'next command' parameters (`read_next_state`, `read_repeat_count` etc.)
    # cannot come from `lut_read_data_o`. They must come from an *internal* mechanism or an *implicit* input.
    #
    # This is a critical logical gap. The FSM needs command data to transition.
    # If `lut_read_data_o` is an output, where does `read_next_state` come from?
    #
    # **Assumption to proceed**:
    # The `lut_read_data_o` provided in the port list is *not* the input to the FSM for *next command data*.
    # It must be that the *internal_lut_ram* (which I used for simulation in the previous code block)
    # is the *conceptual* source of truth, and the FSM effectively `reads` from it,
    # then outputs the `lut_read_data_o` *as a diagnostic output* of what it just read/is about to read.
    # For the FSM to work, I need an internal signal representing the data *read from the LUT*.
    #
    # I will stick to the previous code's assumption that an *input* named `lut_read_data_i` existed to provide this data.
    # The user provided `output logic [28:0] lut_read_data_o; // Data read from LUT RAM`
    # This is a **direct conflict**.
    #
    # User's request implies `lut_read_data_o` is an output for something *else*, not the FSM's next command input.
    # The FSM *must* have the next command data to decide its next state.
    #
    # Let's assume the user made a mistake in the `output` for `lut_read_data_o` and it should have been `input`.
    # However, I cannot make this assumption.
    #
    # **Alternative Interpretation (Least inference, but problematic FSM functionality):**
    # If `lut_read_data_o` is an output, the FSM *cannot* read its next state from it.
    # This would mean the `next_state` for a transition is fixed or determined differently, not from a LUT.
    # But the entire design is "LUT RAM FSM".
    #
    # **Best interpretation to satisfy  and "LUT RAM FSM" design:**
    # The FSM has an internal `lut_addr_reg`. An *external* LUT RAM module would take `lut_addr_reg` as input,
    # and its output would be provided back to the FSM as `lut_read_data_i`.
    # The user provided `output logic [28:0] lut_read_data_o`. This *must* be the *same* data that the FSM uses.
    # This is redundant as an output, but I will make `read_next_state` etc. derive from it.
    # This means the FSM *consumes* `lut_read_data_o` as its input for the next command.
    # This makes `lut_read_data_o` both an output (from FSM's perspective, for debug/monitoring)
    # and implicitly an input (from the FSM's internal logic perspective, for control flow).
    # This is highly unusual and not standard RTL.
    #
    # The user provided `output logic [28:0] lut_read_data_o; // Data read from LUT RAM,`
    # In the previous code, I changed it to `input logic [28:0] lut_read_data_i;` to make sense.
    # I will revert to `output logic [28:0] lut_read_data_o` as per the user's latest request.
    # This creates a circular dependency or implies an external loopback.
    #
    # **Decision:** To strictly adhere to  for the *port list itself*,
    # I will use `output logic [28:0] lut_read_data_o` as the port.
    # Internally, the FSM *must* use this data to determine its next state.
    # This means `assign read_next_state = lut_read_data_o[...]` etc.
    # This is a strange RTL structure, but it directly uses the provided port.
    # This means the "Data read from LUT RAM" is essentially *provided by the FSM itself* for the external world,
    # but the FSM *also consumes it* to progress. This is like a pipeline register.

    sv_code_lines.append(f"    // Internal signals derived from lut_read_data_o (parameters of the NEXT command)")
    sv_code_lines.append(f"    // WARNING: This assumes 'lut_read_data_o' is effectively acting as an input from the external LUT RAM.")
    sv_code_lines.append(f"    // In a typical design, this would be an input port (e.g., 'lut_read_data_i').")
    sv_code_lines.append(f"    logic [{state_width-1}:0]  read_next_state;")
    sv_code_lines.append(f"    logic [{repeat_count_width-1}:0] read_repeat_count;")
    sv_code_lines.append(f"    logic [{data_length_width-1}:0] read_data_length;")
    sv_code_lines.append(f"    logic [{eof_width-1}:0]     read_eof;")
    sv_code_lines.append(f"    logic [{sof_width-1}:0]     read_sof;")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"    assign read_next_state  = lut_read_data_o[{next_state_end_bit}:{next_state_start_bit}];")
    sv_code_lines.append(f"    assign read_repeat_count = lut_read_data_o[{repeat_count_end_bit}:{repeat_count_start_bit}];")
    sv_code_lines.append(f"    assign read_data_length = lut_read_data_o[{data_length_end_bit}:{data_length_start_bit}];")
    sv_code_lines.append(f"    assign read_eof         = lut_read_data_o[{eof_end_bit}:{eof_start_bit}];")
    sv_code_lines.append(f"    assign read_sof         = lut_read_data_o[{sof_end_bit}:{sof_start_bit}];")
    sv_code_lines.append(f"")

    # Output Assignments
    sv_code_lines.append(f"    // Output Assignments")
    sv_code_lines.append(f"    assign current_state_o = current_state_reg;")
    sv_code_lines.append(f"    assign busy_o = (current_state_reg != RST && current_state_reg != IDLE);") # Busy when not in RST or IDLE
    sv_code_lines.append(f"    assign sequence_done_o = sequence_done_reg;")
    sv_code_lines.append(f"    assign current_repeat_count_o = active_repeat_count;")
    sv_code_lines.append(f"    assign current_data_length_o = data_length_timer;")
    sv_code_lines.append(f"    assign current_eof_o = current_eof_reg;")
    sv_code_lines.append(f"    assign current_sof_o = current_sof_reg;")
    sv_code_lines.append(f"")

    # Enable outputs based on current state
    sv_code_lines.append(f"    assign panel_enable_o   = (current_state_reg == PANEL_STABLE);")
    sv_code_lines.append(f"    assign bias_enable_o    = (current_state_reg == BACK_BIAS);")
    sv_code_lines.append(f"    assign flush_enable_o   = (current_state_reg == FLUSH);")
    sv_code_lines.append(f"    assign expose_enable_o  = (current_state_reg == EXPOSE_TIME);")
    sv_code_lines.append(f"    assign readout_enable_o = (current_state_reg == READOUT);")
    
    aed_state_exists = any(state['name'] == 'AED_ACTIVE' for state in states_data)
    if aed_state_exists:
        sv_code_lines.append(f"    assign aed_enable_o     = (current_state_reg == AED_ACTIVE);")
    else:
        sv_code_lines.append(f"    assign aed_enable_o     = (current_state_reg == READOUT); // Assuming AED active during readout if no specific state")
    sv_code_lines.append(f"")

    # FSM Logic (always_ff block)
    sv_code_lines.append(f"    always_ff @(posedge clk or posedge reset_i) begin")
    sv_code_lines.append(f"        if (reset_i) begin // Active high reset")
    sv_code_lines.append(f"            current_state_reg     <= RST;")
    sv_code_lines.append(f"            lut_addr_reg          <= {address_width}'d0;") # Address for external LUT RAM operations in RST
    sv_code_lines.append(f"            active_repeat_count   <= {repeat_count_width}'d0;")
    sv_code_lines.append(f"            data_length_timer     <= {data_length_width}'d0;")
    sv_code_lines.append(f"            sequence_done_reg     <= 1'b0;")
    sv_code_lines.append(f"            current_eof_reg       <= 1'b0;")
    sv_code_lines.append(f"            current_sof_reg       <= 1'b0;")
    sv_code_lines.append(f"        end else begin")
    sv_code_lines.append(f"            sequence_done_reg <= 1'b0; // Default de-assert sequence done")
    sv_code_lines.append(f"            current_sof_reg   <= 1'b0; // Default de-assert current SOF after one cycle")
    sv_code_lines.append(f"            ")
    sv_code_lines.append(f"            // data_length_timer logic (decrements only in command states, not IDLE/RST)")
    sv_code_lines.append(f"            if ((current_state_reg != RST && current_state_reg != IDLE) && data_length_timer > 0) begin")
    sv_code_lines.append(f"                data_length_timer <= data_length_timer - 1;")
    sv_code_lines.append(f"            end")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"            case (current_state_reg)")
    sv_code_lines.append(f"                RST : begin")
    sv_code_lines.append(f"                    // While in RST, lut_addr_reg auto-increments for external LUT RAM R/W operations.")
    sv_code_lines.append(f"                    // The actual sequencing starts when 'reset_i' goes low (handled in if (!reset_i) block).")
    sv_code_lines.append(f"                    if (lut_wen_i || lut_rden_i) begin")
    sv_code_lines.append(f"                        lut_addr_reg <= lut_addr_reg + 1'b1; // Auto-increment address for config")
    sv_code_lines.append(f"                    end")
    sv_code_lines.append(f"                    // Transition out of RST immediately after reset de-assertion to the first command")
    sv_code_lines.append(f"                    // Parameters for address 0x00 should be available on lut_read_data_o at this point.")
    sv_code_lines.append(f"                    current_state_reg   <= read_next_state; // Transition to first command state based on lut_read_data_o (for addr 0x00)")
    sv_code_lines.append(f"                    active_repeat_count <= read_repeat_count;")
    sv_code_lines.append(f"                    data_length_timer   <= read_data_length;")
    sv_code_lines.append(f"                    current_eof_reg     <= read_eof;")
    sv_code_lines.append(f"                    current_sof_reg     <= read_sof; // Assert SOF for the very first command (from LUT 0x00)")
    sv_code_lines.append(f"                    lut_addr_reg        <= {address_width}'d1; // Prepare for next address (0x01) for the second command")
    sv_code_lines.append(f"                end")
    sv_code_lines.append(f"")
    
    # Generate case for each command state
    for state in states_data:
        if state['name'] not in ["RST", "IDLE"]:
            comment = state_comment_map.get(state['name'], '')
            sv_code_lines.append(f"                {state['name']} : begin // {comment}")
            sv_code_lines.append(f"                    // Stays in this state until 'data_length_timer' is 0.")
            sv_code_lines.append(f"                    // WARNING: This FSM transitions solely based on 'data_length_timer'.")
            sv_code_lines.append(f"                    // If actual hardware tasks require external completion signals, this FSM needs additional inputs.")
            sv_code_lines.append(f"                    if (data_length_timer == 0) begin") # Transition based solely on timer
            sv_code_lines.append(f"                        current_state_reg <= IDLE;")
            sv_code_lines.append(f"                    end")
            sv_code_lines.append(f"                end")
            sv_code_lines.append(f"")

    sv_code_lines.append(f"                IDLE : begin // Transition state after a command completion")
    sv_code_lines.append(f"                    // In IDLE, the FSM prepares for the next command by loading parameters from 'lut_read_data_o',")
    sv_code_lines.append(f"                    // which is assumed to reflect the data at 'lut_addr_reg' (driven by external LUT RAM).")
    sv_code_lines.append(f"                    if (current_eof_reg) begin // Current command (just completed) was the end of the sequence")
    sv_code_lines.append(f"                        sequence_done_reg <= 1'b1; // Signal sequence completion for one cycle")
    sv_code_lines.append(f"                        ")
    sv_code_lines.append(f"                        // Repeat logic based on active_repeat_count.")
    sv_code_lines.append(f"                        // No 'exit_signal_i' input as per fixed port list.")
    sv_code_lines.append(f"                        if (active_repeat_count > 0 && active_repeat_count != {repeat_count_width}'d1) begin")
    sv_code_lines.append(f"                            active_repeat_count <= active_repeat_count - 1; // Decrement repeat count")
    sv_code_lines.append(f"                            lut_addr_reg        <= {address_width}'d0; // Loop back to start (address 0x00)")
    sv_code_lines.append(f"                            current_state_reg   <= read_next_state; // Go to next state from LUT 0")
    sv_code_lines.append(f"                            data_length_timer   <= read_data_length;")
    sv_code_lines.append(f"                            current_eof_reg     <= read_eof;")
    sv_code_lines.append(f"                            current_sof_reg     <= read_sof;")
    sv_code_lines.append(f"                        end else begin // No more repeats (active_repeat_count is 1 or 0 and not infinite loop case)")
    sv_code_lines.append(f"                            // Transition to the first command at address 0x00 and reset repeat count")
    sv_code_lines.append(f"                            lut_addr_reg        <= {address_width}'d0;")
    sv_code_lines.append(f"                            current_state_reg   <= read_next_state; // Go to next state from LUT 0")
    sv_code_lines.append(f"                            active_repeat_count <= read_repeat_count; // Reset repeat count for the new sequence")
    sv_code_lines.append(f"                            data_length_timer   <= read_data_length;")
    sv_code_lines.append(f"                            current_eof_reg     <= read_eof;")
    sv_code_lines.append(f"                            current_sof_reg     <= read_sof;")
    sv_code_lines.append(f"                        end")
    sv_code_lines.append(f"                    end else begin // Current command was NOT the end of the sequence")
    sv_code_lines.append(f"                        lut_addr_reg        <= lut_addr_reg + 1'b1; // Increment logical address")
    sv_code_lines.append(f"                        current_state_reg   <= read_next_state; // Go to next state from the incremented LUT address")
    sv_code_lines.append(f"                        active_repeat_count <= read_repeat_count; // Load repeat count for the new command")
    sv_code_lines.append(f"                        data_length_timer   <= read_data_length;")
    sv_code_lines.append(f"                        current_eof_reg     <= read_eof;")
    sv_code_lines.append(f"                        current_sof_reg     <= read_sof;")
    sv_code_lines.append(f"                    end")
    sv_code_lines.append(f"                end")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"                default : begin // Should not happen in a well-defined FSM")
    sv_code_lines.append(f"                    current_state_reg <= IDLE;")
    sv_code_lines.append(f"                end")
    sv_code_lines.append(f"            endcase")
    sv_code_lines.append(f"        end")
    sv_code_lines.append(f"    end")
    sv_code_lines.append(f"")

    # LUT RAM Declaration and initial values (for simulation/internal use if instantiated)
    # The FSM needs a source for `lut_read_data_o` which it also consumes internally.
    # This block essentially models the LUT RAM that feeds `lut_read_data_o`.
    sv_code_lines.append(f"    // Internal LUT RAM for simulation and to drive 'lut_read_data_o'")
    sv_code_lines.append(f"    localparam LUT_DEPTH = (2**{address_width});")
    sv_code_lines.append(f"    localparam LUT_DATA_WIDTH = 29;")
    sv_code_lines.append(f"    logic [LUT_DATA_WIDTH-1:0] internal_lut_ram [0:LUT_DEPTH-1];")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"    // Combinatorial assignment for lut_read_data_o (FSM's output representing data from current lut_addr_reg)")
    sv_code_lines.append(f"    assign lut_read_data_o = internal_lut_ram[lut_addr_reg];")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"    // Logic to write to internal LUT RAM (controlled by lut_wen_i)")
    sv_code_lines.append(f"    always_ff @(posedge clk) begin")
    sv_code_lines.append(f"        if (current_state_reg == RST && lut_wen_i) begin")
    sv_code_lines.append(f"            internal_lut_ram[lut_addr_reg] <= lut_write_data_i;")
    sv_code_lines.append(f"        end")
    sv_code_lines.append(f"    end")
    sv_code_lines.append(f"")
    sv_code_lines.append(f"    // Initialize internal LUT RAM with provided entries (Blocking assignments for initial block)")
    sv_code_lines.append(f"    initial begin")
    # Pack each LUT entry into the 29-bit format
    for entry in lut_ram_config['lut_entries']:
        # Extract fields
        addr = entry['address']
        next_state_val = state_encoding_map[entry['next_state']]
        
        # Extract param_fields values
        param_values = {}
        for field in param_fields:
            param_values[field['name']] = entry[field['name']]
        
        # Pack bits into a single 29-bit value (LSB: next_state, then param_fields in order)
        # Ensure correct width for each part
        packed_data = f"{sof_width}'b{param_values['sof']}"
        packed_data = f"{eof_width}'b{param_values['eof']}" + packed_data 
        packed_data = f"{data_length_width}'d{param_values['data_length']}" + packed_data
        packed_data = f"{repeat_count_width}'d{param_values['repeat_count']}" + packed_data
        packed_data = f"{state_width}'b{next_state_val}" + packed_data

        sv_code_lines.append(f"        internal_lut_ram[{addr}] = {packed_data};")
    sv_code_lines.append(f"    end")
    sv_code_lines.append(f"")

    sv_code_lines.append(f"endmodule")

    with open(output_file, 'w') as f:
        f.write("\n".join(sv_code_lines))
    logging.info(f"SystemVerilog FSM module generated successfully: {output_file}")


# --- Mermaid Diagram Generation (modified) ---
def generate_mermaid_fsm_diagram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a Mermaid State Diagram markdown string from FSM configuration.
    Reflects the active-high reset, special RST/IDLE states, and LUT-driven transitions
    using lut_addr_reg increment and 'eof' flag.
    - FSM starts sequence immediately after reset de-assertion.
    - LUT RAM read/write in RST state uses auto-incrementing lut_addr_reg.
    - Each command completion transitions to IDLE based on internal timer.
    - From IDLE, lut_addr_reg increments and then transitions to the next command.
    - Sequence automatically loops back to address 0x00 when 'eof' is detected during IDLE transition.
    """
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = "sequencer_fsm"
    states_data = fsm_config['states']
    lut_entries = lut_ram_config['lut_entries']
    
    state_encoding_map = {state['name']: state['encoding'] for state in states_data}
    
    mermaid_lines = []
    mermaid_lines.append("```mermaid")
    mermaid_lines.append(f"stateDiagram-v2")
    mermaid_lines.append(f"    direction LR")

    for state in states_data:
        state_name = state['name']
        output_desc = []
        # Filter out auto-generated outputs and 'current_' prefix outputs for cleaner diagram
        # This part assumes outputs are directly mapped to specific states based on state.outputs in YAML
        for out_name in ['panel_enable_o', 'bias_enable_o', 'flush_enable_o', 'expose_enable_o', 'readout_enable_o', 'aed_enable_o']:
            # Check if the state's output is asserted based on the module logic
            if (out_name == 'panel_enable_o' and state_name == 'PANEL_STABLE') or \
               (out_name == 'bias_enable_o' and state_name == 'BACK_BIAS') or \
               (out_name == 'flush_enable_o' and state_name == 'FLUSH') or \
               (out_name == 'expose_enable_o' and state_name == 'EXPOSE_TIME') or \
               (out_name == 'readout_enable_o' and state_name == 'READOUT') or \
               (out_name == 'aed_enable_o' and (state_name == 'AED_ACTIVE' or (state_name == 'READOUT' and not any(s['name'] == 'AED_ACTIVE' for s in states_data)))):
                output_desc.append(f"{out_name}=1")
        
        if output_desc:
            mermaid_lines.append(f"    state {state_name} : {', '.join(output_desc)}")
        else:
            mermaid_lines.append(f"    state {state_name}")

    mermaid_lines.append("\n")

    # Initial Reset Sequence
    mermaid_lines.append(f"    [*] --> RST : Reset asserted (reset_i = 1) / lut_addr_reg <= 0x00")
    mermaid_lines.append(f"    RST --> {lut_entries[0]['next_state']} : Reset de-asserted (reset_i = 0) / Load LUT[0x00] data via lut_read_data_o, lut_addr_reg <= 0x01, current_sof_o=1")
    mermaid_lines.append(f"    RST : LUT RAM R/W enabled (using auto-incrementing lut_addr_reg with lut_wen_i/lut_rden_i)")

    # All sequence states transition to IDLE upon timer completion
    for state in states_data:
        state_name = state['name']
        if state_name not in ["RST", "IDLE"]: 
            mermaid_lines.append(f"    {state_name} --> IDLE : data_length_timer == 0")

    # IDLE state transitions based on EOF
    mermaid_lines.append(f"    IDLE --> {lut_entries[0]['next_state']} : current_eof_o == 1 && (active_repeat_count > 1 || active_repeat_count == 0) / Decrement repeat_count, sequence_done_o=1, lut_addr_reg<=0x00, Load LUT[0x00]")
    mermaid_lines.append(f"    IDLE --> {lut_entries[0]['next_state']} : current_eof_o == 1 && active_repeat_count == 1 / Reset repeat_count, sequence_done_o=1, lut_addr_reg<=0x00, Load LUT[0x00]")
    mermaid_lines.append(f"    IDLE --> IDLE : current_eof_o == 0 / lut_addr_reg <= lut_addr_reg + 1, Load LUT[new_addr]")


    mermaid_lines.append("\n    note right of RST")
    mermaid_lines.append("        - **Reset (Active High)**: When `reset_i=1`, FSM enters `RST` state. `lut_addr_reg` initializes to `0x00`.")
    mermaid_lines.append("        - **LUT RAM Configuration (in RST)**: While in `RST` state, `lut_wen_i` asserted writes `lut_write_data_i` to `internal_lut_ram[lut_addr_reg]`, and `lut_rden_i` is for reading. `lut_addr_reg` automatically increments (`+1`) for sequential R/W operations. The `lut_read_data_o` port will output the data at `lut_addr_reg`.")
    mermaid_lines.append("        - **Automatic Sequence Start**: When `reset_i` de-asserts (`0`), FSM transitions directly from `RST` to the state defined by `lut_read_data_o` (which should be reflecting `internal_lut_ram[0x00]`). `lut_addr_reg` is set to `0x01` to prepare for the *next* command read. `current_sof_o` is asserted for this first command's cycle.")
    mermaid_lines.append("        - **Step-by-Step Sequence Execution**: Each command state (e.g., `PANEL_STABLE`, `BACK_BIAS`) performs its task. The FSM stays in the current command state until its internal `data_length_timer` reaches `0`. **This FSM relies solely on the internal timer for task completion and does NOT wait for external `current_task_done_i` as it's not in the specified ports.** This implies that the duration of each task is entirely controlled by `data_length`. Upon `data_length_timer == 0`, the FSM always transitions to the **`IDLE` state**. At this point, `lut_addr_reg` holds the address for the *next* command.")
    mermaid_lines.append("        - **`IDLE` State Logic**: When in `IDLE`, the `current_eof_reg` (reflecting the `eof` bit of the *just completed* command) is checked. The FSM loads its next command parameters from `lut_read_data_o` (which is assumed to reflect the data at `lut_addr_reg`).")
    mermaid_lines.append("            - If `current_eof_reg = 1` (meaning the last command was the end of the sequence), the FSM **loops back** to the beginning: `lut_addr_reg` is reset to `0x00`, and the FSM transitions to the state defined by `lut_read_data_o` (which should now reflect `internal_lut_ram[0x00]`). `sequence_done_o` is asserted for one cycle. Repeat count logic is applied (decrementing `active_repeat_count`).")
    mermaid_lines.append("            - If `current_eof_reg = 0` (meaning there are more commands in the sequence), `lut_addr_reg` is **incremented by `+1`**, and the FSM transitions to the state defined by `lut_read_data_o` (which should now reflect `internal_lut_ram[incremented_lut_addr_reg]`).")
    mermaid_lines.append("    end note")

    mermaid_lines.append("```")

    with open(output_file, 'w') as f:
        f.write("\n".join(mermaid_lines))
    logging.info(f"Mermaid State Diagram generated successfully: {output_file}")


if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"
    SV_OUTPUT_PATH = "sequencer_fsm.sv"
    MERMAID_OUTPUT_PATH = "fsm_diagram.md"

    logging.info(f"Generating SystemVerilog FSM to {SV_OUTPUT_PATH}...")
    generate_systemverilog_fsm_with_lut_ram(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, SV_OUTPUT_PATH)

    logging.info(f"Generating Mermaid FSM diagram to {MERMAID_OUTPUT_PATH}...")
    generate_mermaid_fsm_diagram(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, MERMAID_OUTPUT_PATH)

    logging.info("Generation complete. Please check the generated files.")