import yaml
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_fsm_with_lut_ram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a SystemVerilog FSM module based on LUT RAM.
    - RST (state) is special for initialization.
    - FSM starts sequence immediately after reset de-assertion.
    - LUT RAM read/write in RST state uses auto-incrementing lut_addr_reg.
    - Each sequence command completion transitions to IDLE.
    - From IDLE, lut_addr_reg increments, and then transitions to the next command.
    - Sequence automatically loops back to address 0x00 when 'eof' is detected during IDLE transition.
    """
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
    
    # Add LUT RAM specific inputs (fixed width after calculation)
    input_ports.append(f"    input logic lut_wen_i; // LUT Write Enable (active high, only in RST state)")
    input_ports.append(f"    input logic [{lut_data_width-1}:0] lut_write_data_i; // Data to write to LUT RAM")
    input_ports.append(f"    input logic lut_rden_i; // LUT Read Enable (active high, only in RST state)") 

    # Other non-control inputs (e.g., internal task completion signals)
    for inp in inputs:
        # Skip control signals already handled or removed
        if inp['name'] in ['clk', 'reset_i', 'lut_wen_i', 'lut_write_data_i', 'lut_rden_i']:
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
    sv_code.append(f"    // Simulated internal task completion signals")
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
    sv_code.append(f"        end else begin")
    sv_code.append(f"            case (current_state_reg)")
    sv_code.append(f"                RST: begin")
    sv_code.append(f"                    // Reset de-asserted: transition to the first sequence state (from LUT[0x00])")
    sv_code.append(f"                    current_state_reg <= lut_ram[{lut_address_width}'h00][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; ")
    sv_code.append(f"                    lut_addr_reg <= {lut_address_width}'h00; // Reset address for sequence execution")
    sv_code.append(f"                end")
    sv_code.append(f"                IDLE: begin")
    sv_code.append(f"                    // In IDLE, increment lut_addr_reg and determine next state")
    sv_code.append(f"                    if (current_eof) begin // If the *current* command (that just completed) was EOF")
    sv_code.append(f"                        lut_addr_reg <= {lut_address_width}'h00; // Loop back to start of sequence")
    sv_code.append(f"                        current_state_reg <= lut_ram[{lut_address_width}'h00][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; // Go to state from LUT[0x00]")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        lut_addr_reg <= lut_addr_reg + 1; // Increment for the next command")
    sv_code.append(f"                        // In the next cycle, lut_addr_reg will be updated, so current_state_reg will then read lut_ram[new_lut_addr_reg]")
    sv_code.append(f"                        current_state_reg <= lut_ram[lut_addr_reg + 1][{next_state_start_bit+state_width-1}:{next_state_start_bit}]; // Go to next state from LUT for (current lut_addr_reg + 1)")
    sv_code.append(f"                    end")
    sv_code.append(f"                end") 
    
    # All non-RST, non-IDLE states transition to IDLE upon task completion
    for state in states_data:
        state_name = state['name']
        if state_name != "RST" and state_name != "IDLE": 
            completion_signal = ""
            if state_name == "PANEL_STABLE": completion_signal = "internal_sensor_stable"
            elif state_name == "BACK_BIAS": completion_signal = "internal_task_done"
            elif state_name == "FLUSH": completion_signal = "internal_task_done"
            elif state_name == "EXPOSE_TIME": completion_signal = "internal_task_done"
            elif state_name == "READOUT": completion_signal = "(internal_task_done && internal_adc_ready)"
            elif state_name == "AED_DETECT": completion_signal = "internal_aed_detected" # AED_DETECT is still defined in fsm_config.yaml, but not in lut_entries for this sequence
            
            if completion_signal:
                sv_code.append(f"                {state_name}: begin")
                sv_code.append(f"                    if ({completion_signal}) begin")
                sv_code.append(f"                        current_state_reg <= IDLE; // Task done, go to IDLE to update address and transition")
                sv_code.append(f"                    end else begin")
                sv_code.append(f"                        current_state_reg <= {state_name}; // Stay in current state")
                sv_code.append(f"                    end")
                # lut_addr_reg stays the same until IDLE state processes it
                sv_code.append(f"                    lut_addr_reg <= lut_addr_reg; ") 
                sv_code.append(f"                end")
    sv_code.append(f"                default: begin")
    sv_code.append(f"                    current_state_reg <= RST; // Fallback to RST on unexpected state")
    sv_code.append(f"                    lut_addr_reg <= {lut_address_width}'h00;") 
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
    current_bit_pos = 0
    # Assign actual parameters including 'eof' and 'sof'
    for field in reversed(param_fields): # Iterate in reverse to correctly build from LSB (assuming param_fields are LSB to MSB)
        sv_code.append(f"        current_{field['name']} = lut_read_current_addr_internal[{current_bit_pos + field['width']-1}:{current_bit_pos}];")
        current_bit_pos += field['width']
    sv_code.append(f"    end")
    sv_code.append(f"")
    
    # --- Internal Signal Generation (Simulated for verification) ---
    # This block simulates task completion signals, not part of the FSM itself.
    sv_code.append(f"    // Internal Signal Generation Logic (Simulated for verification)")
    sv_code.append(f"    logic [7:0] task_timer;")
    sv_code.append(f"    always_ff @(posedge clk or posedge reset_i) begin // Active-High Reset")
    sv_code.append(f"        if (reset_i) begin // Reset asserted")
    sv_code.append(f"            task_timer <= '0;")
    sv_code.append(f"            internal_task_done <= 1'b0;")
    sv_code.append(f"            internal_adc_ready <= 1'b0;")
    sv_code.append(f"            internal_sensor_stable <= 1'b0;")
    sv_code.append(f"            internal_aed_detected <= 1'b0;")
    sv_code.append(f"        end else begin")
    sv_code.append(f"            internal_task_done <= 1'b0;") 
    sv_code.append(f"            internal_adc_ready <= 1'b0;")
    sv_code.append(f"            internal_sensor_stable <= 1'b0;")
    sv_code.append(f"            internal_aed_detected <= 1'b0;")
    
    sv_code.append(f"            case (current_state_reg)")
    sv_code.append(f"                RST, BACK_BIAS, FLUSH, EXPOSE_TIME: begin") 
    sv_code.append(f"                    if (task_timer >= 8'd20) begin")
    sv_code.append(f"                        internal_task_done <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                PANEL_STABLE: begin")
    sv_code.append(f"                    if (task_timer >= 8'd15) begin")
    sv_code.append(f"                        internal_sensor_stable <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                READOUT: begin")
    sv_code.append(f"                    if (task_timer >= 8'd50) begin")
    sv_code.append(f"                        internal_task_done <= 1'b1;")
    sv_code.append(f"                        internal_adc_ready <= 1'b1;") # ADC ready signal might be needed for READOUT
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    else if (task_timer >= 8'd40) begin") # Example: ADC is ready 10 cycles before task done
    sv_code.append(f"                        internal_adc_ready <= 1'b1;")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        internal_adc_ready <= 1'b0;")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                AED_DETECT: begin") # Still kept in fsm_config but not in this sequence, timer will reset if FSM somehow hits this.
    sv_code.append(f"                    if (task_timer >= 8'd10) begin")
    sv_code.append(f"                        internal_aed_detected <= 1'b1;")
    sv_code.append(f"                        task_timer <= '0;")
    sv_code.append(f"                    end else begin")
    sv_code.append(f"                        task_timer <= task_timer + 1;")
    sv_code.append(f"                    end")
    sv_code.append(f"                end")
    sv_code.append(f"                default: task_timer <= '0;") # IDLE will also reset timer, or keep it low
    sv_code.append(f"            endcase")
    sv_code.append(f"        end")
    sv_code.append(f"    end")
    sv_code.append(f"")
    
    # FSM Outputs
    sv_code.append(f"    // FSM Outputs Assignments")
    sv_code.append(f"    assign current_state_o = current_state_reg;")
    sv_code.append(f"    // Busy if not in RST or IDLE. In this model, IDLE is a transient state between commands, so FSM is always 'busy' once sequence starts.")
    sv_code.append(f"    assign busy_o = (current_state_reg != RST); ") 
    
    # sequence_done_o assertion logic: asserted when in IDLE and the command just completed was EOF
    sv_code.append(f"    // sequence_done_o is asserted when in IDLE and the command just completed was EOF (current_eof == 1'b1).")
    sv_code.append(f"    // It will be asserted for one cycle before looping back to the first command.")
    sv_code.append(f"    assign sequence_done_o = (current_state_reg == IDLE && current_eof == 1'b1);") 

    # Outputs for FSM specific control (derived from `fsm_config.yaml` outputs)
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] or out['name'].startswith('current_'):
            continue # These are handled separately

        # Find the state where this output is defined and its value
        # This assumes outputs are directly mapped from current_state_reg and are mutually exclusive
        output_cases = []
        for state in states_data:
            if 'outputs' in state and out['name'] in state['outputs']:
                output_cases.append(f"                {state['name']}: {state['outputs'][out['name']]}'b1;")
        
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
    mermaid_lines.append(f"    [*] --> RST : Reset asserted (reset_i = 1) / lut_addr_reg <= 0x00")
    mermaid_lines.append(f"    RST --> {lut_entries[0]['next_state']} : Reset de-asserted (reset_i = 0 falling edge) / lut_addr_reg <= 0x00 (re-init for seq)")
    mermaid_lines.append(f"    RST : LUT RAM R/W enabled (using auto-incrementing lut_addr_reg with lut_wen_i/lut_rden_i)")

    # All sequence states transition to IDLE upon task completion
    for entry in lut_entries:
        current_state_for_cmd = entry['next_state']
        if current_state_for_cmd not in ["RST", "IDLE"]: # RST and IDLE are handled separately
            mermaid_lines.append(f"    {current_state_for_cmd} --> IDLE : Task Done")

    # IDLE state transitions based on EOF
    # IDLE state has two possible transitions based on the 'eof' bit of the *current* lut_addr_reg after increment
    mermaid_lines.append(f"    IDLE --> State_Evaluation_in_IDLE : lut_addr_reg increments (+1)")
    
    # Transition for EOF = 1
    # This refers to the next state after the increment.
    # The 'eof' bit is from the *current* command (before increment in Verilog, but after the state transition logic)
    # The mermaid needs to represent the logic: if lut_ram[old_addr].eof == 1, then new_addr = 0x00.
    # If lut_ram[old_addr].eof == 0, then new_addr = old_addr + 1.
    
    mermaid_lines.append(f"    State_Evaluation_in_IDLE --> {lut_entries[0]['next_state']} : if current_eof == 1 / lut_addr_reg <= 0x00 (loop)")
    
    # Transition for EOF = 0
    # Iterate through all entries to find the *next* state if EOF was 0
    for i in range(len(lut_entries)):
        current_entry = lut_entries[i]
        if current_entry['eof'] == 0: # If this command is NOT the end of sequence
            next_addr_in_sequence = current_entry['address'] + 1
            next_state_obj = next((e for e in lut_entries if e['address'] == next_addr_in_sequence), None)
            
            if next_state_obj:
                mermaid_lines.append(f"    State_Evaluation_in_IDLE --> {next_state_obj['next_state']} : if current_eof == 0 (for command at {hex(current_entry['address'])})")
            # else: If no next_state_obj, it's an undefined path, handled by default below

    # Default fallback to RST (e.g., if FSM enters an unexpected state)
    mermaid_lines.append(f"    [*] --> RST : Unexpected state / lut_addr_reg <= 0x00")

    mermaid_lines.append("\n    note right of RST")
    mermaid_lines.append("        - **Reset (Active High)**: When `reset_i=1`, FSM enters `RST` state. `lut_addr_reg` initializes to `0x00`.")
    mermaid_lines.append("        - **LUT RAM Configuration (in RST)**: While in `RST` state, `lut_wen_i` asserted writes `lut_write_data_i` to `lut_ram[lut_addr_reg]`, and `lut_rden_i` asserted reads `lut_ram[lut_addr_reg]` to `lut_read_data_o`. For both R/W operations, `lut_addr_reg` automatically increments (`+1`) to sequential addresses. **External logic must manage when to de-assert `reset_i` after the LUT RAM is fully configured.**")
    mermaid_lines.append("        - **Automatic Sequence Start**: When `reset_i` falls to `0`, FSM transitions directly from `RST` to the state defined by `lut_ram[0x00]` (e.g., `PANEL_STABLE`). `lut_addr_reg` is reset to `0x00` at this point to start the sequence from the beginning.")
    mermaid_lines.append("        - **Step-by-Step Sequence Execution**: Each command state (e.g., `PANEL_STABLE`, `BACK_BIAS`) performs its task. Upon task completion, the FSM always transitions to the **`IDLE` state**. At this point, `lut_addr_reg` still holds the address of the *just completed* command.")
    mermaid_lines.append("        - **`IDLE` State Logic**: When in `IDLE`, the `lut_addr_reg` is first **incremented by `+1`**. Then, the **`eof` bit of the *previously completed command* (i.e., `current_eof` which reflects the LUT entry before the increment)** is checked:")
    mermaid_lines.append("            - If `current_eof = 1` (meaning the last command was the end of the sequence), the FSM **loops back** to the beginning: `lut_addr_reg` is reset to `0x00`, and the FSM transitions to the state defined by `lut_ram[0x00]`.")
    mermaid_lines.append("            - If `current_eof = 0` (meaning there are more commands in the sequence), the FSM transitions to the state defined by `lut_ram[new_lut_addr_reg]` (the newly incremented address).")
    mermaid_lines.append("        - **`sequence_done_o`**: This output is asserted for one cycle when the FSM is in `IDLE` and the *previous* command indicated `eof=1`. It signals the completion of one full sequence loop.")
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