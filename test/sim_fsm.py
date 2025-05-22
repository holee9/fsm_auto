import yaml
import logging
import os
import sys

# Configure logging to prevent unnecessary output during normal simulation.
# Logging level is set to WARNING, so only significant issues will be reported.
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

class SequencerFSM:
    """
    Python model of the Sequencer FSM for rapid simulation.
    Simulates FSM state transitions based on LUT data and internal task completions.
    """
    def __init__(self, fsm_config_path, lut_ram_config_path):
        if not os.path.exists(fsm_config_path):
            logging.error(f"FSM configuration file not found at {fsm_config_path}")
            sys.exit(1)
        if not os.path.exists(lut_ram_config_path):
            logging.error(f"LUT RAM data file not found at {lut_ram_config_path}")
            sys.exit(1)

        with open(fsm_config_path, 'r') as f:
            self.fsm_config = yaml.safe_load(f)
        with open(lut_ram_config_path, 'r') as f:
            self.lut_ram_config = yaml.safe_load(f)

        self.fsm_name = self.fsm_config['fsm_name']
        self.state_width = self.fsm_config['state_encoding_width']
        self.states_data = self.fsm_config['states']
        
        self.state_encoding_map = {state['name']: state['encoding'] for state in self.states_data}
        self.encoding_state_map = {encoding: name for name, encoding in self.state_encoding_map.items()}

        if 'RST' not in self.state_encoding_map:
            logging.error("'RST' state is not defined in fsm_config.yaml.")
            sys.exit(1)
        if 'IDLE' not in self.state_encoding_map:
            logging.error("'IDLE' state is not defined in fsm_config.yaml.")
            sys.exit(1)

        self.param_fields = self.lut_ram_config['lut_ram_config']['param_fields']
        self.lut_entries_raw = self.lut_ram_config['lut_entries']
        
        self.current_state_reg = self.state_encoding_map['RST']
        self.lut_addr_reg = 0
        self.sim_time = 0

        self.active_repeat_count = 0    
        self.data_length_timer = 0      
        self.exit_signal = False        

        self.internal_task_done = False
        self.internal_adc_ready = False
        self.internal_sensor_stable = False
        self.internal_aed_detected = False

        self.lut_ram = self._pack_lut_entries()

        # self.current_params will be explicitly loaded in step() or get_display_info
        self.current_params = {} 
        self.sequence_completion_count = 0

    def _pack_lut_entry(self, entry):
        packed_value = 0
        next_state_encoding = self.state_encoding_map[entry['next_state']]
        total_param_width = sum(field['width'] for field in self.param_fields)
        packed_value |= (next_state_encoding << total_param_width)

        bit_offset = 0
        for field in self.param_fields:
            field_name = field['name']
            field_width = field['width']
            field_value = entry[field_name]
            packed_value |= (field_value << bit_offset)
            bit_offset += field_width
        
        return packed_value

    def _unpack_lut_data(self, packed_data):
        unpacked = {}
        bit_offset = 0
        for field in self.param_fields:
            field_name = field['name']
            field_width = field['width']
            mask = (1 << field_width) - 1
            unpacked[field_name] = (packed_data >> bit_offset) & mask
            bit_offset += field_width
        
        unpacked_next_state_encoding = (packed_data >> bit_offset) & ((1 << self.state_width) - 1)
        unpacked['next_state'] = self.encoding_state_map.get(unpacked_next_state_encoding, "UNKNOWN")
        
        return unpacked

    def _pack_lut_entries(self):
        ram = {}
        for entry in self.lut_entries_raw:
            addr = entry['address']
            packed_val = self._pack_lut_entry(entry)
            ram[addr] = packed_val
        return ram

    def _get_lut_data_at_addr(self, addr):
        if addr in self.lut_ram:
            packed_val = self.lut_ram[addr]
            return self._unpack_lut_data(packed_val)
        
        logging.warning(f"Sim Time {self.sim_time}: LUT Address {addr:#04x} out of bounds or invalid. Defaulting to RST command.")
        # Return a default "safe" command if address is invalid
        return {
            'next_state': 'RST',
            'repeat_count': 1,
            'data_length': 1,
            'eof': 0,
            'sof': 0
        }

    def _simulate_internal_tasks_auto(self):
        # Reset internal task signals at the beginning of each cycle
        self.internal_task_done = False
        self.internal_adc_ready = False
        self.internal_sensor_stable = False
        self.internal_aed_detected = False

        current_state_name = self.encoding_state_map.get(self.current_state_reg)

        # Only set task done if timer has reached 0 AND current state is a command state
        if self.data_length_timer == 0:
            if current_state_name == "PANEL_STABLE":
                self.internal_sensor_stable = True
            elif current_state_name in ["BACK_BIAS", "FLUSH", "EXPOSE_TIME", "READOUT"]:
                self.internal_task_done = True
                if current_state_name == "READOUT":
                    self.internal_adc_ready = True # Specific task completion for READOUT
            elif current_state_name == "AED_DETECT":
                self.internal_aed_detected = True

    def step(self):
        self.sim_time += 1
        
        prev_current_state_reg = self.current_state_reg
        prev_lut_addr_reg = self.lut_addr_reg

        next_state_reg = self.current_state_reg
        next_lut_addr_reg = self.lut_addr_reg
        
        # Load the LUT data for the *current* lut_addr_reg.
        # This self.current_params will be used for state transition logic.
        self.current_params = self._get_lut_data_at_addr(self.lut_addr_reg)
        
        current_eof = self.current_params.get('eof', 0)
        current_command_repeat_val = self.current_params.get('repeat_count', 1)

        self._simulate_internal_tasks_auto() 

        if self.current_state_reg == self.state_encoding_map['RST']:
            next_lut_addr_reg = 0x00 # Always go to 0x00 after reset
            # Load initial parameters for the first command (0x00)
            next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
            next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
            
            self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
            self.data_length_timer = next_command_lut_data.get('data_length', 1)

            # Decrement active_repeat_count as we are now entering the command state
            if self.active_repeat_count > 0:
                self.active_repeat_count -= 1

        elif self.current_state_reg == self.state_encoding_map['IDLE']:
            # IDLE state transition logic
            # This logic determines what the FSM *will do next* from IDLE.

            # Check if the IDLE state itself is a programmed command in LUT RAM
            # A LUT-defined IDLE would have 'next_state' as 'IDLE' in its own entry.
            # This is a bit recursive, let's simplify: if current_state_reg is IDLE,
            # we check the next state *defined in the LUT entry at lut_addr_reg*.
            # If that LUT entry itself points to IDLE as next_state, it's a programmed IDLE.
            
            # Retrieve the command that the FSM is considering *from* IDLE state
            # This is the command pointed to by lut_addr_reg when in IDLE
            command_at_current_addr_from_idle = self._get_lut_data_at_addr(self.lut_addr_reg)
            
            # Determine if this IDLE is due to a direct 'IDLE' command in LUT
            # Or if it's an 'IDLE' state that is a transition after a command completes.
            # For this, we look at the 'next_state' of the current LUT address.
            # If the current LUT entry points to 'IDLE', then it's a programmed IDLE.
            is_programmed_idle_in_lut = (command_at_current_addr_from_idle['next_state'] == 'IDLE')
            
            if is_programmed_idle_in_lut:
                # If IDLE is a programmed command, its behavior depends on its own repeat_count and data_length
                # Assuming programmed IDLEs function like other commands, eventually advancing based on timer/repeat
                if self.data_length_timer > 0:
                    self.data_length_timer -= 1
                if self.data_length_timer == 0:
                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1
                        self.data_length_timer = command_at_current_addr_from_idle.get('data_length', 1)
                    else: # Programmed IDLE is done repeating/timing, move to next command
                        if command_at_current_addr_from_idle.get('eof', 0) == 1:
                            next_lut_addr_reg = 0x00
                        else:
                            next_lut_addr_reg = self.lut_addr_reg + 1
                        
                        next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                        next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                        self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
                        self.data_length_timer = next_command_lut_data.get('data_length', 1)
                        if self.active_repeat_count > 0:
                            self.active_repeat_count -= 1
                else: # Stay in programmed IDLE as timer is active
                    next_state_reg = self.state_encoding_map['IDLE']
                    next_lut_addr_reg = self.lut_addr_reg

            else: # This is a transition IDLE (after a command completes), not a programmed IDLE in LUT
                if self.active_repeat_count > 0: 
                    # If there are still repeats left for the command *that led to this IDLE*, re-enter it
                    next_lut_addr_reg = self.lut_addr_reg
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.data_length_timer = next_command_lut_data.get('data_length', 1) # Reset timer for this repeat
                    
                    self.active_repeat_count -= 1

                elif current_command_repeat_val == 0 and self.exit_signal:
                    # Infinite repeat with exit signal, move to next address
                    next_lut_addr_reg = self.lut_addr_reg + 1
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)
                    self.exit_signal = False

                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

                elif current_command_repeat_val == 0:
                    # Infinite repeat, no exit signal.
                    # Assume it re-enters the command if it's an infinite loop.
                    next_lut_addr_reg = self.lut_addr_reg
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)


                elif current_eof == 1:
                    # End of sequence, loop back to 0x00
                    self.sequence_completion_count += 1
                    next_lut_addr_reg = 0x00
                    first_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[first_lut_data['next_state']]
                    self.active_repeat_count = first_lut_data.get('repeat_count', 1)
                    self.data_length_timer = first_lut_data.get('data_length', 1)

                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

                else: 
                    # Move to the next sequential address
                    next_lut_addr_reg = self.lut_addr_reg + 1
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)

                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

        else: # Command states (e.g., PANEL_STABLE, BACK_BIAS, FLUSH, EXPOSE_TIME, READOUT, AED_DETECT)
            if self.data_length_timer > 0:
                self.data_length_timer -= 1

            is_task_done = False
            current_state_name = self.encoding_state_map.get(self.current_state_reg)

            # Check if internal task is done, based on current state and timer
            if self.data_length_timer == 0: # Only check task completion if timer has expired
                if current_state_name == "PANEL_STABLE" and self.internal_sensor_stable:
                    is_task_done = True
                elif current_state_name == "BACK_BIAS" and self.internal_task_done:
                    is_task_done = True
                elif current_state_name == "FLUSH" and self.internal_task_done:
                    is_task_done = True
                elif current_state_name == "EXPOSE_TIME" and self.internal_task_done:
                    is_task_done = True
                elif current_state_name == "READOUT" and self.internal_task_done and self.internal_adc_ready:
                    is_task_done = True
                elif current_state_name == "AED_DETECT" and self.internal_aed_detected:
                    is_task_done = True
            
            if is_task_done:
                next_state_reg = self.state_encoding_map['IDLE'] # Transition to IDLE upon task completion
            else:
                next_state_reg = self.current_state_reg # Remain in current command state

        self.current_state_reg = next_state_reg
        self.lut_addr_reg = next_lut_addr_reg

        current_info = self.get_display_info()
        should_print = False

        # Determine if a line should be printed based on state or address change
        if self.sim_time == 1: # Always print the first active state
            should_print = True
        elif current_info['state'] != self.encoding_state_map.get(prev_current_state_reg, "UNKNOWN"):
            should_print = True
        elif current_info['current_addr'] != prev_lut_addr_reg and (self.encoding_state_map.get(prev_current_state_reg) != 'IDLE' or current_info['state'] != 'IDLE'): 
            should_print = True # Print if address changes, unless previous was IDLE and current is also IDLE (handled by state change)
        elif current_info['state'] == 'IDLE' and self.encoding_state_map.get(prev_current_state_reg, "UNKNOWN") != 'IDLE':
            should_print = True # Always print when entering IDLE state
        elif current_info['state'] == 'IDLE' and current_info['current_addr'] != prev_lut_addr_reg: # Print IDLE if its address changes
            should_print = True
        elif self.encoding_state_map.get(prev_current_state_reg) == 'IDLE' and current_info['state'] == 'IDLE' and \
             (self.data_length_timer != fsm.get_display_info()['timer_A'] or self.active_repeat_count != fsm.get_display_info()['active_repeat']):
             should_print = True # If staying in IDLE, print if timer or repeat count changes.

        
        if should_print:
            self.print_line(current_info)

    def get_display_info(self):
        current_state_name = self.encoding_state_map.get(self.current_state_reg, "UNKNOWN")
        
        # Initialize all fields as empty strings by default
        display_current_addr = ""
        display_next_addr = ""
        display_repeat_L = ""
        display_active_repeat = ""
        display_length_L = ""
        display_timer_A = ""
        display_eof = ""
        display_sof = ""
        
        if self.current_state_reg == self.state_encoding_map['RST']:
            # RST state: Addr and NextAddr are fixed to 0x00. All others blank.
            display_current_addr = 0x00
            display_next_addr = 0x00 
            # All other fields (LUT parameters and internal counters) remain blank for RST state.
            
        elif self.current_state_reg == self.state_encoding_map['IDLE']:
            # Check if this IDLE state is defined as a specific command in LUT RAM
            # by checking if the LUT entry at current_addr_reg actually points to IDLE as its next_state.
            # This is a bit ambiguous in standard FSMs, but let's assume if the current_params
            # at self.lut_addr_reg have 'next_state' as 'IDLE', it's a programmed IDLE.
            # This means the *current* LUT entry defines this IDLE's behavior.
            
            # To handle the case where IDLE is a programmed command (e.g., for a fixed delay)
            # We need to distinguish this from an IDLE that's just a transition state after a command.
            
            # Let's check the LUT entry for the *current* address (`self.lut_addr_reg`).
            # If this LUT entry's `next_state` parameter is 'IDLE', then it's a programmed IDLE.
            # Otherwise, it's a transient IDLE after a command finishes.

            # Important: The `self.current_params` has already been loaded from `self.lut_addr_reg` in `step()`.
            # We can use `self.current_params['next_state']` to check if the current LUT entry points to IDLE.
            
            is_programmed_idle_in_lut = (self.current_params.get('next_state') == 'IDLE')
            
            if is_programmed_idle_in_lut:
                # This is a programmed IDLE command in LUT RAM. Display its parameters.
                display_current_addr = self.lut_addr_reg
                
                # The next_addr for a programmed IDLE follows its own logic.
                # If its timer/repeat is not done, it stays at current_addr.
                # If done, it follows its EOF or moves to next sequential.
                
                if self.data_length_timer > 0 or self.active_repeat_count > 0: # Still active within the IDLE command
                    display_next_addr = self.lut_addr_reg
                elif self.current_params.get('eof', 0) == 1:
                    display_next_addr = 0x00
                else:
                    display_next_addr = self.lut_addr_reg + 1
                
                display_repeat_L = self.current_params.get('repeat_count', 1)
                display_length_L = self.current_params.get('data_length', 1)
                display_eof = self.current_params.get('eof', 0)
                display_sof = self.current_params.get('sof', 0)
                
            else:
                # This is a transition IDLE. Addresses and LUT params are blank.
                # 'Addr' and 'NextAddr' would refer to the *command that just finished* or *next command*.
                # As per customer request, for transition IDLE, these should be blank.
                display_current_addr = ""
                display_next_addr = ""
                # LUT parameters are also blank.
                
            # For both types of IDLE, internal FSM counters are always displayed.
            display_active_repeat = self.active_repeat_count 
            display_timer_A = self.data_length_timer 

        else: # All other Command states (PANEL_STABLE, BACK_BIAS, FLUSH, EXPOSE_TIME, READOUT, AED_DETECT)
            # In command states, display all parameters loaded from LUT RAM and internal counters.
            display_current_addr = self.lut_addr_reg
            
            current_command_lut_data = self._get_lut_data_at_addr(self.lut_addr_reg)
            display_repeat_L = current_command_lut_data.get('repeat_count', 1)
            display_length_L = current_command_lut_data.get('data_length', 1)
            display_eof = current_command_lut_data.get('eof', 0)
            display_sof = current_command_lut_data.get('sof', 0)

            display_active_repeat = self.active_repeat_count 
            display_timer_A = self.data_length_timer 

            # Calculate next_addr for command states based on the *current* LUT data logic
            # This reflects where the FSM *will go* after this command (and its repeats) are done.
            if display_active_repeat == 0: # If this is the last repeat (or non-repeating command)
                if display_eof == 1:
                    display_next_addr = 0x00
                elif display_repeat_L == 0 and self.exit_signal: # Infinite repeat with exit signal
                    display_next_addr = self.lut_addr_reg + 1
                elif display_repeat_L == 0: # Infinite repeat, no exit signal - will loop back to same address
                    display_next_addr = self.lut_addr_reg
                else: # Finite repeats done, move to next sequential address
                    display_next_addr = self.lut_addr_reg + 1
            else: # Still repeating this command, so next address will be the same
                display_next_addr = self.lut_addr_reg


        return {
            'time': self.sim_time,
            'state': current_state_name,
            'current_addr': display_current_addr,
            'next_addr': display_next_addr,
            'repeat_L': display_repeat_L, 
            'active_repeat': display_active_repeat,
            'length_L': display_length_L, 
            'timer_A': display_timer_A,
            'eof': display_eof,
            'sof': display_sof
        }

    def print_header(self):
        print(f"{'Time':<4} | {'State':<14} | {'Addr':<4} | {'NextAddr':<8} | {'Repeat(L)':<9} | {'Repeat(A)':<11} | {'Length(L)':<9} | {'Timer(A)':<9} | {'EOF':<3} | {'SOF':<3}")
        print("-" * 115)

    def print_line(self, info):
        # Use str() to handle both integers and empty strings gracefully in f-strings
        # Format addresses with #04x or #08x if they are integers, otherwise keep as string
        formatted_current_addr = f"{info['current_addr']:#04x}" if isinstance(info['current_addr'], int) else str(info['current_addr'])
        formatted_next_addr = f"{info['next_addr']:#08x}" if isinstance(info['next_addr'], int) else str(info['next_addr'])

        print(f"{info['time']:<4} | {info['state']:<14} | {formatted_current_addr:<4} | {formatted_next_addr:<8} | {str(info['repeat_L']):<9} | {str(info['active_repeat']):<11} | {str(info['length_L']):<9} | {str(info['timer_A']):<9} | {str(info['eof']):<3} | {str(info['sof']):<3}")

    def generate_report(self):
        report = []
        report.append("\n--- Simulation Report ---")
        report.append(f"FSM Name: {self.fsm_name}")
        report.append(f"Total Simulation Time: {self.sim_time} cycles")
        report.append(f"Number of Full Sequence Completions (EOF detected and looped to 0x00): {self.sequence_completion_count}")
        report.append("\nNo warnings reported during simulation.")
        report.append("\n--- Final State ---")
        report.append(f"Final State: {self.encoding_state_map.get(self.current_state_reg, 'UNKNOWN')}")
        report.append(f"Final LUT Address: {self.lut_addr_reg:#04x}")
        report.append(f"Final Active Repeat Count: {self.active_repeat_count}")
        report.append(f"Final Data Length Timer: {self.data_length_timer}")
        report.append("-------------------------")
        return "\n".join(report)


def run_simulation(fsm_config_path, lut_ram_config_path, simulation_duration=5000):
    fsm = SequencerFSM(fsm_config_path, lut_ram_config_path)

    print(f"\n--- Starting FSM Simulation for {fsm.fsm_name} ---")
    print("Initial State: RST.")
    print("------------------------------------------------------------------")

    fsm.print_header()

    # Print initial RST state at time 0.
    fsm.print_line(fsm.get_display_info())

    for _ in range(1, simulation_duration + 1):
        fsm.step()
        # Ensure the very last state is printed if not already printed by step()
        if fsm.sim_time == simulation_duration:
            fsm.print_line(fsm.get_display_info())

    print(f"\n--- Simulation Output End ---")
    print(fsm.generate_report())


if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"

    run_simulation(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, simulation_duration=3000)