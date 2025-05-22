import yaml
import logging
import os

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
        
        # Initialize LUT RAM model (simulated)
        self.lut_ram_model = self._initialize_lut_ram_model()

        # Initialize current inputs and outputs
        self.current_inputs = {inp['name']: 0 for inp in self.inputs_def}
        self.current_outputs = {out['name']: '0' for out in self.outputs_def} # Use string for bit values
        
        # Initialize parameter registers (will be updated from LUT RAM)
        self.current_param_values = {field['name']: 0 for field in self.lut_ram_config['lut_ram_config']['param_fields']}

        # Add internal state for LUT RAM address in simulator (matches Verilog)
        self.lut_current_addr = 0 

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
        eval_scope = {}
        for inp_name, inp_val in self.current_inputs.items():
            # Convert '0'/'1' string to False/True boolean for evaluation
            if isinstance(inp_val, str) and (inp_val == '0' or inp_val == '1'):
                eval_scope[inp_name] = (inp_val == '1')
            else:
                eval_scope[inp_name] = inp_val
        
        try:
            # Replace '&&' with 'and' for Python evaluation
            condition_expr_py = condition_expr.replace('&&', 'and').replace('||', 'or')
            return eval(condition_expr_py, {}, eval_scope)
        except Exception as e:
            logging.error(f"Error evaluating condition '{condition_expr}': {e}. Inputs: {self.current_inputs}")
            return False # Default to false on error

    def step(self):
        """Simulates one clock cycle of the FSM."""
        logging.info(f"\n--- FSM Step (Current State: {self.current_state_name}) ---")
        logging.info(f"Inputs: {self.current_inputs}")

        current_state_data = self.states[self.current_state_name]
        next_state_name = self.current_state_name # Default next state

        # LUT RAM R/W Logic controlled by RST state
        if self.current_state_name == "RST":
            if self.current_inputs.get('lut_access_en_i') == '1':
                if self.current_inputs.get('lut_read_write_mode_i') == '1': # Write mode
                    # Extract data from external lut_write_data_i
                    lut_data_width = self.state_encoding_width + sum(f['width'] for f in self.lut_ram_config['lut_ram_config']['param_fields'])
                    write_data_int = self.current_inputs.get('lut_write_data_i', 0) # Assumed int for simulation
                    
                    next_s_enc_val = write_data_int >> sum(f['width'] for f in self.lut_ram_config['lut_ram_config']['param_fields'])
                    # Convert encoding back to state name (simple for simulation, can be more robust)
                    state_names_ordered = [s_data['name'] for s_data in self.fsm_config['states']]
                    next_state_from_data = "IDLE"
                    try:
                        next_state_from_data = state_names_ordered[next_s_enc_val]
                    except IndexError:
                        logging.warning(f"Invalid state encoding {next_s_enc_val} in lut_write_data_i. Defaulting to IDLE.")

                    # Extract parameters
                    params_dict = {}
                    current_bit_pos = 0
                    for field in self.lut_ram_config['lut_ram_config']['param_fields']:
                        mask = (1 << field['width']) - 1
                        params_dict[field['name']] = (write_data_int >> current_bit_pos) & mask
                        current_bit_pos += field['width']

                    self.write_lut_ram(self.lut_current_addr, next_state_from_data, params_dict)
                    logging.info(f"RST State: Writing to LUT RAM at address 0x{self.lut_current_addr:X}")
                else: # Read mode
                    read_data = self.read_lut_ram(self.lut_current_addr)
                    # Output read data (for external interface to consume)
                    logging.info(f"RST State: Reading from LUT RAM at address 0x{self.lut_current_addr:X} - {read_data}")
                
                # Increment address after R/W if access_en is high
                self.lut_current_addr = (self.lut_current_addr + 1) % (2**self.lut_ram_config['lut_ram_config']['address_width'])
                logging.info(f"RST State: LUT RAM address incremented to 0x{self.lut_current_addr:X}")
        
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
                logging.info(f"No explicit transition met for state {self.current_state_name}. Defaulting to IDLE.")
                next_state_name = "IDLE" # Default to IDLE if no other transition is defined or met
        
        # Special handling for RST state transition (reset lut_current_addr)
        if next_state_name == "RST" and self.current_state_name != "RST":
            self.lut_current_addr = 0 # Reset LUT RAM address when entering RST

        # Update outputs based on current state (Moore-like outputs)
        self.current_outputs['current_state_o'] = self.get_state_encoding(self.current_state_name)
        self.current_outputs['busy_o'] = '1' if self.current_state_name != 'IDLE' else '0'
        
        self.current_outputs['sequence_done_o'] = '0' 
        if self.current_state_name == "EXPOSE_TIME" and next_state_name == "IDLE" and self.current_param_values.get('eof') == 1:
             self.current_outputs['sequence_done_o'] = '1'

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
                field_width = next(f['width'] for f in self.lut_ram_config['lut_ram_config']['param_fields'] if f['name'] == param_name)
                if any(out['name'] == output_key and 'std_logic_vector' in out['type'] for out in self.outputs_def):
                    self.current_outputs[output_key] = f"{field_width}'d{param_val}" # Using decimal string
                else:
                    self.current_outputs[output_key] = param_val

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

    def write_lut_ram(self, address, next_state_name, params_dict):
        """Allows runtime update of the simulated LUT RAM."""
        addr_width = self.lut_ram_config['lut_ram_config']['address_width']
        ram_depth = 2**addr_width
        
        if address < ram_depth:
            if next_state_name not in self.states:
                logging.warning(f"Invalid next_state '{next_state_name}' for LUT RAM write. Defaulting to IDLE.")
                next_state_name = 'IDLE'

            validated_params = {}
            for field in self.lut_ram_config['lut_ram_config']['param_fields']:
                validated_params[field['name']] = params_dict.get(field['name'], 0)
            
            self.lut_ram_model[address] = {
                'next_state': next_state_name,
                'params': validated_params
            }
            logging.info(f"SIMULATOR: LUT RAM entry updated at address 0x{address:X}: Next={next_state_name}, Params={validated_params}")
        else:
            logging.error(f"SIMULATOR: Attempted to write beyond LUT RAM bounds: Address 0x{address:X}")

    def read_lut_ram(self, address):
        """Allows runtime read of the simulated LUT RAM."""
        addr_width = self.lut_ram_config['lut_ram_config']['address_width']
        ram_depth = 2**addr_width
        
        if address < ram_depth:
            entry = self.lut_ram_model.get(address)
            logging.info(f"SIMULATOR: LUT RAM read at address 0x{address:X}: {entry}")
            return entry
        else:
            logging.error(f"SIMULATOR: Attempted to read beyond LUT RAM bounds: Address 0x{address:X}")
            return None


def generate_systemverilog_fsm_with_lut_ram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a SystemVerilog HDL module for the FSM with LUT RAM runtime update.
    LUT RAM address automatically increments based on lut_access_en_i in RST state.
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
    
    # Add simplified LUT RAM R/W interface ports
    port_declarations.append(f"    input  logic                               lut_access_en_i,    // LUT RAM Access Enable (1 pulse per read/write cycle)")
    port_declarations.append(f"    input  logic                               lut_read_write_mode_i, // 0: Read, 1: Write")
    port_declarations.append(f"    input  logic [{lut_data_width}-1:0]        lut_write_data_i,   // Data to write to LUT RAM")
    port_declarations.append(f"    output logic [{lut_data_width}-1:0]        lut_read_data_o     // Data read from LUT RAM")


    verilog_code.append(",\n".join(port_declarations))
    verilog_code.append(");\n")

    verilog_code.append(f"    // --- State Encoding Parameters ---")
    for state_name, encoding in state_encoding.items():
        verilog_code.append(f"    localparam {state_name} = {encoding};")
    verilog_code.append("\n")

    verilog_code.append(f"    // --- FSM State Registers ---")
    verilog_code.append(f"    logic [{state_width-1}:0] current_state;")
    verilog_code.append(f"    logic [{state_width-1}:0] next_state;\n")
    
    verilog_code.append(f"    // --- Parameter Registers (updated from LUT RAM) ---")
    verilog_code.append(f"    logic [{total_param_width-1}:0] current_param_combined_reg; // Holds combined parameter value")
    # Individual parameter registers
    for field in param_fields:
        verilog_code.append(f"    logic [{field['width']-1}:0] param_{field['name']}_reg;")
    verilog_code.append("\n")

    # --- LUT RAM Implementation ---
    verilog_code.append(f"    // --- FSM LUT RAM (Behavioral Model - will be synthesized to BRAM/LUT-RAM) ---")
    verilog_code.append(f"    // Each entry stores: {{next_state_encoding, combined_param_value}}")
    verilog_code.append(f"    localparam int LUT_RAM_DEPTH = {2**lut_address_width};")
    verilog_code.append(f"    logic [{lut_data_width-1}:0] lut_ram [LUT_RAM_DEPTH-1:0];\n")
    
    verilog_code.append(f"    // --- LUT RAM Address and Control Registers ---")
    verilog_code.append(f"    logic [{lut_address_width}-1:0] lut_current_addr_reg; // Current address for LUT RAM R/W")
    verilog_code.append(f"    logic                               lut_internal_active;  // True when LUT RAM access is permitted/active\n")

    verilog_code.append(f"    // LUT RAM access is only enabled when FSM is in RST state AND external access_en is high")
    verilog_code.append(f"    assign lut_internal_active = (current_state == RST) && lut_access_en_i;\n")
    
    verilog_code.append(f"    // LUT RAM Read Data Output: always reading from lut_current_addr_reg when internal_active, else '0")
    verilog_code.append(f"    assign lut_read_data_o = lut_internal_active && !lut_read_write_mode_i ? lut_ram[lut_current_addr_reg] : '0; \n")


    verilog_code.append(f"    // --- Synchronous Logic (State, Parameters, and LUT RAM R/W) ---")
    verilog_code.append(f"    always_ff @(posedge clk or negedge reset_n) begin")
    verilog_code.append(f"        if (!reset_n) begin")
    verilog_code.append(f"            current_state <= IDLE;")
    verilog_code.append(f"            current_param_combined_reg <= '0;")
    for field in param_fields:
        verilog_code.append(f"            param_{field['name']}_reg <= '0;")
    
    # Reset/Initialise LUT RAM content to default values
    verilog_code.append(f"            lut_current_addr_reg <= '0;") # Reset LUT RAM address
    verilog_code.append(f"            for (int i = 0; i < LUT_RAM_DEPTH; i++) begin")
    default_param_values_str = "{" + ", ".join([f"{field['width']}'d0" for field in param_fields]) + "}"
    verilog_code.append(f"                lut_ram[i] <= {{IDLE, {default_param_values_str}}};")
    verilog_code.append(f"            end")

    verilog_code.append(f"        end else begin")
    verilog_code.append(f"            // FSM State Update")
    verilog_code.append(f"            current_state <= next_state;")

    verilog_code.append(f"            // LUT RAM Address Increment and Write Logic")
    verilog_code.append(f"            if (lut_internal_active) begin")
    verilog_code.append(f"                if (lut_read_write_mode_i) begin // Write mode")
    verilog_code.append(f"                    lut_ram[lut_current_addr_reg] <= lut_write_data_i;")
    verilog_code.append(f"                end")
    verilog_code.append(f"                // Increment address after R/W, wrapping around")
    verilog_code.append(f"                lut_current_addr_reg <= lut_current_addr_reg + 1;")
    verilog_code.append(f"            end else if (next_state == RST && current_state != RST) begin")
    verilog_code.append(f"                // Reset LUT RAM address when entering RST state")
    verilog_code.append(f"                lut_current_addr_reg <= '0;")
    verilog_code.append(f"            end")
    
    verilog_code.append(f"            // FSM Parameter Registers Update")
    verilog_code.append(f"            if (current_state == IDLE) begin // Update parameters when transitioning FROM IDLE")
    verilog_code.append(f"                current_param_combined_reg <= lut_param_read;")
    for field in param_fields:
        start_bit, end_bit = param_bit_ranges[field['name']]
        verilog_code.append(f"                param_{field['name']}_reg <= lut_param_read[{end_bit}:{start_bit}];")
    verilog_code.append(f"            end")
    verilog_code.append(f"        end")
    verilog_code.append(f"    end\n")

    # Read from RAM based on command_id_i (always available for IDLE state transitions)
    verilog_code.append(f"    logic [{state_width-1}:0] lut_next_state_read; ")
    verilog_code.append(f"    logic [{total_param_width-1}:0] lut_param_read; ")
    verilog_code.append(f"    assign {{lut_next_state_read, lut_param_read}} = lut_ram[command_id_i];\n")

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
            explicit_idle_transition_found = False
            for transition in state['transitions']:
                condition = transition['condition']
                next_s = transition['next_state']
                if next_s == "IDLE":
                    explicit_idle_transition_found = True
                verilog_code.append(f"                if ({condition}) begin")
                verilog_code.append(f"                    next_state = {next_s};")
                verilog_code.append(f"                end")
            
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
        if out_port['name'] == 'current_state_o':
            verilog_code.append(f"        {out_port['name']} = current_state;")
        elif out_port['name'] == 'busy_o':
            verilog_code.append(f"        {out_port['name']} = (current_state != IDLE);")
        elif out_port['name'] == 'sequence_done_o':
            verilog_code.append(f"        {out_port['name']} = (current_state == EXPOSE_TIME && next_state == IDLE && param_eof_reg == 1'b1);")
        elif out_port['name'].startswith('current_') and out_port['name'].endswith('_o'):
            param_name = out_port['name'].replace('current_', '').replace('_o', '')
            verilog_code.append(f"        {out_port['name']} = param_{param_name}_reg;")
        else:
            if 'std_logic_vector' in out_port['type']:
                verilog_code.append(f"        {out_port['name']} = '0; // Default to all zeros")
            else:
                verilog_code.append(f"        {out_port['name']} = '0;")
    
    verilog_code.append(f"        case (current_state)")
    for state in states_data:
        state_name = state['name']
        verilog_code.append(f"            {state_name}: begin")
        for output_name, output_value in state['outputs'].items():
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


def generate_mermaid_fsm_diagram(fsm_config_path, lut_ram_config_path, output_file):
    """
    Generates a Mermaid State Diagram markdown string from FSM configuration.
    """
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = fsm_config['fsm_name']
    states_data = fsm_config['states']
    
    mermaid_lines = []
    mermaid_lines.append("```mermaid")
    mermaid_lines.append(f"stateDiagram-v2")
    mermaid_lines.append(f"    direction LR") # Left to Right diagram direction

    # Define states
    for state in states_data:
        state_name = state['name']
        output_desc = []
        # .get()을 사용하여 'outputs' 키가 없을 경우를 대비합니다.
        for out_name, out_val in state.get('outputs', {}).items():
            if out_name not in ['current_state_o', 'busy_o', 'sequence_done_o'] and \
               not out_name.startswith('current_') and not out_name.endswith('_o'):
                output_desc.append(f"{out_name}={out_val}")
        
        if output_desc:
            mermaid_lines.append(f"    state {state_name} : {', '.join(output_desc)}")
        else:
            mermaid_lines.append(f"    state {state_name}")

    mermaid_lines.append("\n")

    # Define initial state
    mermaid_lines.append(f"    [*] --> IDLE")

    # Define transitions
    for state in states_data:
        state_name = state['name']
        
        if state_name == "IDLE":
            mermaid_lines.append(f"    IDLE --> State_from_LUT : command_id_i (LUT Lookup)")
            mermaid_lines.append(f"    state State_from_LUT <<choice>>")
            
            next_states_from_lut = set(entry['next_state'] for entry in lut_ram_config['lut_entries'])
            
            for next_s in sorted(list(next_states_from_lut)):
                # LUT에서 전이될 수 있는 각 상태에 대해 command_id_i를 조건으로 명시
                # 실제 command_id_i 값 대신 상태 이름을 조건으로 사용하는 것이 다이어그램에서 더 직관적입니다.
                mermaid_lines.append(f"    State_from_LUT --> {next_s} : command_id_i == \"{next_s}\"")
            
        else:
            has_explicit_transition_to_self = False # 'True' 조건으로 자기 자신에게 가는 전이 여부 확인
            explicit_transitions = []
            for transition in state['transitions']:
                condition = transition['condition'].replace('&&', ' and ').replace('||', ' or ').replace("'", "")
                next_s = transition['next_state']
                
                explicit_transitions.append(f"    {state_name} --> {next_s} : {condition}")
                
                if condition == "True" and next_s == state_name:
                    has_explicit_transition_to_self = True

            # 명시적 전이를 먼저 추가합니다.
            mermaid_lines.extend(explicit_transitions)

            # 'else' 전이 추가 로직 (기존 FSM의 동작 방식과 Mermaid의 'else' 문법을 고려)
            # 조건이 명시적으로 'True'가 아니면서 자기 자신에게 가는 전이가 없다면 'else'를 추가
            if not has_explicit_transition_to_self:
                # FSM 시뮬레이터와 Verilog 생성 코드는 명시된 전이가 없으면 기본적으로 IDLE로 갑니다.
                # 하지만, 수정된 Mermaid 코드에서는 'else'일 때 자기 자신에게 머무는 것으로 표현되어 있습니다.
                # Mermaid 다이어그램의 의도를 반영하기 위해 'else'는 자기 자신에게 머무는 것으로 합니다.
                # 만약 IDLE로 가야 한다면, 해당 상태의 YAML에 'True' 조건으로 IDLE 전이를 명시하는 것이 좋습니다.
                mermaid_lines.append(f"    {state_name} --> {state_name} : else")
    
    # Updated note block position and content formatting
    mermaid_lines.append("\n    note right of RST")
    mermaid_lines.append("        LUT RAM Read/Write Mode:")
    mermaid_lines.append("        - Address auto-increments with each access.")
    mermaid_lines.append("        - lut_read_write_mode_i: 0=Read, 1=Write")
    mermaid_lines.append("        - lut_access_en_i triggers access & increment.")
    mermaid_lines.append("    end note")

    mermaid_lines.append("```")

    with open(output_file, 'w') as f:
        f.write("\n".join(mermaid_lines))
    logging.info(f"Mermaid State Diagram generated successfully: {output_file}")

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

  - name: PANEL_STABLE
    outputs: {busy_o: '1', sequence_done_o: '0'}
    transitions:
      - condition: "sensor_stable_i == '1'"
        next_state: IDLE
      - condition: "True"
        next_state: PANEL_STABLE

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
      - condition: "task_done_i == '1' && adc_ready_i == '1'"
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
    print("Starting FSM Simulation (Python)...")
    simulator = FsmSimulator("fsm_config.yaml", "fsm_lut_ram_data.yaml")

    # Simulation Sequence Example
    # Step 1: Send command_id_i = 0x00 (Go to RST from IDLE)
    # lut_access_en_i and lut_read_write_mode_i are for external control during RST
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                         lut_access_en_i='0', lut_read_write_mode_i='0', lut_write_data_i=0)
    simulator.step() # Current: IDLE, Next: RST, Params updated (lut_current_addr will be reset to 0 upon entering RST)
    
    # Step 2: In RST state, write some data to LUT RAM at address 0x00 (which is current_addr)
    print("\n--- Simulating LUT RAM Write in RST State (Addr increments) ---")
    # Prepare data to write: State: FLUSH (0b011), repeat_count: 5, data_length: 64, eof: 0, sof: 1
    # Assuming state encoding width 3 bits, total_param_width 26 bits
    # Data format: {next_state_encoding, sof, eof, data_length, repeat_count}
    # FLUSH = 0b011
    # 0b011 (state) | 1 (sof) | 0 (eof) | 64 (data_length) | 5 (repeat_count)
    
    # Example raw write data (for address 0x00)
    # The actual combined integer value needs to be calculated based on bit widths
    # For simulation, we'll just conceptually set lut_ram_model, but the Verilog logic needs the combined value.
    # Total param width = 8 + 16 + 1 + 1 = 26 bits
    # State width = 3 bits
    # LUT Data width = 29 bits
    
    # Example: write FLUSH (0b011) with params {rep=5, data_len=64, eof=0, sof=1}
    # params: sof (1b) + eof (1b) + data_length (16b) + repeat_count (8b) = 26 bits
    # Data: {3'b011, 1'b1, 1'b0, 16'd64, 8'd5}
    # Combined int value: (0b011 << 26) | (1 << 25) | (0 << 24) | (64 << 8) | (5 << 0)
    
    # Pre-calculating a complex combined value for demo:
    # For state FLUSH (0b011), repeat_count = 5, data_length = 64, eof = 0, sof = 1
    # params_bit_ranges: {'repeat_count': (0, 7), 'data_length': (8, 23), 'eof': (24, 24), 'sof': (25, 25)}
    # State encoding for FLUSH is 0b011
    # combined_param_value = (1 << 25) | (0 << 24) | (64 << 8) | (5 << 0)
    # lut_data_word = (state_encoding['FLUSH'] << 26) | combined_param_value
    # For Python simulator convenience, we still use simplified write_lut_ram:
    simulator.write_lut_ram(simulator.lut_current_addr, "FLUSH", {'repeat_count': 5, 'data_length': 64, 'eof': 0, 'sof': 1})
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                         lut_access_en_i='1', lut_read_write_mode_i='1', lut_write_data_i=0) # lut_write_data_i will be the combined int
    simulator.step() # Current: RST, Next: RST. Writes to addr 0x00, increments addr to 0x01.

    # Step 3: In RST state, read from LUT RAM at address 0x01 (current_addr)
    print("\n--- Simulating LUT RAM Read in RST State (Addr increments) ---")
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                         lut_access_en_i='1', lut_read_write_mode_i='0', lut_write_data_i=0)
    simulator.step() # Current: RST, Next: RST. Reads from addr 0x01, increments addr to 0x02.

    # Step 4: Exit RST state by task_done_i
    simulator.set_inputs(command_id_i=0x00, task_done_i='1', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                         lut_access_en_i='0', lut_read_write_mode_i='0', lut_write_data_i=0)
    simulator.step() # Current: RST, Next: IDLE. lut_current_addr is NOT reset here because it was reset upon entering RST.

    # Step 5: Trigger command_id_i = 0x00 again. This time it should transition to FLUSH with new params.
    # Note: If LUT RAM was updated at 0x00 in step 2, this will use the NEW entry.
    print("\n--- Triggering updated LUT RAM entry (0x00) ---")
    simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                         lut_access_en_i='0', lut_read_write_mode_i='0', lut_write_data_i=0)
    simulator.step() # Current: IDLE, Next: FLUSH, Params updated (from updated 0x00 entry)

    print("\nFSM Simulation Complete.")

    # 3. Generate SystemVerilog HDL code
    print("\nGenerating SystemVerilog HDL code...")
    generate_systemverilog_fsm_with_lut_ram("fsm_config.yaml", "fsm_lut_ram_data.yaml", "sequencer_fsm.sv")
    print("SystemVerilog FSM with LUT RAM runtime update code generated successfully: sequencer_fsm.sv")

    # 4. Generate Mermaid State Diagram 
    print("\nGenerating Mermaid State Diagram...")
    generate_mermaid_fsm_diagram("fsm_config.yaml", "fsm_lut_ram_data.yaml", "fsm_diagram.md")
    print("Mermaid State Diagram generated successfully: fsm_diagram.md")


    # Clean up dummy config files
    import os
    # os.remove("fsm_config.yaml")
    # os.remove("fsm_lut_ram_data.yaml")
    # os.remove("fsm_diagram.md")
    # print("Dummy config files removed.")
