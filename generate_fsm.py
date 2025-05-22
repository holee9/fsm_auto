import yaml
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class FsmSimulator:
    """
    Python-based FSM simulator for pre-FPGA verification.
    Reads FSM structure and LUT RAM data from YAML files.
    """
    def __init__(self, fsm_config_path, lut_ram_config_path):
        with open(fsm_config_path, 'r') as f:
            self.fsm_config = yaml.safe_load(f)
        
        with open(lut_ram_config_path, 'r') as f:
            self.lut_ram_config = yaml.safe_load(f)

        self.fsm_name = self.fsm_config['fsm_name']
        self.state_encoding_width = self.fsm_config['state_encoding_width']
        self.inputs_def = self.fsm_config['inputs']
        self.outputs_def = self.fsm_config['outputs']

        # Map state names to their objects
        self.states = {}
        for s_data in self.fsm_config['states']:
            self.states[s_data['name']] = {
                'name': s_data['name'],
                'outputs': s_data['outputs'],
                'transitions': s_data.get('transitions', [])
            }
        
        self.current_state_name = 'IDLE' # Initial state
        
        # Initialize LUT RAM model
        self.lut_ram_model = self._initialize_lut_ram_model()

        # Initialize current inputs and outputs
        self.current_inputs = {inp['name']: 0 for inp in self.inputs_def}
        self.current_outputs = {out['name']: '0' for out in self.outputs_def} # Use string for bit values
        
        # Initialize parameter registers
        self.current_param_values = {field['name']: 0 for field in self.lut_ram_config['lut_ram_config']['param_fields']}

        logging.info(f"FSM Simulator '{self.fsm_name}' initialized. Current state: {self.current_state_name}")

    def _initialize_lut_ram_model(self):
        """Creates an in-memory representation of the LUT RAM."""
        addr_width = self.lut_ram_config['lut_ram_config']['address_width']
        ram_depth = 2**addr_width
        
        ram_model = {i: {'next_state': 'IDLE', 'params': {field['name']: 0 for field in self.lut_ram_config['lut_ram_config']['param_fields']}}
                     for i in range(ram_depth)}
        
        for entry in self.lut_ram_config['lut_entries']:
            addr = entry['address']
            if addr < ram_depth:
                params = {field['name']: entry.get(field['name'], 0) for field in self.lut_ram_config['lut_ram_config']['param_fields']}
                ram_model[addr] = {
                    'next_state': entry['next_state'],
                    'params': params
                }
            else:
                logging.warning(f"LUT RAM load: Address {addr} out of bounds (max {ram_depth-1}).")
        logging.info("FSM LUT RAM model initialized.")
        return ram_model

    def set_inputs(self, **kwargs):
        """Set values for FSM inputs."""
        for key, value in kwargs.items():
            if key in self.current_inputs:
                self.current_inputs[key] = value
            else:
                logging.warning(f"Input '{key}' not defined in FSM configuration.")

    def _evaluate_condition(self, condition_expr):
        """Evaluates a condition string against current inputs."""
        # Simple evaluation. For complex conditions, a more robust parser might be needed.
        # Ensure input values are properly cast for evaluation (e.g., '1' becomes True)
        eval_scope = {}
        for inp_name, inp_val in self.current_inputs.items():
            # Convert '0'/'1' string to False/True boolean for evaluation
            if isinstance(inp_val, str) and (inp_val == '0' or inp_val == '1'):
                eval_scope[inp_name] = (inp_val == '1')
            else:
                eval_scope[inp_name] = inp_val
        
        try:
            return eval(condition_expr, {}, eval_scope)
        except Exception as e:
            logging.error(f"Error evaluating condition '{condition_expr}': {e}. Inputs: {self.current_inputs}")
            return False # Default to false on error

    def step(self):
        """Simulates one clock cycle of the FSM."""
        logging.info(f"\n--- FSM Step (Current State: {self.current_state_name}) ---")
        logging.info(f"Inputs: {self.current_inputs}")

        current_state_data = self.states[self.current_state_name]
        next_state_name = self.current_state_name # Default next state

        # Determine next state logic
        if self.current_state_name == "IDLE":
            cmd_id = self.current_inputs.get("command_id_i", 0)
            if cmd_id in self.lut_ram_model:
                lut_entry = self.lut_ram_model[cmd_id]
                next_state_name = lut_entry['next_state']
                # Update parameter registers when leaving IDLE
                self.current_param_values = lut_entry['params']
                logging.info(f"IDLE: LUT RAM lookup for cmd_id={cmd_id} -> Next: {next_state_name}, Params: {self.current_param_values}")
            else:
                logging.warning(f"IDLE: Invalid command_id_i {cmd_id}. Staying IDLE.")
                next_state_name = "IDLE" # Fallback if command ID is not in LUT RAM
        else:
            # For non-IDLE states, check transitions defined in fsm_config.yaml
            transition_found = False
            for transition in current_state_data['transitions']:
                condition_expr = transition['condition']
                if self._evaluate_condition(condition_expr):
                    next_state_name = transition['next_state']
                    transition_found = True
                    logging.info(f"Transition from {self.current_state_name} on condition '{condition_expr}' -> {next_state_name}")
                    break
            
            if not transition_found:
                # This should ideally not happen if 'True' condition is last
                logging.warning(f"No transition met for state {self.current_state_name}. Staying in current state.")
                next_state_name = self.current_state_name # Stay in current state as default

        # Update outputs based on current state (Moore-like outputs)
        # Handle current_state_o and busy_o explicitly
        self.current_outputs['current_state_o'] = self.get_state_encoding(self.current_state_name)
        self.current_outputs['busy_o'] = '1' if self.current_state_name != 'IDLE' else '0'
        # Example for sequence_done_o (adjust based on your definition of "sequence done")
        self.current_outputs['sequence_done_o'] = '1' if self.current_state_name == 'STATE_G' and next_state_name == 'IDLE' else '0' # Example

        # Set specific outputs for the current state (from fsm_config.yaml)
        for output_name, output_value in current_state_data['outputs'].items():
            if output_name in self.current_outputs: # Avoid overwriting hardcoded outputs
                self.current_outputs[output_name] = output_value
            else:
                logging.warning(f"Output '{output_name}' in FSM config is not defined in FSM outputs.")

        # Assign parameter outputs from current_param_values
        for param_name, param_val in self.current_param_values.items():
            output_key = f"current_{param_name}_o"
            if output_key in self.current_outputs:
                # Convert integer param_val to string suitable for HDL (e.g., "8'h0A")
                field_width = next(f['width'] for f in self.lut_ram_config['lut_ram_config']['param_fields'] if f['name'] == param_name)
                self.current_outputs[output_key] = f"{field_width}'d{param_val}" # Using decimal for simplicity in simulation

        logging.info(f"Outputs: {self.current_outputs}")

        # Transition to next state
        self.current_state_name = next_state_name
        logging.info(f"New State: {self.current_state_name}")
        
        return self.current_outputs, self.current_state_name

    def get_state_encoding(self, state_name):
        """Returns the binary encoding string for a given state name."""
        state_names_ordered = [s_data['name'] for s_data in self.fsm_config['states']]
        try:
            idx = state_names_ordered.index(state_name)
            return bin(idx)[2:].zfill(self.state_encoding_width)
        except ValueError:
            logging.error(f"Attempted to encode unknown state: {state_name}")
            return '?' * self.state_encoding_width # Indicate error


def generate_verilog_fsm_with_lut_ram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a Verilog HDL module for the FSM with LUT RAM.
    """
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = fsm_config['fsm_name']
    state_width = fsm_config['state_encoding_width']
    inputs = fsm_config['inputs']
    outputs = fsm_config['outputs']
    states_data = fsm_config['states']
    
    # LUT RAM configuration
    lut_address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    lut_entries = lut_ram_config['lut_entries']
    
    # Calculate total parameter width and create bit ranges for concatenation
    total_param_width = sum(field['width'] for field in param_fields)
    param_bit_ranges = {} # { 'param_name': (start_bit, end_bit) }
    current_bit_pos = 0
    for field in param_fields:
        param_bit_ranges[field['name']] = (current_bit_pos, current_bit_pos + field['width'] - 1)
        current_bit_pos += field['width']
    
    lut_data_width = state_width + total_param_width # Total width of data stored in LUT RAM entry

    # Map state names to their binary encodings
    state_encoding = {}
    for i, state_data in enumerate(states_data):
        state_name = state_data['name']
        state_encoding[state_name] = f"{state_width}'b{bin(i)[2:].zfill(state_width)}"

    verilog_code = []
    verilog_code.append(f"module {fsm_name} (")
    
    # Port declarations
    port_declarations = []
    for p in inputs:
        if 'std_logic_vector' in p['type']:
            width = p['type'].replace('std_logic_vector(', '').replace(')', '')
            port_declarations.append(f"    input logic {width} {p['name']}")
        else:
            port_declarations.append(f"    input logic {p['name']}")
    for p in outputs:
        if 'std_logic_vector' in p['type']:
            width = p['type'].replace('std_logic_vector(', '').replace(')', '')
            port_declarations.append(f"    output logic {width} {p['name']}")
        else:
            port_declarations.append(f"    output logic {p['name']}")
    verilog_code.append(",\n".join(port_declarations))
    verilog_code.append(");\n")

    verilog_code.append(f"    // --- State Encoding Parameters ---")
    for state_name, encoding in state_encoding.items():
        verilog_code.append(f"    localparam {state_name} = {encoding};")
    verilog_code.append("\n")

    verilog_code.append(f"    // --- State Registers ---")
    verilog_code.append(f"    logic [{state_width-1}:0] current_state;")
    verilog_code.append(f"    logic [{state_width-1}:0] next_state;\n")
    
    verilog_code.append(f"    // --- Parameter Registers (updated from LUT RAM) ---")
    verilog_code.append(f"    logic [{total_param_width-1}:0] current_param_combined_reg; // Holds combined parameter value")
    # Individual parameter registers
    for field in param_fields:
        verilog_code.append(f"    logic [{field['width']-1}:0] param_{field['name']}_reg;")
    verilog_code.append("\n")


    # --- LUT RAM Implementation (Behavioral, will map to BRAM/LUT-RAM) ---
    verilog_code.append(f"    // --- FSM LUT RAM (Behavioral Model - will be synthesized to BRAM/LUT-RAM) ---")
    verilog_code.append(f"    // Each entry stores: {{next_state_encoding, combined_param_value}}")
    verilog_code.append(f"    localparam int LUT_RAM_DEPTH = {2**lut_address_width};")
    verilog_code.append(f"    logic [{lut_data_width-1}:0] lut_ram [LUT_RAM_DEPTH-1:0];\n")
    
    verilog_code.append(f"    initial begin")
    # Initialize RAM content from lut_entries
    for i in range(2**lut_address_width):
        found_entry = None
        for entry in lut_entries:
            if entry['address'] == i:
                found_entry = entry
                break
        
        next_s_enc_val = state_encoding['IDLE'] # Default to IDLE
        param_parts_val = []
        for field in param_fields:
            param_parts_val.append(f"{field['width']}'d0") # Default to 0 for all params
        
        if found_entry:
            next_s_enc_val = state_encoding.get(found_entry['next_state'], state_encoding['IDLE']) # Use IDLE if state not found
            param_parts_val = []
            for field in param_fields:
                param_val = found_entry.get(field['name'], 0) # Use 0 if param not specified
                param_parts_val.append(f"{field['width']}'d{param_val}")
        
        combined_param_str = "{" + ", ".join(param_parts_val) + "}"
        verilog_code.append(f"        lut_ram[{i}] = {{{next_s_enc_val}, {combined_param_str}}};")
    verilog_code.append(f"    end\n")

    # Read from RAM based on command_id_i
    verilog_code.append(f"    logic [{state_width-1}:0] lut_next_state_read; ")
    verilog_code.append(f"    logic [{total_param_width-1}:0] lut_param_read; ")
    verilog_code.append(f"    assign {{lut_next_state_read, lut_param_read}} = lut_ram[command_id_i];\n")

    verilog_code.append(f"    // --- Synchronous State Logic ---")
    verilog_code.append(f"    always_ff @(posedge clk or negedge reset_n) begin")
    verilog_code.append(f"        if (!reset_n) begin")
    verilog_code.append(f"            current_state <= IDLE;")
    verilog_code.append(f"            current_param_combined_reg <= '0;")
    for field in param_fields:
        verilog_code.append(f"            param_{field['name']}_reg <= '0;")
    verilog_code.append(f"        end else begin")
    verilog_code.append(f"            current_state <= next_state;")
    verilog_code.append(f"            if (current_state == IDLE) begin") # Update parameters when transitioning FROM IDLE
    verilog_code.append(f"                current_param_combined_reg <= lut_param_read;")
    for field in param_fields:
        start_bit, end_bit = param_bit_ranges[field['name']]
        verilog_code.append(f"                param_{field['name']}_reg <= lut_param_read[{end_bit}:{start_bit}];")
    verilog_code.append(f"            end")
    verilog_code.append(f"        end")
    verilog_code.append(f"    end\n")

    verilog_code.append(f"    // --- Next State Logic (Combinational) ---")
    verilog_code.append(f"    always_comb begin")
    verilog_code.append(f"        next_state = current_state; // Default to current state (safety)")
    verilog_code.append(f"        case (current_state)")
    
    for state in states_data:
        state_name = state['name']
        verilog_code.append(f"            {state_name}: begin")
        
        if state_name == "IDLE":
            verilog_code.append(f"                next_state = lut_next_state_read; // Determined by LUT RAM lookup")
        else:
            # For non-IDLE states, check transitions. All end with going to IDLE.
            explicit_idle_transition_found = False
            for transition in state['transitions']:
                condition = transition['condition']
                next_s = transition['next_state']
                if next_s == "IDLE": # Check if the transition directly leads to IDLE
                    explicit_idle_transition_found = True
                verilog_code.append(f"                if ({condition}) begin")
                verilog_code.append(f"                    next_state = {next_s};")
                verilog_code.append(f"                end")
            
            # If no explicit 'always go to IDLE' transition, add it as a final fallback
            # This ensures all task states eventually return to IDLE
            if not explicit_idle_transition_found:
                 verilog_code.append(f"                // Default: Go to IDLE (Task Completion)")
                 verilog_code.append(f"                next_state = IDLE;")

        verilog_code.append(f"            end")
    
    verilog_code.append(f"            default: begin")
    verilog_code.append(f"                next_state = IDLE; // Fallback for unknown states")
    verilog_code.append(f"            end")

    verilog_code.append(f"        endcase")
    verilog_code.append(f"    end\n")

    verilog_code.append(f"    // --- Output Logic (Combinational) ---")
    verilog_code.append(f"    always_comb begin")
    
    # Default outputs
    for out_port in outputs:
        # Special handling for current_state_o, busy_o, sequence_done_o
        if out_port['name'] == 'current_state_o':
            verilog_code.append(f"        {out_port['name']} = current_state;")
        elif out_port['name'] == 'busy_o':
            verilog_code.append(f"        {out_port['name']} = (current_state != IDLE);")
        elif out_port['name'] == 'sequence_done_o':
            # Example: Signal sequence_done_o when transitioning FROM the last state (STATE_G) to IDLE
            verilog_code.append(f"        {out_port['name']} = (current_state == STATE_G && next_state == IDLE);")
        elif out_port['name'].startswith('current_') and out_port['name'].endswith('_o'):
            # Map parameter outputs directly to their corresponding registers
            param_name = out_port['name'].replace('current_', '').replace('_o', '')
            verilog_code.append(f"        {out_port['name']} = param_{param_name}_reg;")
        # Generic defaults for other outputs if not specified in state configs
        elif 'std_logic_vector' in out_port['type']:
            verilog_code.append(f"        {out_port['name']} = '0; // Default to all zeros")
        else:
            verilog_code.append(f"        {out_port['name']} = '0;")
    
    verilog_code.append(f"        case (current_state)")
    for state in states_data:
        state_name = state['name']
        verilog_code.append(f"            {state_name}: begin")
        for output_name, output_value in state['outputs'].items():
            # Only generate if not one of the specially handled outputs above
            if output_name not in ['current_state_o', 'busy_o', 'sequence_done_o'] and \
               not (output_name.startswith('current_') and output_name.endswith('_o')):
                verilog_code.append(f"                {output_name} = {output_value};")
        verilog_code.append(f"            end")
    verilog_code.append(f"            default: begin")
    verilog_code.append(f"                // All outputs default to 0 for unknown states (handled above)")
    verilog_code.append(f"            end")
    verilog_code.append(f"        endcase")
    verilog_code.append(f"    end\n")

    verilog_code.append(f"endmodule")

    with open(output_file, 'w') as f:
        f.write("\n".join(verilog_code))

# --- Main Execution ---
if __name__ == "__main__":
    # 1. Create dummy YAML config files (for testing this script directly)
    # In a real project, these files would already exist.
    with open("fsm_config.yaml", "w") as f:
        f.write("""
fsm_name: sequencer_fsm
state_encoding_width: 3

inputs:
  - name: clk
    type: std_logic
  - name: reset_n
    type: std_logic
  - name: command_id_i
    type: std_logic_vector(7 downto 0)

  - name: task_done_i
    type: std_logic
  - name: adc_ready_i
    type: std_logic
  - name: sensor_stable_i
    type: std_logic
  - name: aed_detected_i
    type: std_logic

outputs:
  - name: current_state_o
    type: std_logic_vector(2 downto 0)
  - name: busy_o
    type: std_logic
  - name: sequence_done_o
    type: std_logic

  - name: current_repeat_count_o
    type: std_logic_vector(7 downto 0)
  - name: current_data_length_o
    type: std_logic_vector(15 downto 0)
  - name: current_eof_o
    type: std_logic
  - name: current_sof_o
    type: std_logic

states:
  - name: IDLE
    outputs: {busy_o: '0', sequence_done_o: '0', current_repeat_count_o: "8'h00", current_data_length_o: "16'h0000", current_eof_o: '0', current_sof_o: '0'}
    transitions: []

  - name: RST
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "task_done_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: RST

  - name: BACK_BIAS
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "task_done_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: BACK_BIAS

  - name: FLUSH
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "task_done_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: FLUSH

  - name: EXPOSE_TIME
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "task_done_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: EXPOSE_TIME

  - name: READOUT
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "task_done_i == '1' and adc_ready_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: READOUT

  - name: AED_DETECT
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "aed_detected_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: AED_DETECT

  - name: PANEL_STABLE
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "sensor_stable_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: PANEL_STABLE
""")

    with open("fsm_lut_ram_data.yaml", "w") as f:
        f.write("""
lut_ram_config:
  address_width: 8
  param_fields:
    - name: repeat_count
      width: 8
    - name: data_length
      width: 16
    - name: eof
      width: 1
    - name: sof
      width: 1

lut_entries:
  - address: 0x00
    next_state: RST
    repeat_count: 1
    data_length: 1024
    eof: 0
    sof: 1
  - address: 0x01
    next_state: FLUSH
    repeat_count: 1
    data_length: 0
    eof: 0
    sof: 0
  - address: 0x02
    next_state: AED_DETECT
    repeat_count: 1
    data_length: 0
    eof: 0
    sof: 0
  - address: 0x03
    next_state: EXPOSE_TIME
    repeat_count: 1
    data_length: 0
    eof: 1
    sof: 0
  - address: 0xFF
    next_state: IDLE
    repeat_count: 0
    data_length: 0
    eof: 0
    sof: 0
""")

    # 2. Run Python simulation
    print("Starting FSM Simulation...")
    simulator = FsmSimulator("fsm_config.yaml", "fsm_lut_ram_data.yaml")

    # Simulation Sequence Example
    # Step 1: Send command_id_i = 0x00 (Go to RST from IDLE)
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: IDLE, Next: RST, Params updated
    
    # Step 2: RST state, task_done_i is 0, so stay in RST
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: RST, Next: RST

    # Step 3: RST state, task_done_i is 1, so go to IDLE
    simulator.set_inputs(command_id_i=0x00, task_done_i='1', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: RST, Next: IDLE

    # Step 4: Send command_id_i = 0x01 (Go to FLUSH from IDLE)
    simulator.set_inputs(command_id_i=0x01, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: IDLE, Next: FLUSH, Params updated

    # Step 5: FLUSH state, task_done_i is 1, so go to IDLE
    simulator.set_inputs(command_id_i=0x01, task_done_i='1', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: FLUSH, Next: IDLE

    # Step 6: Send command_id_i = 0xFF (Invalid/No-op command, stay IDLE)
    simulator.set_inputs(command_id_i=0xFF, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0')
    simulator.step() # Current: IDLE, Next: IDLE

    print("\nFSM Simulation Complete.")

    # 3. Generate Verilog HDL code
    print("\nGenerating Verilog HDL code...")
    generate_verilog_fsm_with_lut_ram("fsm_config.yaml", "fsm_lut_ram_data.yaml", "sequencer_fsm.sv")
    print("Verilog FSM with LUT RAM code generated successfully: sequencer_fsm.sv")

    # # Clean up dummy config files
    # import os
    # os.remove("fsm_config.yaml")
    # os.remove("fsm_lut_ram_data.yaml")
    # print("Dummy config files removed.")

