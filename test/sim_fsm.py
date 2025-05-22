# sim_fsm.py
import yaml
import logging
import os
import subprocess
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class FsmSimulator:
    """
    A Python-based FSM simulator to mimic the SystemVerilog FSM's behavior.
    Reads FSM and LUT RAM configurations from YAML files.
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

        self.states = {}
        for s_data in self.fsm_config['states']:
            self.states[s_data['name']] = {
                'name': s_data['name'],
                'outputs': s_data.get('outputs', {}),
                'transitions': s_data.get('transitions', [])
            }
        
        self.current_state_name = 'IDLE'
        self.lut_ram_model = self._initialize_lut_ram_model()
        self.current_inputs = {inp['name']: 0 for inp in self.inputs_def}
        self.current_outputs = {out['name']: '0' for out in self.outputs_def}
        self.current_param_values = {field['name']: 0 for field in self.lut_ram_config['lut_ram_config']['param_fields']}
        self.lut_current_addr = 0

        logging.info(f"FSM Simulator '{self.fsm_name}' initialized. Current state: {self.current_state_name}")

    def _initialize_lut_ram_model(self):
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
        for key, value in kwargs.items():
            if key in self.current_inputs:
                self.current_inputs[key] = value
            else:
                logging.warning(f"Input '{key}' not defined in FSM configuration.")

    def _evaluate_condition(self, condition_expr):
        eval_scope = {}
        for inp_name, inp_val in self.current_inputs.items():
            if isinstance(inp_val, str) and (inp_val == '0' or inp_val == '1'):
                eval_scope[inp_name] = (inp_val == '1')
            else:
                eval_scope[inp_name] = inp_val
        
        try:
            condition_expr_py = condition_expr.replace('&&', 'and').replace('||', 'or')
            return eval(condition_expr_py, {}, eval_scope)
        except Exception as e:
            logging.error(f"Error evaluating condition '{condition_expr}': {e}. Inputs: {self.current_inputs}")
            return False

    def step(self):
        # logging.info(f"\n--- FSM Step (Current State: {self.current_state_name}) ---")
        # logging.info(f"Inputs: {self.current_inputs}")

        current_state_data = self.states[self.current_state_name]
        next_state_name = self.current_state_name

        if self.current_state_name == "RST":
            # In a real scenario, this would be driven by external signals.
            # For pure simulation matching, we assume LUT RAM is initialized once.
            pass 
        
        if self.current_state_name == "IDLE":
            cmd_id = self.current_inputs.get("command_id_i", 0)
            if cmd_id in self.lut_ram_model:
                lut_entry = self.lut_ram_model[cmd_id]
                next_state_name = lut_entry['next_state']
                self.current_param_values = lut_entry['params']
                # logging.info(f"IDLE: LUT RAM lookup for cmd_id={cmd_id} -> Next: {next_state_name}, Params: {self.current_param_values}")
            else:
                # logging.warning(f"IDLE: Invalid command_id_i {cmd_id}. Staying IDLE.")
                next_state_name = "IDLE"
        else:
            transition_found = False
            for transition in current_state_data['transitions']:
                condition_expr = transition['condition']
                if self._evaluate_condition(condition_expr):
                    next_state_name = transition['next_state']
                    transition_found = True
                    # logging.info(f"Transition from {self.current_state_name} on condition '{condition_expr}' -> {next_state_name}")
                    break
            
            if not transition_found:
                # Default behavior if no explicit transition is met
                # Based on SystemVerilog, it defaults to current_state, unless explicit.
                # Your YAML implies IDLE on task_done_i for many states.
                # Here, we'll keep it simple: if no condition, stay in current state (or IDLE if that's the FSM default).
                # For direct comparison with SV, ensure this matches SV's 'default' case.
                next_state_name = self.current_state_name # Stay in current state by default
                # logging.info(f"No explicit transition met for state {self.current_state_name}. Staying in current state.")

        self.current_outputs['current_state_o'] = self.get_state_encoding(self.current_state_name) # This should be current_state_name
        self.current_outputs['busy_o'] = '1' if self.current_state_name != 'IDLE' else '0'
        
        self.current_outputs['sequence_done_o'] = '0' 
        if self.current_state_name == "EXPOSE_TIME" and next_state_name == "IDLE" and self.current_param_values.get('eof') == 1:
             self.current_outputs['sequence_done_o'] = '1'

        for output_name, output_value in current_state_data.get('outputs', {}).items():
            if output_name in self.current_outputs:
                self.current_outputs[output_name] = output_value
            # For simplicity, other outputs like lut_read_data_o are not dynamically set here as they are part of SV.

        for param_name, param_val in self.current_param_values.items():
            output_key = f"current_{param_name}_o"
            if output_key in self.current_outputs:
                # Convert to integer for comparison purposes.
                self.current_outputs[output_key] = param_val

        # Store next_state_name for the actual state transition
        self.current_state_name = next_state_name
        # logging.info(f"New State: {self.current_state_name}, Outputs: {self.current_outputs}")
        
        return self.current_outputs, self.current_state_name

    def get_state_encoding(self, state_name):
        state_names_ordered = [s_data['name'] for s_data in self.fsm_config['states']]
        try:
            idx = state_names_ordered.index(state_name)
            # Return name for comparison directly, not binary encoding
            return state_name 
        except ValueError:
            logging.error(f"Attempted to encode unknown state: {state_name}")
            return 'UNKNOWN'

    def get_lut_ram_initial_data_sv_format(self):
        """
        Generates initial LUT RAM data in a SystemVerilog-friendly format for testbench.
        Returns a list of tuples: (address, data_value_decimal)
        """
        sv_initial_data = []
        state_names_ordered = [s_data['name'] for s_data in self.fsm_config['states']]
        param_fields = self.lut_ram_config['lut_ram_config']['param_fields']

        for entry in self.lut_ram_config['lut_entries']:
            addr = entry['address']
            next_state_name = entry['next_state']
            
            # Get state encoding
            try:
                state_idx = state_names_ordered.index(next_state_name)
                next_state_encoding = state_idx
            except ValueError:
                logging.warning(f"LUT entry for address 0x{addr:X} has unknown next_state '{next_state_name}'. Defaulting to IDLE.")
                next_state_encoding = state_names_ordered.index('IDLE') # Default to IDLE encoding

            # Combine parameters into a single integer value
            combined_params = 0
            current_bit_pos = 0
            for field in param_fields:
                param_val = entry.get(field['name'], 0)
                combined_params |= (param_val << current_bit_pos)
                current_bit_pos += field['width']
            
            # Combined data format: {state_encoding, combined_params}
            # SystemVerilog usually concatenates MSB first: {next_state_encoding, param_N, ..., param_0}
            # Let's match the Verilog generation order: {next_state_encoding, sof, eof, data_length, repeat_count}
            # This means the last param_field in YAML is MSB of params, and state_encoding is MSB overall.
            
            # Reconstruct combined_params based on SV output order (reversed from param_bit_ranges)
            # Reversing param_fields to get MSB to LSB if needed
            sv_combined_params = 0
            current_sv_bit_pos = 0
            for field in reversed(param_fields): # Assuming param_fields are ordered LSB to MSB in definition
                param_val = entry.get(field['name'], 0)
                sv_combined_params |= (param_val << current_sv_bit_pos)
                current_sv_bit_pos += field['width']

            # Total value: {next_state_encoding, sv_combined_params}
            # The state_encoding is at the very MSB.
            total_data_value = (next_state_encoding << current_sv_bit_pos) | sv_combined_params
            
            sv_initial_data.append((addr, total_data_value))
        return sv_initial_data

def generate_sv_tb_with_lut_init(fsm_config_path, lut_ram_config_path, tb_output_file, py_sim_cycles):
    """
    Generates a SystemVerilog testbench with initial LUT RAM data.
    """
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = fsm_config['fsm_name']
    state_width = fsm_config['state_encoding_width']
    
    lut_address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    total_param_width = sum(field['width'] for field in param_fields)
    lut_data_width = state_width + total_param_width

    state_encoding_map = {}
    for i, state_data in enumerate(fsm_config['states']):
        state_encoding_map[state_data['name']] = f"{state_width}'d{i}"

    # Get initial LUT RAM data for SystemVerilog
    simulator_dummy = FsmSimulator(fsm_config_path, lut_ram_config_path) # Use dummy to get initial data
    initial_lut_data = simulator_dummy.get_lut_ram_initial_data_sv_format()

    tb_code = []
    tb_code.append(f"`timescale 1ns / 1ps")
    tb_code.append(f"module {fsm_name}_tb;")
    tb_code.append(f"")
    
    tb_code.append(f"    // FSM Inputs")
    tb_code.append(f"    logic clk;")
    tb_code.append(f"    logic reset_n;")
    tb_code.append(f"    logic [7:0] command_id_i;")
    tb_code.append(f"    logic task_done_i;")
    tb_code.append(f"    logic adc_ready_i;")
    tb_code.append(f"    logic sensor_stable_i;")
    tb_code.append(f"    logic aed_detected_i;")
    tb_code.append(f"")
    tb_code.append(f"    // FSM LUT RAM Access Inputs (for runtime updates, if needed in TB)")
    tb_code.append(f"    logic lut_access_en_i;")
    tb_code.append(f"    logic lut_read_write_mode_i;")
    tb_code.append(f"    logic [{lut_data_width-1}:0] lut_write_data_i;")
    tb_code.append(f"")
    tb_code.append(f"    // FSM Outputs")
    tb_code.append(f"    wire [{state_width-1}:0] current_state_o;")
    tb_code.append(f"    wire busy_o;")
    tb_code.append(f"    wire sequence_done_o;")
    tb_code.append(f"    wire [{param_fields[0]['width']-1}:0] current_repeat_count_o; // Assuming first field is repeat_count")
    tb_code.append(f"    wire [{param_fields[1]['width']-1}:0] current_data_length_o; // Assuming second field is data_length")
    tb_code.append(f"    wire [{param_fields[2]['width']-1}:0] current_eof_o; // Assuming third field is eof")
    tb_code.append(f"    wire [{param_fields[3]['width']-1}:0] current_sof_o; // Assuming fourth field is sof")
    tb_code.append(f"    wire [{lut_data_width-1}:0] lut_read_data_o;")
    tb_code.append(f"")
    
    tb_code.append(f"    // Internal variables for state encoding to string for logging")
    tb_code.append(f"    string state_names[] = {{")
    for i, state_data in enumerate(fsm_config['states']):
        tb_code.append(f"        \"{state_data['name']}\"{(',' if i < len(fsm_config['states']) - 1 else '')}")
    tb_code.append(f"    }};")
    tb_code.append(f"")
    tb_code.append(f"    // File handle for dumping results")
    tb_code.append(f"    integer outfile;")
    tb_code.append(f"")
    tb_code.append(f"    // Instantiate the FSM module")
    tb_code.append(f"    {fsm_name} dut (")
    tb_code.append(f"        .clk                    (clk),")
    tb_code.append(f"        .reset_n                (reset_n),")
    tb_code.append(f"        .command_id_i           (command_id_i),")
    tb_code.append(f"        .task_done_i            (task_done_i),")
    tb_code.append(f"        .adc_ready_i            (adc_ready_i),")
    tb_code.append(f"        .sensor_stable_i        (sensor_stable_i),")
    tb_code.append(f"        .aed_detected_i         (aed_detected_i),")
    tb_code.append(f"        .lut_access_en_i        (lut_access_en_i),")
    tb_code.append(f"        .lut_read_write_mode_i  (lut_read_write_mode_i),")
    tb_code.append(f"        .lut_write_data_i       (lut_write_data_i),")
    tb_code.append(f"        .current_state_o        (current_state_o),")
    tb_code.append(f"        .busy_o                 (busy_o),")
    tb_code.append(f"        .sequence_done_o        (sequence_done_o),")
    tb_code.append(f"        .current_repeat_count_o (current_repeat_count_o),")
    tb_code.append(f"        .current_data_length_o  (current_data_length_o),")
    tb_code.append(f"        .current_eof_o          (current_eof_o),")
    tb_code.append(f"        .current_sof_o          (current_sof_o),")
    tb_code.append(f"        .lut_read_data_o        (lut_read_data_o)")
    tb_code.append(f"    );")
    tb_code.append(f"")
    tb_code.append(f"    // Initial LUT RAM Data Loading")
    tb_code.append(f"    initial begin")
    for addr, data in initial_lut_data:
        tb_code.append(f"        dut.lut_ram[{addr}] = {lut_data_width}'d{data};")
    tb_code.append(f"    end")
    tb_code.append(f"")
    tb_code.append(f"    // Clock generation")
    tb_code.append(f"    initial begin")
    tb_code.append(f"        clk = 1'b0;")
    tb_code.append(f"        forever #5 clk = ~clk; // 10ns clock period")
    tb_code.append(f"    end")
    tb_code.append(f"")
    tb_code.append(f"    // Test sequence")
    tb_code.append(f"    initial begin")
    tb_code.append(f"        outfile = $fopen(\"sv_sim_results.csv\", \"w\");")
    tb_code.append(f"        if (outfile == 0) begin")
    tb_code.append(f"            $error(\"Error: Could not open sv_sim_results.csv\");")
    tb_code.append(f"            $finish;")
    tb_code.append(f"        end")
    tb_code.append(f"        $fwrite(outfile, \"clk_cycle,current_state_sv,busy_sv,sequence_done_sv,repeat_count_sv,data_length_sv,eof_sv,sof_sv\\n\");")
    tb_code.append(f"")
    tb_code.append(f"        // Initial reset")
    tb_code.append(f"        reset_n = 1'b0;")
    tb_code.append(f"        command_id_i = 8'h00;")
    tb_code.append(f"        task_done_i = 1'b0;")
    tb_code.append(f"        adc_ready_i = 1'b0;")
    tb_code.append(f"        sensor_stable_i = 1'b0;")
    tb_code.append(f"        aed_detected_i = 1'b0;")
    tb_code.append(f"        lut_access_en_i = 1'b0;")
    tb_code.append(f"        lut_read_write_mode_i = 1'b0;")
    tb_code.append(f"        lut_write_data_i = {lut_data_width}'h0;")
    tb_code.append(f"")
    tb_code.append(f"        #10; // Apply reset for one clock cycle")
    tb_code.append(f"        reset_n = 1'b1;")
    tb_code.append(f"")
    tb_code.append(f"        // -----------------------------------------------------")
    tb_code.append(f"        // Simulation Sequence - Inputs MUST MATCH Python Sim")
    tb_code.append(f"        // -----------------------------------------------------")
    tb_code.append(f"        // This section will be dynamically populated by Python during execution.")
    tb_code.append(f"        // For now, it's a placeholder. Python will write actual inputs here.")
    tb_code.append(f"")
    tb_code.append(f"        // Example (replace with generated inputs later):")
    tb_code.append(f"        // @(posedge clk); command_id_i = 8'h00; task_done_i = 1'b0; // Cycle 0")
    tb_code.append(f"        // @(posedge clk); command_id_i = 8'h00; task_done_i = 1'b1; // Cycle 1 (IDLE from RST)")
    tb_code.append(f"        // @(posedge clk); command_id_i = 8'h03; task_done_i = 1'b0; // Cycle 2 (EXPOSE_TIME)")
    tb_code.append(f"        // @(posedge clk); command_id_i = 8'h03; task_done_i = 1'b1; // Cycle 3 (IDLE from EXPOSE_TIME)")
    tb_code.append(f"")
    tb_code.append(f"        // This is a dynamic section filled by Python before running SV sim.")
    tb_code.append(f"        // PYTHON_INPUT_SEQUENCE_PLACEHOLDER")
    tb_code.append(f"")
    tb_code.append(f"        $fclose(outfile);")
    tb_code.append(f"        $display(\"SystemVerilog simulation complete. Results saved to sv_sim_results.csv\");")
    tb_code.append(f"        $finish; // End simulation")
    tb_code.append(f"    end")
    tb_code.append(f"")
    tb_code.append(f"endmodule")

    with open(tb_output_file, 'w') as f:
        f.write("\n".join(tb_code))
    logging.info(f"SystemVerilog Testbench generated successfully: {tb_output_file}")


def run_verification_cycle(fsm_config_path, lut_ram_data_path, sv_fsm_path,
                           python_sim_cycles, sim_scenario_inputs):
    """
    Runs one full verification cycle: Python sim, SV sim, and comparison.
    Args:
        fsm_config_path (str): Path to fsm_config.yaml.
        lut_ram_data_path (str): Path to fsm_lut_ram_data.yaml.
        sv_fsm_path (str): Path to the completed sequencer_fsm.sv.
        python_sim_cycles (int): Number of clock cycles to simulate in Python.
        sim_scenario_inputs (list of dict): List of inputs for each cycle.
                                            Example: [{'command_id_i': 0x00, ...}, {'command_id_i': 0x01, ...}]
    """
    logging.info(f"\n--- Starting Verification Cycle with {lut_ram_data_path} ---")

    # --- 1. Run Python FSM Simulation and save results ---
    logging.info("Running Python FSM simulation...")
    simulator = FsmSimulator(fsm_config_path, lut_ram_data_path)
    
    python_output_log_file = "python_sim_results.csv"
    with open(python_output_log_file, "w") as f_out:
        # Define header based on what you want to compare
        header = "clk_cycle,current_state_py,busy_py,sequence_done_py,repeat_count_py,data_length_py,eof_py,sof_py\n"
        f_out.write(header)

        for cycle in range(python_sim_cycles):
            # Apply inputs for the current cycle
            if cycle < len(sim_scenario_inputs):
                simulator.set_inputs(**sim_scenario_inputs[cycle])
            else:
                # Default inputs if scenario is shorter than total cycles
                simulator.set_inputs(command_id_i=0x00, task_done_i='0', adc_ready_i='0', sensor_stable_i='0', aed_detected_i='0',
                                     lut_access_en_i='0', lut_read_write_mode_i='0', lut_write_data_i=0)

            outputs, current_state = simulator.step()
            
            row = f"{cycle},{current_state},{outputs['busy_o']},{outputs['sequence_done_o']}," \
                  f"{outputs.get('current_repeat_count_o', 0)},{outputs.get('current_data_length_o', 0)}," \
                  f"{outputs.get('current_eof_o', 0)},{outputs.get('current_sof_o', 0)}\n"
            f_out.write(row)
    logging.info(f"Python simulation results saved to {python_output_log_file}")

    # --- 2. Generate SystemVerilog Testbench with initial LUT data and input sequence ---
    logging.info("Generating SystemVerilog Testbench with initial LUT data...")
    sv_tb_file = "sequencer_fsm_tb.sv"
    generate_sv_tb_with_lut_init(fsm_config_path, lut_ram_data_path, sv_tb_file, python_sim_cycles)

    # Inject the input sequence into the generated testbench
    with open(sv_tb_file, 'r') as f:
        tb_content = f.read()

    input_sequence_str = []
    for i, inputs_dict in enumerate(sim_scenario_inputs):
        # Convert inputs_dict to SV assignment strings
        sv_assignments = []
        for k, v in inputs_dict.items():
            if isinstance(v, str): # '0' or '1'
                sv_assignments.append(f"{k} = 1'b{v}")
            elif isinstance(v, int): # e.g., command_id_i=0x00
                if k.startswith('command_id_i'):
                    sv_assignments.append(f"{k} = 8'h{v:X}")
                elif k.startswith('lut_write_data_i'):
                    sv_assignments.append(f"{k} = {simulator.lut_ram_config['lut_ram_config']['address_width']+sum(f['width'] for f in simulator.lut_ram_config['lut_ram_config']['param_fields'])}'d{v}")
                else: # Default for other integers
                    sv_assignments.append(f"{k} = {v}")
            else:
                sv_assignments.append(f"{k} = {v}") # Fallback for other types
        
        # Ensure all inputs are explicitly set for each cycle to avoid 'X' in SV
        # This can be made more robust by deriving all inputs from fsm_config['inputs']
        # For simplicity, we just use the inputs provided in sim_scenario_inputs
        input_sequence_str.append(f"        @(posedge clk); // Cycle {i}")
        input_sequence_str.append(f"        " + "; ".join(sv_assignments) + ";")
    
    # Fill remaining cycles with default inputs if sim_scenario_inputs is shorter than python_sim_cycles
    for i in range(len(sim_scenario_inputs), python_sim_cycles):
         input_sequence_str.append(f"        @(posedge clk); // Cycle {i} (default inputs)")
         input_sequence_str.append(f"        command_id_i = 8'h00; task_done_i = 1'b0; adc_ready_i = 1'b0; sensor_stable_i = 1'b0; aed_detected_i = 1'b0;")
         input_sequence_str.append(f"        lut_access_en_i = 1'b0; lut_read_write_mode_i = 1'b0; lut_write_data_i = {simulator.lut_ram_config['lut_ram_config']['address_width']+sum(f['width'] for f in simulator.lut_ram_config['lut_ram_config']['param_fields'])}'h0;")


    tb_content = tb_content.replace("// PYTHON_INPUT_SEQUENCE_PLACEHOLDER", "\n".join(input_sequence_str))

    with open(sv_tb_file, 'w') as f:
        f.write(tb_content)
    logging.info(f"SystemVerilog Testbench populated with input sequence.")


    # --- 3. Run SystemVerilog Simulation ---
    logging.info("Running SystemVerilog simulation (using QuestaSim)...")
    sv_output_log_file = "sv_sim_results.csv"
    try:
        # Assuming sequencer_fsm.sv is already generated and available
        # subprocess.run(["iverilog", "-o", "sequencer_fsm_sim", sv_fsm_path, sv_tb_file], check=True, capture_output=True)
        # subprocess.run(["./sequencer_fsm_sim"], check=True, capture_output=True)

        # --- 아래 두 가지 옵션 중 하나를 선택하여 적용합니다. ---

        # 옵션 1: Vivado XSim 사용 (Vivado 프로젝트 환경이 필요)
        # Vivado XSim은 일반적으로 프로젝트 내에서 실행되므로, 외부 스크립트에서 직접 제어하는 것이 복잡할 수 있습니다.
        # 가장 좋은 방법은 Vivado Tcl 스크립트를 생성하여 이를 호출하는 것입니다.
        # 여기서는 간단한 명령줄 실행 예시를 보여드리지만, 실제 복잡한 프로젝트에서는 Tcl 스크립트가 더 적합합니다.
        # 아래 명령어는 Vivado 프로젝트가 이미 설정되어 있고, sequencer_fsm.sv와 sequencer_fsm_tb.sv가 추가되어 있다고 가정합니다.

        # Vivado XSim 실행을 위한 Tcl 스크립트 생성 (예시)
        # tcl_script_content = f"""
        # launch_simulation
        # set_property -name {fsm_name}_tb -top {{ {fsm_name}_tb }} [get_filesets sim_1]
        # reopen_impl_xdc [get_files -of_objects [get_filesets sim_1] {{*.sv *.v}}]
        # update_compile_order -fileset sim_1
        # add_files -fileset sim_1 {{ {sv_fsm_path} {sv_tb_file} }}
        # compile_simlib -force
        # # run simulation for {python_sim_cycles * 10}ns (if clock period is 10ns)
        # run {python_sim_cycles * 10}ns
        # # Export waveform data or print values to a file
        # # add_wave /tb_fsm_top/*
        # # write_wave_config my_sim.wcfg
        # # write_object_to_file [get_objects -r *] -file /dev/stdout -type {{report_property}} -regexp {{.*}}
        # # Use $finish in your TB to terminate simulation and ensure output file is written
        # exit
        # """
        # with open("run_xsim.tcl", "w") as f:
        #     f.write(tcl_script_content)
        # logging.info("Vivado XSim Tcl script generated.")

        # # Tcl 스크립트 실행 (Vivado 설치 경로에 따라 'vivado' 대신 'xsim' 또는 전체 경로 사용)
        # subprocess.run(["vivado", "-mode", "batch", "-source", "run_xsim.tcl"], check=True, capture_output=True)
        # logging.info(f"Vivado XSim simulation completed. Check sv_sim_results.csv.")


        # 옵션 2: QuestaSim (또는 ModelSim) 사용
        # QuestaSim은 vsim 명령어를 통해 시뮬레이션을 실행합니다.
        # test.do 스크립트를 생성하여 시뮬레이션 과정을 제어하는 것이 일반적입니다.

        do_script_content = f"""
        # Compile
        vlib work
        vlog -sv {sv_fsm_path} {sv_tb_file}

        # Simulate
        vsim -c work.sequencer_fsm_tb -do "run -all; quit" -logfile questa_sim.log
        # -c for command line mode, -do for commands
        # 'run -all' runs until $finish, 'quit' exits vsim
        # You could also specify a time like 'run {python_sim_cycles * 10}ns'
        """
        with open("run_questa.do", "w") as f:
            f.write(do_script_content)
        logging.info("QuestaSim .do script generated.")

        # .do 스크립트 실행 (vsim 명령어가 PATH에 있어야 함)
        # '-batch' 옵션은 GUI 없이 배치 모드로 실행합니다.
        subprocess.run(["vsim", "-c", "-do", "run_questa.do"], check=True, capture_output=True)
        logging.info(f"QuestaSim simulation completed. Check sv_sim_results.csv.")

    except FileNotFoundError:
        logging.error("iverilog not found. Please ensure Icarus Verilog is installed and in your PATH.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"SystemVerilog simulation failed: {e.stderr.decode()}")
        return False

    # --- 4. Compare Results ---
    logging.info("Comparing Python and SystemVerilog simulation results...")
    return compare_results(python_output_log_file, sv_output_log_file)

def compare_results(python_results_file, sv_results_file):
    """
    Compares FSM simulation results from Python and SystemVerilog.
    Returns True if results match, False otherwise.
    """
    try:
        df_py = pd.read_csv(python_results_file)
        df_sv = pd.read_csv(sv_results_file)
    except FileNotFoundError as e:
        logging.error(f"Error: One of the result files not found for comparison: {e}")
        return False

    if len(df_py) != len(df_sv):
        logging.warning(f"Warning: Number of cycles differ! Python: {len(df_py)}, SystemVerilog: {len(df_sv)}. Comparing up to min length.")
        min_len = min(len(df_py), len(df_sv))
        df_py = df_py.head(min_len)
        df_sv = df_sv.head(min_len)

    mismatches_found = False
    for i in range(len(df_py)):
        py_row = df_py.iloc[i]
        sv_row = df_sv.iloc[i]
        
        cycle = py_row['clk_cycle']

        # Compare outputs - ensure data types are consistent for comparison
        # State comparison (string)
        if py_row['current_state_py'] != sv_row['current_state_sv']:
            logging.error(f"Mismatch at cycle {cycle} - State: Python='{py_row['current_state_py']}', SV='{sv_row['current_state_sv']}'")
            mismatches_found = True
        
        # Binary outputs (convert to int)
        if int(py_row['busy_py']) != int(sv_row['busy_sv']):
            logging.error(f"Mismatch at cycle {cycle} - Busy: Python='{py_row['busy_py']}', SV='{sv_row['busy_sv']}'")
            mismatches_found = True
        
        if int(py_row['sequence_done_py']) != int(sv_row['sequence_done_sv']):
            logging.error(f"Mismatch at cycle {cycle} - Sequence Done: Python='{py_row['sequence_done_py']}', SV='{sv_row['sequence_done_sv']}'")
            mismatches_found = True

        # Parameter outputs (integer comparison)
        if int(py_row['repeat_count_py']) != int(sv_row['repeat_count_sv']):
            logging.error(f"Mismatch at cycle {cycle} - Repeat Count: Python={py_row['repeat_count_py']}, SV={py_row['repeat_count_sv']}")
            mismatches_found = True
        
        if int(py_row['data_length_py']) != int(sv_row['data_length_sv']):
            logging.error(f"Mismatch at cycle {cycle} - Data Length: Python={py_row['data_length_py']}, SV={sv_row['data_length_sv']}")
            mismatches_found = True

        if int(py_row['eof_py']) != int(sv_row['eof_sv']):
            logging.error(f"Mismatch at cycle {cycle} - EOF: Python={py_row['eof_py']}, SV={sv_row['eof_sv']}")
            mismatches_found = True
        
        if int(py_row['sof_py']) != int(sv_row['sof_sv']):
            logging.error(f"Mismatch at cycle {cycle} - SOF: Python={py_row['sof_py']}, SV={sv_row['sof_sv']}")
            mismatches_found = True

    if not mismatches_found:
        logging.info("\nVerification PASSED: Python and SystemVerilog simulation results match!")
        return True
    else:
        logging.error("\nVerification FAILED: Mismatches found between Python and SystemVerilog simulation results.")
        return False

if __name__ == "__main__":
    # Define file paths
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml" # This is the file you'll modify
    SV_FSM_PATH = "sequencer_fsm.sv" # Ensure this file exists and is generated by generate_fsm.py

    # --- Scenario 1: Default LUT RAM data and a simple sequence ---
    logging.info("===== Running Scenario 1: Default LUT RAM Data =====")
    # This LUT data should already be in fsm_lut_ram_data.yaml as provided earlier.
    # We will simulate a sequence where FSM goes IDLE -> RST -> IDLE -> EXPOSE_TIME -> IDLE
    
    # Input sequence for both Python and SV simulations
    scenario1_inputs = [
        # Cycle 0: IDLE, command_id_i=0x00 (should go to RST)
        {'command_id_i': 0x00, 'task_done_i': '0', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 1: RST, task_done_i=1 (should go to IDLE)
        {'command_id_i': 0x00, 'task_done_i': '1', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 2: IDLE, command_id_i=0x03 (should go to EXPOSE_TIME)
        {'command_id_i': 0x03, 'task_done_i': '0', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 3: EXPOSE_TIME, task_done_i=1 (should go to IDLE)
        {'command_id_i': 0x03, 'task_done_i': '1', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 4-X: Stay in IDLE (default inputs will be applied)
        {'command_id_i': 0x00, 'task_done_i': '0', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
    ]
    # Total cycles for this scenario
    TOTAL_SIM_CYCLES = 8 

    run_verification_cycle(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, SV_FSM_PATH,
                           TOTAL_SIM_CYCLES, scenario1_inputs)

    # --- Scenario 2: Modify fsm_lut_ram_data.yaml dynamically ---
    # This demonstrates changing LUT RAM and re-verifying
    logging.info("\n===== Running Scenario 2: Modified LUT RAM Data =====")
    
    # Create a modified LUT RAM data file
    modified_lut_ram_data_content = """
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
    repeat_count: 5 # Changed repeat count for FLUSH
    data_length: 128 # Changed data length for FLUSH
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
  - address: 0x04
    next_state: READOUT
    repeat_count: 1
    data_length: 2048
    eof: 0
    sof: 0
  - address: 0xFF
    next_state: IDLE
    repeat_count: 0
    data_length: 0
    eof: 0
    sof: 0
"""
    # Write the modified content to the LUT RAM data file
    with open(LUT_RAM_DATA_PATH, "w") as f:
        f.write(modified_lut_ram_data_content)
    
    # Define an input sequence that triggers the modified entry (e.g., command_id_i=0x01 for FLUSH)
    scenario2_inputs = [
        # Cycle 0: IDLE, command_id_i=0x01 (should go to FLUSH with new params)
        {'command_id_i': 0x01, 'task_done_i': '0', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 1: FLUSH, task_done_i=1 (should go to IDLE)
        {'command_id_i': 0x01, 'task_done_i': '1', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
        # Cycle 2-X: Stay in IDLE
        {'command_id_i': 0x00, 'task_done_i': '0', 'adc_ready_i': '0', 'sensor_stable_i': '0', 'aed_detected_i': '0',
         'lut_access_en_i': '0', 'lut_read_write_mode_i': '0', 'lut_write_data_i': 0},
    ]
    TOTAL_SIM_CYCLES_SCENARIO2 = 5 # Fewer cycles for this shorter scenario

    run_verification_cycle(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, SV_FSM_PATH,
                           TOTAL_SIM_CYCLES_SCENARIO2, scenario2_inputs)

    # Clean up generated files (optional)
    # os.remove("python_sim_results.csv")
    # os.remove("sv_sim_results.csv")
    # os.remove("sequencer_fsm_tb.sv")
