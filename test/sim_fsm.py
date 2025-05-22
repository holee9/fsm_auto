import yaml
import logging
import os
import sys

# Configure logging for informational messages only.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class SequencerFSM:
    """
    Python model of the Sequencer FSM for rapid simulation and LUT optimization.
    This simulates the FSM's state transitions based on LUT data and internal task completions.
    """
    def __init__(self, fsm_config_path, lut_ram_config_path):
        # Validate configuration file paths.
        if not os.path.exists(fsm_config_path):
            logging.error(f"Error: FSM configuration file not found at {fsm_config_path}")
            sys.exit(1)
        if not os.path.exists(lut_ram_config_path):
            logging.error(f"Error: LUT RAM data file not found at {lut_ram_config_path}")
            sys.exit(1)

        # Load FSM and LUT RAM configurations from YAML files.
        with open(fsm_config_path, 'r') as f:
            self.fsm_config = yaml.safe_load(f)
        with open(lut_ram_config_path, 'r') as f:
            self.lut_ram_config = yaml.safe_load(f)

        self.fsm_name = self.fsm_config['fsm_name']
        self.state_width = self.fsm_config['state_encoding_width']
        self.states_data = self.fsm_config['states']
        
        # Create mappings between state names and their encodings.
        self.state_encoding_map = {state['name']: state['encoding'] for state in self.states_data}
        self.encoding_state_map = {encoding: name for name, encoding in self.state_encoding_map.items()}

        # Ensure essential states (RST, IDLE) are defined.
        if 'RST' not in self.state_encoding_map:
            logging.error("Critical Error: 'RST' state is not defined in fsm_config.yaml.")
            sys.exit(1)
        if 'IDLE' not in self.state_encoding_map:
            logging.error("Critical Error: 'IDLE' state is not defined in fsm_config.yaml.")
            sys.exit(1)

        # Extract LUT RAM configuration parameters.
        self.lut_address_width = self.lut_ram_config['lut_ram_config']['address_width']
        self.param_fields = self.lut_ram_config['lut_ram_config']['param_fields']
        self.lut_entries_raw = self.lut_ram_config['lut_entries']

        # Calculate total width of LUT data, including next state and parameters.
        total_param_width = sum(field['width'] for field in self.param_fields)
        self.lut_data_width = self.state_width + total_param_width

        # Initialize FSM state registers.
        self.current_state_reg = self.state_encoding_map['RST'] # FSM starts in RST state.
        self.lut_addr_reg = 0
        self.sim_time = 0

        # Internal simulation signals to mimic hardware task completion.
        self.internal_task_done = False
        self.internal_adc_ready = False
        self.internal_sensor_stable = False
        self.internal_aed_detected = False
        self.task_timer = 0 # Simple timer for task completion simulation.

        # Load and pack LUT RAM data.
        self.lut_ram = self._pack_lut_entries()

        # Initialize current parameter values read from LUT.
        self.current_params = {field['name']: 0 for field in self.param_fields}
        self.next_state_from_lut = self.state_encoding_map['RST'] # Placeholder for next state from LUT.

        # Simulation statistics.
        self.sequence_completion_count = 0
        self.warnings = [] # Collect warnings during simulation.

        # For optimized output:
        self.prev_display_info = {} # Stores info from previous cycle for comparison.

    def _pack_lut_entry(self, entry):
        """Packs a single LUT entry (next state and parameters) into a binary integer."""
        packed_value = 0
        
        # Pack next_state (most significant bits).
        next_state_encoding = self.state_encoding_map[entry['next_state']]
        packed_value |= (next_state_encoding << sum(field['width'] for field in self.param_fields))

        # Pack parameter fields (least significant bits).
        bit_offset = 0
        for field in self.param_fields:
            field_name = field['name']
            field_width = field['width']
            field_value = entry[field_name]
            packed_value |= (field_value << bit_offset)
            bit_offset += field_width
        
        return packed_value

    def _unpack_lut_data(self, packed_data):
        """Unpacks a binary LUT data word into its next_state and parameter components."""
        unpacked = {}
        
        # Unpack parameters (least significant bits).
        bit_offset = 0
        for field in self.param_fields:
            field_name = field['name']
            field_width = field['width']
            mask = (1 << field_width) - 1
            unpacked[field_name] = (packed_data >> bit_offset) & mask
            bit_offset += field_width
        
        # Unpack next_state (most significant bits).
        unpacked_next_state_encoding = (packed_data >> bit_offset) & ((1 << self.state_width) - 1)
        unpacked['next_state'] = self.encoding_state_map.get(unpacked_next_state_encoding, "UNKNOWN")
        
        return unpacked

    def _pack_lut_entries(self):
        """Packs all raw LUT entries into a dictionary representing the RAM."""
        ram = {}
        for entry in self.lut_entries_raw:
            addr = entry['address']
            packed_val = self._pack_lut_entry(entry)
            ram[addr] = packed_val
        return ram

    def _get_lut_data_at_addr(self, addr):
        """Retrieves and unpacks LUT data for a given address."""
        if addr in self.lut_ram:
            packed_val = self.lut_ram[addr]
            return self._unpack_lut_data(packed_val)
        
        # If address is out of bounds or invalid, log a warning and return a default RST command.
        self.warnings.append(f"Sim Time {self.sim_time}: LUT Address {addr:#04x} out of bounds or invalid. Defaulting to RST command.")
        return {
            'next_state': 'RST',
            'repeat_count': 0,
            'data_length': 0,
            'eof': 0,
            'sof': 0
        }

    def _simulate_internal_tasks(self):
        """Simulates internal task completion signals based on the current FSM state."""
        # Reset signals each cycle.
        self.internal_task_done = False
        self.internal_adc_ready = False
        self.internal_sensor_stable = False
        self.internal_aed_detected = False

        current_state_name = self.encoding_state_map.get(self.current_state_reg)

        # Simple task timers (adjust delays as needed for specific FSM timing).
        if current_state_name in ["BACK_BIAS", "FLUSH", "EXPOSE_TIME"]:
            if self.task_timer >= 20: # Example delay
                self.internal_task_done = True
                self.task_timer = 0
            else:
                self.task_timer += 1
        elif current_state_name == "PANEL_STABLE":
            if self.task_timer >= 15: # Example delay
                self.internal_sensor_stable = True
                self.task_timer = 0
            else:
                self.task_timer += 1
        elif current_state_name == "READOUT":
            if self.task_timer >= 50: # Example delay
                self.internal_task_done = True
                self.internal_adc_ready = True
                self.task_timer = 0
            elif self.task_timer >= 40: # ADC_READY asserts before task_done.
                self.internal_adc_ready = True
                self.task_timer += 1
            else:
                self.task_timer += 1
        elif current_state_name == "AED_DETECT":
            if self.task_timer >= 10: # Example delay
                self.internal_aed_detected = True
                self.task_timer = 0
            else:
                self.task_timer += 1
        else: # For RST, IDLE or UNKNOWN states, reset timer.
            self.task_timer = 0

    def step(self):
        """Simulates one clock cycle of the FSM, updating state and registers."""
        self.sim_time += 1
        
        # Simulate internal task completion signals for the current cycle.
        self._simulate_internal_tasks()

        # Store current state and address to determine next.
        next_state_reg = self.current_state_reg
        next_lut_addr_reg = self.lut_addr_reg
        
        # Read parameters from the LUT entry at the current address.
        current_lut_data = self._get_lut_data_at_addr(self.lut_addr_reg)
        self.next_state_from_lut = self.state_encoding_map[current_lut_data['next_state']]
        for field in self.param_fields:
            self.current_params[field['name']] = current_lut_data.get(field['name'], 0) # Use .get with default for robustness
        
        current_eof = self.current_params.get('eof', 0) # Get EOF bit from current command.

        # FSM state transition logic.
        if self.current_state_reg == self.state_encoding_map['RST']:
            # From RST, transition to the first state defined at LUT address 0x00.
            first_lut_data = self._get_lut_data_at_addr(0x00)
            next_state_reg = self.state_encoding_map[first_lut_data['next_state']]
            next_lut_addr_reg = 0x00 # Initialize address for sequence execution.

        elif self.current_state_reg == self.state_encoding_map['IDLE']:
            # In IDLE, determine the next address and state based on the 'eof' bit of the *just completed* command.
            if current_eof == 1: # If the command that led to IDLE was EOF.
                self.sequence_completion_count += 1 # Increment full sequence completion count.
                next_lut_addr_reg = 0x00 # Loop back to the start of the sequence.
                next_lut_data = self._get_lut_data_at_addr(0x00)
                next_state_reg = self.state_encoding_map[next_lut_data['next_state']]
            else:
                # Move to the next command in the sequence.
                next_lut_addr_reg = self.lut_addr_reg + 1
                next_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                next_state_reg = self.state_encoding_map[next_lut_data['next_state']]
        
        else: # For other command states (PANEL_STABLE, BACK_BIAS, etc.).
            transition_condition = False
            current_state_name = self.encoding_state_map.get(self.current_state_reg)

            # Define specific transition conditions for each state.
            if current_state_name == "PANEL_STABLE" and self.internal_sensor_stable:
                transition_condition = True
            elif current_state_name == "BACK_BIAS" and self.internal_task_done:
                transition_condition = True
            elif current_state_name == "FLUSH" and self.internal_task_done:
                transition_condition = True
            elif current_state_name == "EXPOSE_TIME" and self.internal_task_done:
                transition_condition = True
            elif current_state_name == "READOUT" and self.internal_task_done and self.internal_adc_ready:
                transition_condition = True
            elif current_state_name == "AED_DETECT" and self.internal_aed_detected:
                transition_condition = True
            
            if transition_condition:
                next_state_reg = self.state_encoding_map['IDLE'] # Transition to IDLE to fetch next command.
            else:
                next_state_reg = self.current_state_reg # Stay in the current state.

        # Update FSM state and LUT address registers.
        self.current_state_reg = next_state_reg
        self.lut_addr_reg = next_lut_addr_reg

    def get_display_info(self):
        """Returns simplified FSM information for display."""
        current_state_name = self.encoding_state_map.get(self.current_state_reg, "UNKNOWN")
        
        # Calculate the next LUT address that would be used if the FSM transitions to IDLE.
        display_next_addr = self.lut_addr_reg
        if current_state_name == "IDLE":
            if self.current_params.get('eof', 0) == 1:
                display_next_addr = 0x00
            else:
                display_next_addr = self.lut_addr_reg + 1

        return {
            'time': self.sim_time,
            'state': current_state_name,
            'current_addr': self.lut_addr_reg,
            'next_addr_after_idle_logic': display_next_addr,
            'repeat_count': self.current_params.get('repeat_count', 0),
            'data_length': self.current_params.get('data_length', 0),
            'eof': self.current_params.get('eof', 0),
            'sof': self.current_params.get('sof', 0)
        }

    def print_header(self):
        """Prints the header for the simulation output."""
        print(f"{'Time':<4} | {'State':<12} | {'Addr':<4} | {'NextAddr':<8} | {'Repeat':<6} | {'Length':<6} | {'EOF':<3} | {'SOF':<3}")
        print("-" * 80)

    def print_line(self, info):
        """Prints a single line of simulation status."""
        print(f"{info['time']:<4} | {info['state']:<12} | {info['current_addr']:#04x} | {info['next_addr_after_idle_logic']:#08x} | {info['repeat_count']:<6} | {info['data_length']:<6} | {info['eof']:<3} | {info['sof']:<3}")

    def generate_report(self):
        """Generates a summary report of the simulation."""
        report = []
        report.append("\n--- Simulation Report ---")
        report.append(f"FSM Name: {self.fsm_name}")
        report.append(f"Total Simulation Time: {self.sim_time} cycles")
        report.append(f"Number of Full Sequence Completions (EOF detected and looped to 0x00): {self.sequence_completion_count}")
        
        if self.warnings:
            report.append("\n--- Warnings during Simulation ---")
            for warn in self.warnings:
                report.append(f"- {warn}")
        else:
            report.append("\nNo warnings reported during simulation.")

        report.append("\n--- Final State ---")
        report.append(f"Final State: {self.encoding_state_map.get(self.current_state_reg, 'UNKNOWN')}")
        report.append(f"Final LUT Address: {self.lut_addr_reg:#04x}")
        report.append("-------------------------")
        return "\n".join(report)


def run_simulation(fsm_config_path, lut_ram_config_path, simulation_duration=500):
    """Runs the FSM simulation."""
    fsm = SequencerFSM(fsm_config_path, lut_ram_config_path)

    print(f"\n--- Starting FSM Simulation for {fsm.fsm_name} ---")
    print("Initial State: RST. (LUT RAM is logically pre-loaded in this model)")
    print("------------------------------------------------------------------")

    fsm.print_header()

    # Print the initial RST state at time 0.
    initial_info = fsm.get_display_info()
    fsm.print_line(initial_info)
    fsm.prev_display_info = initial_info # Store for comparison.

    # Run the main simulation loop for the specified duration.
    for _ in range(simulation_duration):
        fsm.step() # Advance FSM by one clock cycle.
        current_info = fsm.get_display_info()

        # Only print if there's a significant change in state, address, or parameters.
        # This reduces redundant output when FSM is simply waiting in a state.
        if (current_info['state'] != fsm.prev_display_info['state'] or
            current_info['current_addr'] != fsm.prev_display_info['current_addr'] or
            current_info['next_addr_after_idle_logic'] != fsm.prev_display_info['next_addr_after_idle_logic'] or
            current_info['repeat_count'] != fsm.prev_display_info['repeat_count'] or
            current_info['data_length'] != fsm.prev_display_info['data_length'] or
            current_info['eof'] != fsm.prev_display_info['eof'] or
            current_info['sof'] != fsm.prev_display_info['sof']):
            
            fsm.print_line(current_info)
        
        fsm.prev_display_info = current_info # Update for next comparison.

        # Optional: Add conditions to stop simulation early, e.g., after N sequence completions.
        # if fsm.sequence_completion_count >= 3:
        #     logging.info(f"\n--- Stopping simulation early after {fsm.sequence_completion_count} sequence completions ---")
        #     break

    print(f"\n--- Simulation Output End ---")
    print(fsm.generate_report())


if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"

    # Run the simulation for a specified number of cycles.
    run_simulation(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, simulation_duration=500)