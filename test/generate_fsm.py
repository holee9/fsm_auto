import yaml
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_fsm_with_lut_ram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a SystemVerilog FSM module based on LUT RAM.
    - Includes advanced handling for data_length, repeat, and exit_signal.
    """
    # 파일 존재 여부 확인
    if not os.path.exists(fsm_config_path):
        logging.error(f"Error: FSM configuration file not found at {fsm_config_path}")
        sys.exit(1)
    if not os.path.exists(lut_ram_config_path):
        logging.error(f"Error: LUT RAM data file not found at {lut_ram_config_path}")
        sys.exit(1)

    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = fsm_config['fsm_name']
    state_width = fsm_config['state_encoding_width']
    states_data = fsm_config['states']
    
    # Create a mapping for state names to their encodings
    state_encoding_map = {state['name']: state['encoding'] for state in states_data}
    
    lut_address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    
    # Calculate lut_data_width: state_width + sum of all param_fields widths
    total_param_width = sum(field['width'] for field in param_fields)
    lut_data_width = state_width + total_param_width 
    
    inputs = fsm_config['inputs']
    outputs = fsm_config['outputs']

    input_ports = []
    # Always include clk and reset_i
    input_ports.append(f"    input logic clk") 
    input_ports.append(f"    input logic reset_i") 
    
    # Add new input for infinite loop exit
    input_ports.append(f"    input logic exit_signal_i;")

    # Add LUT RAM specific inputs (fixed width after calculation)
    input_ports.append(f"    input logic lut_wen_i; // LUT Write Enable (active high, only in RST state)")
    input_ports.append(f"    input logic [{lut_data_width-1}:0] lut_write_data_i; // Data to write to LUT RAM")
    input_ports.append(f"    input logic lut_rden_i; // LUT Read Enable (active high, only in RST state)") 

    # List of signals that should be internal for simulation purposes, not external inputs
    internal_sim_signals = [
        'internal_task_done', 
        'internal_adc_ready', 
        'internal_sensor_stable', 
        'internal_aed_detected'
    ]

    # Other non-control inputs from fsm_config.yaml, excluding those listed in internal_sim_signals
    for inp in inputs:
        # Skip control signals already handled or removed, AND signals defined as internal for simulation
        if inp['name'] in ['clk', 'reset_i', 'lut_wen_i', 'lut_write_data_i', 'lut_rden_i', 'exit_signal_i'] or \
           inp['name'] in internal_sim_signals: 
            continue 
        elif inp['width'] == 1:
            input_ports.append(f"    input logic {inp['name']}")
        else:
            input_ports.append(f"    input logic [{inp['width']-1}:0] {inp['name']}")

    output_ports = []
    # Add LUT RAM specific output (fixed width after calculation)
    output_ports.append(f"    output logic [{lut_data_width-1}:0] lut_read_data_o; // Data read from LUT RAM") 

    for out in outputs:
        # Skip output already handled
        if out['name'] == 'lut_read_data_o':
            continue 
        elif out['width'] == 1:
            output_ports.append(f"    output logic {out['name']}")
        else:
            output_ports.append(f"    output logic [{out['width']-1}:0] {out['name']}")

    sv_code = []
    sv_code.append(f"`timescale 1ns / 1ps")
    sv_code.append(f"")
    sv_code.append(f"module {fsm_name} (")
    sv_code.append(",\n".join(input_ports + output_ports))
    sv_code.append(");")
    sv_code.append("")

    # Localparams for states
    for state_name, encoding in state_encoding_map.items():
        sv_code.append(f"    localparam {state_name} = {state_width}'d{encoding};")
    sv_code.append("")

    sv_code.append(f"    logic [{state_width-1}:0] current_state_reg;")
    sv_code.append("")

    sv_code.append(f"    // LUT Address Register. This points to the current LUT entry being processed.")
    sv_code.append(f"    logic [{lut_address_width-1}:0] lut_addr_reg; ")
    
    # New internal registers for data_length and repeat functionality
    # Determine max width for data_length_timer and active_repeat_count
    max_data_length = 0
    max_repeat_count = 0
    for entry in lut_ram_config['lut_entries']:
        for field in param_fields:
            if field['name'] == 'data_length':
                max_data_length = max(max_data_length, entry.get('data_length', 0))
            if field['name'] == 'repeat_count':
                max_repeat_count = max(max_repeat_count, entry.get('repeat_count', 0))

    data_length_width = (max_data_length - 1).bit_length() if max_data_length > 0 else 1 # At least 1 bit for 0
    repeat_count_width = (max_repeat_count - 1).bit_length() if max_repeat_count > 0 else 1 # At least 1 bit for 0

    sv_code.append(f"    logic [{data_length_width-1}:0] data_length_timer; // Timer for data_length parameter")
    sv_code.append(f"    logic [{repeat_count_width-1}:0] active_repeat_count; // Counter for repeat_count parameter")
    
    sv_code.append(f"    // Simulated internal task completion signals - These are for simulation purposes only, not external inputs.")
    sv_code.append(f"    logic internal_task_done;")
    sv_code.append(f"    logic internal_adc_ready;")
    sv_code.append(f"    logic internal_sensor_stable;")
    sv_code.append(f"    logic internal_aed_detected;")
    sv_code.append(f"")

    # Extract parameter field widths for parsing LUT data
    eof_field = next((field for field in param_fields if field['name'] == 'eof'), None)
    if not eof_field:
        raise ValueError("fsm_lut_ram_data.yaml must define an 'eof' field in 'param_fields'.")
    eof_width = eof_field['width']

    # Define current_ parameters based on fields in LUT RAM
    for field in param_fields:
        sv_code.append(f"    logic [{field['width']-1}:0] current_{field['name']};")
    sv_code.append(f"")

    sv_code.append(f"    // LUT RAM Declaration")
    sv_code.append(f"    logic [{lut_data_width-1}:0] lut_ram [0:{(2**lut_address_width)-1}];")
    sv_code.append(f"")
    
    sv_code.append(f"    // LUT data for current address (combinatorial read for FSM internal use)")
    sv_code.append(f"    logic [{lut_data_width-1}:0] lut_read_current_addr_internal;")
    sv_code.append(f"    assign lut_read_current_addr_internal = lut_ram[lut_addr_reg]; ")
    sv_code.append(f"")
    
    # Calculate bit positions for state and parameters within the LUT entry
    # next_state is at the MSB side
    next_state_start_bit = total_param_width
    sv_code.append(f"    logic [{state_width-1}:0] next_state_from_lut;")
    sv_code.append(f"    assign next_state_from_lut = lut_read_current_addr_internal[{next_state_start_bit+state_width-1}:{next_state_start_bit}];")
    sv_code.append(f"")

    # FSM State Register and lut_addr_reg management
    sv_code.append(f"    // FSM State Register and LUT Address Management")
    sv_code.append(f"    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset")
    sv_code.append(f"        if (reset_i) begin // Reset asserted (active high)")
    sv_code.append(f"            current_state_reg <= RST; // Go to RST state on reset assertion")
    sv_code.append(f"            lut_addr_reg <= {lut_address_width}'h00; // Initialize LUT address for RAM config")
    sv_code.append(f"            data_length_timer <= '0;")
    sv_code.append(f"            active_repeat_count <= '0;")
    sv_code.append(f"        end else begin")
    sv_code.append(f"            case (current_state_reg)")
    sv_code.append(f"                RST: begin")
    sv_code.append(f"                    // Reset de-asserted: transition to the first sequence state (from LUT[0x00])")
    sv_code.append(f"                    current_state_reg <= lut_ram[{lut_address_width}'h00][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; ")
    sv_code.append(f"                    lut_addr_reg <= {lut_address_width}'h00; // Reset address for sequence execution")
    sv_code.append(f"                    data_length_timer <= lut_ram[{lut_address_width}'h00][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for the first command")
    sv_code.append(f"                    active_repeat_count <= lut_ram[{lut_address_width}'h00][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for the first command")
    sv_code.append(f"                end")
    sv_code.append(f"                IDLE: begin")
    sv_code.append(f"                    // In IDLE, process repeat and EOF logic, then determine next state and address")
    sv_code.append(f"                    if (active_repeat_count > 0) begin // If current command needs to be repeated")
    sv_code.append(f"                        active_repeat_count <= active_repeat_count - 1; // Decrement repeat counter")
    sv_code.append(f"                        // Stay at the same lut_addr_reg to re-execute the command")
    sv_code.append(f"                        current_state_reg <= next_state_from_lut; // Go back to the command state")
    sv_code.append(f"                        data_length_timer <= current_data_length; // Re-initialize data_length_timer")
    sv_code.append(f"                    end else if (current_repeat_count == 0 && exit_signal_i) begin // Infinite repeat and exit signal is asserted")
    sv_code.append(f"                        lut_addr_reg <= lut_addr_reg + 1; // Move to the next command")
    sv_code.append(f"                        current_state_reg <= lut_ram[lut_addr_reg + 1][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; // Transition to the next state")
    sv_code.append(f"                        data_length_timer <= lut_ram[lut_addr_reg + 1][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for the next command")
    sv_code.append(f"                        active_repeat_count <= lut_ram[lut_addr_reg + 1][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for the next command")
    sv_code.append(f"                    end else if (current_eof) begin // End of sequence, loop back to 0x00")
    sv_code.append(f"                        lut_addr_reg <= {lut_address_width}'h00; // Loop back to start of sequence")
    sv_code.append(f"                        current_state_reg <= lut_ram[{lut_address_width}'h00][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; // Go to state from LUT[0x00]")
    sv_code.append(f"                        data_length_timer <= lut_ram[{lut_address_width}'h00][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for first command")
    sv_code.append(f"                        active_repeat_count <= lut_ram[{lut_address_width}'h00][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for first command")
    sv_code.append(f"                    end else begin // Proceed to the next command in sequence")
    sv_code.append(f"                        lut_addr_reg <= lut_addr_reg + 1; // Increment for the next command")
    sv_code.append(f"                        current_state_reg <= lut_ram[lut_addr_reg + 1][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; // Go to next state from LUT for (current lut_addr_reg + 1)")
    sv_code.append(f"                        data_length_timer <= lut_ram[lut_addr_reg + 1][current_data_length_lsb + current_data_length_width - 1 : current_data_length_lsb]; // Initialize data_length_timer for next command")
    sv_code.append(f"                        active_repeat_count <= lut_ram[lut_addr_reg + 1][current_repeat_count_lsb + current_repeat_count_width - 1 : current_repeat_count_lsb]; // Initialize active_repeat_count for next command")
    sv_code.append(f"                    end")
    sv_code.append(f"                end") 
    
    # All non-RST, non-IDLE states transition to IDLE upon task completion AND data_length_timer == 0
    for state in states_data:
        state_name = state['name']
        if state_name != "RST" and state_name != "IDLE": 
            completion_signal = ""
            if state_name == "PANEL_STABLE": completion_signal = "internal_sensor_stable"
            elif state_name == "BACK_BIAS": completion_signal = "internal_task_done"
            elif state_name == "FLUSH": completion_signal = "internal_task_done"
            elif state_name == "EXPOSE_TIME": completion_signal = "internal_task_done"
            elif state_name == "READOUT": completion_signal = "(internal_task_done && internal_adc_ready)"
            elif state_name == "AED_DETECT": completion_signal = "internal_aed_detected" 
            
            if completion_signal:
                sv_code.append(f"                {state_name}: begin")
                sv_code.append(f"                    if (data_length_timer > 0) begin")
                sv_code.append(f"                        data_length_timer <= data_length_timer - 1; // Decrement timer")
                sv_code.append(f"                        current_state_reg <= {state_name}; // Stay in current state")
                sv_code.append(f"                    end else if ({completion_signal}) begin")
                sv_code.append(f"                        current_state_reg <= IDLE; // Task done AND data_length met, go to IDLE")
                sv_code.append(f"                        // lut_addr_reg and counters will be updated in IDLE")
                sv_code.append(f"                    end else begin")
                sv_code.append(f"                        current_state_reg <= {state_name}; // Stay in current state")
                sv_code.append(f"                    end")
                sv_code.append(f"                end")
    sv_code.append(f"                default: begin")
    sv_code.append(f"                    current_state_reg <= RST; // Fallback to RST on unexpected state")
    sv_code.append(f"                    lut_addr_reg <= {lut_address_width}'h00;") 
    sv_code.append(f"                    data_length_timer <= '0;")
    sv_code.append(f"                    active_repeat_count <= '0;")
    sv_code.append(f"                end")
    sv_code.append(f"            endcase")
    sv_code.append(f"        end")
    sv_code.append(f"    end")
    sv_code.append("")

    # Separate always_ff block for lut_addr_reg increment during RST
    sv_code.append(f"    // lut_addr_reg auto-increment in RST state for LUT RAM configuration")
    sv_code.append(f"    always_ff @(posedge clk) begin")
    sv_code.append(f"        if (current_state_reg == RST && (lut_wen_i || lut_rden_i)) begin")
    sv_code.append(f"            lut_addr_reg <= lut_addr_reg + 1;")
    sv_code.append(f"        end")
    sv_code.append(f"    end")
    sv_code.append("")

    sv_code.append(f"    // FSM Parameter Assignments (from LUT RAM data - combinatorial, based on lut_addr_reg)")
    sv_code.append(f"    always_comb begin")
    
    # Find bit positions for data_length and repeat_count within param_fields
    current_bit_pos = 0
    # Store LSB and width for easy access later
    current_data_length_lsb = -1
    current_data_length_width = -1
    current_repeat_count_lsb = -1
    current_repeat_count_width = -1

    # Assign actual parameters including 'eof', 'sof', 'data_length', 'repeat_count'
    # Iterate in reverse to correctly build from LSB (assuming param_fields are LSB to MSB)
    for field in reversed(param_fields): 
        if field['name'] == 'data_length':
            current_data_length_lsb = current_bit_pos
            current_data_length_width = field['width']
        elif field['name'] == 'repeat_count':
            current_repeat_count_lsb = current_bit_pos
            current_repeat_count_width = field['width']

        sv_code.append(f"        current_{field['name']} = lut_read_current_addr_internal[{current_bit_pos + field['width']-1}:{current_bit_pos}];")
        current_bit_pos += field['width']
    sv_code.append(f"    end")
    sv_code.append(f"")

    # This part injects the Python variables into the SystemVerilog string.
    # It must be inside the generate_systemverilog_fsm_with_lut_ram function
    # where current_data_length_lsb, etc., are calculated.
    sv_code.append(f"    // These are LSB positions and widths for data_length and repeat_count within LUT entry. Generated for internal use.")
    sv_code.append(f"    localparam DATA_LENGTH_LSB = {current_data_length_lsb};")
    sv_code.append(f"    localparam DATA_LENGTH_WIDTH = {current_data_length_width};")
    sv_code.append(f"    localparam REPEAT_COUNT_LSB = {current_repeat_count_lsb};")
    sv_code.append(f"    localparam REPEAT_COUNT_WIDTH = {current_repeat_count_width};")
    sv_code.append(f"")

    # --- Internal Signal Generation (Simulated for verification) ---
    # This block simulates task completion signals, not part of the FSM itself.
    sv_code.append(f"    // Internal Signal Generation Logic (Simulated for verification)")
    sv_code.append(f"    // Note: 'task_timer' here simulates how long a task takes, independent of data_length_timer.")
    sv_code.append(f"    // The actual FSM transition depends on 'data_length_timer == 0' AND the corresponding internal_task_done signal.")
    sv_code.append(f"    logic [7:0] task_timer;") # Max 255 cycles for internal task
    sv_code.append(f"    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset")
    sv_code.append(f"        if (reset_i) begin // Reset asserted")
    sv_code.append(f"            task_timer <= '0;")
    sv_code.append(f"            internal_task_done <= 1'b0;")
    sv_code.append(f"            internal_adc_ready <= 1'b0;")
    sv_code.append(f"            internal_sensor_stable <= 1'b0;")
    sv_code.append(f"            internal_aed_detected <= 1'b0;")
    sv_code.append(f"        end else begin")
    sv_code.append(f"            // Reset signals before new evaluation each cycle")
    sv_code.append(f"            internal_task_done <= 1'b0;") 
    sv_code.append(f"            internal_adc_ready <= 1'b0;")
    sv_code.append(f"            internal_sensor_stable <= 1'b0;")
    sv_code.append(f"            internal_aed_detected <= 1'b0;")
    
    sv_code.append(f"            case (current_state_reg)")
    sv_code.append(f"                RST, IDLE: begin")
    sv_code.append(f"                    task_timer <= '0; // Reset timer when in RST or IDLE")
    sv_code.append(f"                end")
    sv_code.append(f"                BACK_BIAS, FLUSH, EXPOSE_TIME: begin") 
    sv_code.append(f"                    if (task_timer >= 8'd20) begin") # Example fixed task time
    sv_code.append(f"                        internal_task_done <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                PANEL_STABLE: begin")
    sv_code.append(f"                    if (task_timer >= 8'd15) begin") # Example fixed task time
    sv_code.append(f"                        internal_sensor_stable <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                READOUT: begin")
    sv_code.append(f"                    if (task_timer >= 8'd50) begin") # Example fixed task time
    sv_code.append(f"                        internal_task_done <= 1'b1;")
    sv_code.append(f"                        internal_adc_ready <= 1'b1;") 
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else if (task_timer >= 8'd40) begin") # Example: ADC ready 10 cycles before task done
    sv_code.append(f"                        internal_adc_ready <= 1'b1;")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        internal_adc_ready <= 1'b0;")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                AED_DETECT: begin")
    sv_code.append(f"                    if (task_timer >= 8'd10) begin") # Example fixed task time
    sv_code.append(f"                        internal_aed_detected <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                default: task_timer <= '0;") 
    sv_code.append(f"            endcase")
    sv_code.append(f"        end")
    sv_code.append(f"    end")
    sv_code.append(f"")
    
    # FSM Outputs
    sv_code.append(f"    // FSM Outputs Assignments")
    sv_code.append(f"    assign current_state_o = current_state_reg;")
    sv_code.append(f"    // Busy if not in RST or IDLE. In this model, IDLE is a transient state between commands, so FSM is always 'busy' once sequence starts.")
    sv_code.append(f"    assign busy_o = (current_state_reg != RST); ") 
    
    # sequence_done_o assertion logic: asserted when in IDLE and the command just completed was EOF AND not repeating
    sv_code.append(f"    // sequence_done_o is asserted when in IDLE, the command just completed was EOF, AND the command is not repeating.")
    sv_code.append(f"    // It will be asserted for one cycle before looping back to the first command.")
    sv_code.append(f"    assign sequence_done_o = (current_state_reg == IDLE && current_eof == 1'b1 && active_repeat_count == 0 && current_repeat_count == 0);") 

    # Outputs for FSM specific control (derived from `fsm_config.yaml` outputs)
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] or out['name'].startswith('current_'):
            continue # These are handled separately

        # Find the state where this output is defined and its value
        # This assumes outputs are directly mapped from current_state_reg and are mutually exclusive
        output_cases = []
        for state in states_data:
            if 'outputs' in state and out['name'] in state['outputs']:
                output_cases.append(f"                {state['name']}: {state['outputs'][out['name']]};")
        
        if output_cases:
            sv_code.append(f"    assign {out['name']} = (")
            sv_code.append(f"        current_state_reg == {output_cases[0].split(':')[0].strip()}")
            for i in range(1, len(output_cases)):
                sv_code.append(f"        || current_state_reg == {output_cases[i].split(':')[0].strip()}")
            sv_code.append(f"    ) ? 1'b1 : 1'b0;")
        else:
            sv_code.append(f"    assign {out['name']} = 1'b0;") # Default to 0 if not explicitly defined in any state
    
    # Outputs for current LUT parameters
    for field in param_fields:
        sv_code.append(f"    assign current_{field['name']}_o = current_{field['name']};")
    sv_code.append(f"")

    # LUT RAM Read/Write Control (Only possible when FSM is in RST state, using auto-incrementing lut_addr_reg)
    sv_code.append(f"    // LUT RAM Read/Write Control (Only possible when FSM is in RST state, using auto-incrementing lut_addr_reg)")
    sv_code.append(f"    assign lut_read_data_o = lut_ram[lut_addr_reg]; // External read output always reflects lut_addr_reg")
    sv_code.append(f"")
    sv_code.append(f"    always_ff @(posedge clk) begin")
    sv_code.append(f"        if (current_state_reg == RST && lut_wen_i) begin // Only allow write when in RST state and write enable is high")
    sv_code.append(f"            lut_ram[lut_addr_reg] <= lut_write_data_i; ") 
    sv_code.append(f"        end")
    sv_code.append(f"    end")
    sv_code.append("")
    
    sv_code.append(f"endmodule")

    with open(output_file, 'w') as f:
        f.write("\n".join(sv_code))
    logging.info(f"SystemVerilog FSM module generated successfully: {output_file}")


# --- Mermaid Diagram Generation (modified) ---
def generate_mermaid_fsm_diagram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a Mermaid State Diagram markdown string from FSM configuration.
    Reflects the active-high reset, special RST/IDLE states, and LUT-driven transitions
    using lut_addr_reg increment and 'eof' flag.
    - FSM starts sequence immediately after reset de-assertion.
    - LUT RAM read/write in RST state uses auto-incrementing lut_addr_reg.
    - Each command completion transitions to IDLE.
    - From IDLE, lut_addr_reg increments and then transitions to the next command.
    - Sequence automatically loops back to address 0x00 when 'eof' is detected during IDLE transition.
    """
    # 파일 존재 여부 확인
    if not os.path.exists(fsm_config_path):
        logging.error(f"Error: FSM configuration file not found at {fsm_config_path}")
        sys.exit(1)
    if not os.path.exists(lut_ram_config_path):
        logging.error(f"Error: LUT RAM data file not found at {lut_ram_config_path}")
        sys.exit(1)

    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = fsm_config['fsm_name']
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
        for out_name, out_val in state.get('outputs', {}).items():
            if out_name not in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] and \
               not out_name.startswith('current_'):
                output_desc.append(f"{out_name}={out_val}")
        
        if output_desc:
            mermaid_lines.append(f"    state {state_name} : {', '.join(output_desc)}")
        else:
            mermaid_lines.append(f"    state {state_name}")

    mermaid_lines.append("\n")

    # Initial Reset Sequence
    mermaid_lines.append(f"    [*] --> RST : Reset asserted (reset_i = 1) / lut_addr_reg, timers <= 0")
    mermaid_lines.append(f"    RST --> {lut_entries[0]['next_state']} : Reset de-asserted (reset_i = 0) / lut_addr_reg <= 0x00, timers init from LUT[0x00]")
    mermaid_lines.append(f"    RST : LUT RAM R/W enabled (using auto-incrementing lut_addr_reg with lut_wen_i/lut_rden_i)")

    # All sequence states transition to IDLE upon task completion
    for entry in lut_entries:
        current_state_for_cmd = entry['next_state']
        if current_state_for_cmd not in ["RST", "IDLE"]: # RST and IDLE are handled separately
            mermaid_lines.append(f"    {current_state_for_cmd} --> IDLE : Task Done && data_length_timer == 0")

    # IDLE state transitions based on repeat, exit_signal_i, and EOF
    mermaid_lines.append(f"    IDLE --> IDLE_Check_Repeat : Evaluate next sequence step")
    mermaid_lines.append(f"    IDLE_Check_Repeat : Check active_repeat_count, current_repeat_count, exit_signal_i, current_eof")

    # Transition for Repeat > 0
    mermaid_lines.append(f"    IDLE_Check_Repeat --> CURRENT_COMMAND : if active_repeat_count > 0 / active_repeat_count--, data_length_timer re-init")
    # Transition for Infinite Repeat + Exit Signal
    mermaid_lines.append(f"    IDLE_Check_Repeat --> NEXT_COMMAND : if current_repeat_count == 0 && exit_signal_i / lut_addr_reg++, timers init from LUT[new_addr]")
    # Transition for EOF = 1 (finished finite repeat or infinite repeat without exit_signal)
    mermaid_lines.append(f"    IDLE_Check_Repeat --> {lut_entries[0]['next_state']} : if current_eof == 1 / lut_addr_reg <= 0x00, timers init from LUT[0x00] (loop)")
    # Transition for EOF = 0 (and no repeat/exit condition met)
    mermaid_lines.append(f"    IDLE_Check_Repeat --> NEXT_COMMAND : if current_eof == 0 / lut_addr_reg++, timers init from LUT[new_addr]")

    # Ensure all distinct next states are defined
    for entry in lut_entries:
        if entry['next_state'] not in ["RST", "IDLE"]:
             mermaid_lines.append(f"    state {entry['next_state']}")

    # Default fallback to RST (e.g., if FSM enters an unexpected state)
    mermaid_lines.append(f"    default --> RST : Unexpected state / lut_addr_reg, timers <= 0")

    mermaid_lines.append("\n    note right of RST")
    mermaid_lines.append("        - **Reset (Active High)**: When `reset_i=1`, FSM enters `RST` state. All timers and `lut_addr_reg` initialize to `0x00`.")
    mermaid_lines.append("        - **LUT RAM Configuration (in RST)**: While in `RST` state, `lut_wen_i` asserted writes `lut_write_data_i` to `lut_ram[lut_addr_reg]`, and `lut_rden_i` asserted reads `lut_ram[lut_addr_reg]` to `lut_read_data_o`. For both R/W operations, `lut_addr_reg` automatically increments (`+1`) to sequential addresses. **External logic must manage when to de-assert `reset_i` after the LUT RAM is fully configured.**")
    mermaid_lines.append("        - **Automatic Sequence Start**: When `reset_i` falls to `0`, FSM transitions directly from `RST` to the state defined by `lut_ram[0x00]` (e.g., `PANEL_STABLE`). `lut_addr_reg` is reset to `0x00`, and `data_length_timer`, `active_repeat_count` are initialized from `lut_ram[0x00]` for the first command.")
    mermaid_lines.append("        - **Command State Execution**: Each command state (e.g., `PANEL_STABLE`, `BACK_BIAS`) performs its task. The FSM remains in this state until `data_length_timer` reaches `0` AND the associated `internal_task_done` (or equivalent) signal is asserted. Once both conditions are met, the FSM transitions to the **`IDLE` state**. At this point, `lut_addr_reg` still holds the address of the *just completed* command.")
    mermaid_lines.append("        - **`IDLE` State Logic (Advanced)**:")
    mermaid_lines.append("            - **Repeat Check**: If `active_repeat_count` is greater than `0`, the FSM decrements `active_repeat_count` and immediately transitions back to the *same* command state (`lut_addr_reg` does not change). `data_length_timer` is re-initialized from `current_data_length`.")
    mermaid_lines.append("            - **Infinite Repeat with Exit**: If `current_repeat_count` (from LUT) is `0` (indicating infinite repeat) AND `exit_signal_i` is asserted, the FSM proceeds to the *next* command in the sequence (`lut_addr_reg` increments). `data_length_timer` and `active_repeat_count` are initialized from the *new* LUT entry.")
    mermaid_lines.append("            - **End of Sequence (`eof=1`)**: If the *current* command (which just completed) had `current_eof = 1` (and no repeat/exit condition was met), the FSM **loops back** to the beginning: `lut_addr_reg` is reset to `0x00`, and the FSM transitions to the state defined by `lut_ram[0x00]`. Timers are re-initialized from `lut_ram[0x00]`.")
    mermaid_lines.append("            - **Normal Progression (`eof=0`)**: If none of the above conditions are met, the FSM proceeds to the *next* command in the sequence: `lut_addr_reg` increments (`+1`), and the FSM transitions to the state defined by `lut_ram[new_lut_addr_reg]`. Timers are re-initialized from the *new* LUT entry.")
    mermaid_lines.append("        - **`sequence_done_o`**: This output is asserted for one cycle when the FSM is in `IDLE`, the *previous* command indicated `eof=1`, and there are no active repeats (both `active_repeat_count == 0` and `current_repeat_count == 0`). It signals the completion of one full sequence loop.")
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