import yaml
import logging
import os
import sys

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
        return {
            'next_state': 'RST',
            'repeat_count': 1,
            'data_length': 1,
            'eof': 0,
            'sof': 0
        }

    def _simulate_internal_tasks_auto(self):
        self.internal_task_done = False
        self.internal_adc_ready = False
        self.internal_sensor_stable = False
        self.internal_aed_detected = False

        current_state_name = self.encoding_state_map.get(self.current_state_reg)

        if self.data_length_timer == 0:
            if current_state_name == "PANEL_STABLE":
                self.internal_sensor_stable = True
            elif current_state_name in ["BACK_BIAS", "FLUSH", "EXPOSE_TIME", "READOUT", "IDLE"]:
                self.internal_task_done = True
                if current_state_name == "READOUT":
                    self.internal_adc_ready = True
            elif current_state_name == "AED_DETECT":
                self.internal_aed_detected = True

    def step(self):
        self.sim_time += 1

        prev_current_state_reg = self.current_state_reg
        prev_lut_addr_reg = self.lut_addr_reg
        prev_idle_type = ""
        if self.current_state_reg == self.state_encoding_map['IDLE']:
            prev_params = self._get_lut_data_at_addr(self.lut_addr_reg)
            prev_idle_type = "Programmed IDLE" if prev_params.get('next_state') == 'IDLE' else "Transition IDLE"

        next_state_reg = self.current_state_reg
        next_lut_addr_reg = self.lut_addr_reg

        self.current_params = self._get_lut_data_at_addr(self.lut_addr_reg)

        current_eof = self.current_params.get('eof', 0)
        current_command_repeat_val = self.current_params.get('repeat_count', 1)

        self._simulate_internal_tasks_auto()

        if self.current_state_reg == self.state_encoding_map['RST']:
            next_lut_addr_reg = 0x00
            next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
            next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
            self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
            self.data_length_timer = next_command_lut_data.get('data_length', 1)
            if self.active_repeat_count > 0:
                self.active_repeat_count -= 1

        elif self.current_state_reg == self.state_encoding_map['IDLE']:
            command_at_current_addr_from_idle = self._get_lut_data_at_addr(self.lut_addr_reg)
            is_programmed_idle_in_lut = (command_at_current_addr_from_idle['next_state'] == 'IDLE')

            if is_programmed_idle_in_lut:
                if self.data_length_timer > 0:
                    self.data_length_timer -= 1
                if self.data_length_timer == 0:
                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1
                        self.data_length_timer = command_at_current_addr_from_idle.get('data_length', 1)
                    else:
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
                else:
                    next_state_reg = self.state_encoding_map['IDLE']
                    next_lut_addr_reg = self.lut_addr_reg

            else:
                if self.active_repeat_count > 0:
                    next_lut_addr_reg = self.lut_addr_reg
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)
                    self.active_repeat_count -= 1

                elif current_command_repeat_val == 0 and self.exit_signal:
                    next_lut_addr_reg = self.lut_addr_reg + 1
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)
                    self.exit_signal = False
                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

                elif current_command_repeat_val == 0:
                    next_lut_addr_reg = self.lut_addr_reg
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)

                elif current_eof == 1:
                    self.sequence_completion_count += 1
                    next_lut_addr_reg = 0x00
                    first_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[first_lut_data['next_state']]
                    self.active_repeat_count = first_lut_data.get('repeat_count', 1)
                    self.data_length_timer = first_lut_data.get('data_length', 1)
                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

                else:
                    next_lut_addr_reg = self.lut_addr_reg + 1
                    next_command_lut_data = self._get_lut_data_at_addr(next_lut_addr_reg)
                    next_state_reg = self.state_encoding_map[next_command_lut_data['next_state']]
                    self.active_repeat_count = next_command_lut_data.get('repeat_count', 1)
                    self.data_length_timer = next_command_lut_data.get('data_length', 1)
                    if self.active_repeat_count > 0:
                        self.active_repeat_count -= 1

        else:
            if self.data_length_timer > 0:
                self.data_length_timer -= 1

            is_task_done = False
            current_state_name = self.encoding_state_map.get(self.current_state_reg)

            if self.data_length_timer == 0:
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
                elif current_state_name == "IDLE" and self.internal_task_done:
                    is_task_done = True
                elif current_state_name == "AED_DETECT" and self.internal_aed_detected:
                    is_task_done = True

            if is_task_done:
                next_state_reg = self.state_encoding_map['IDLE']
            else:
                next_state_reg = self.current_state_reg

        self.current_state_reg = next_state_reg
        self.lut_addr_reg = next_lut_addr_reg

        current_info = self.get_display_info()
        should_print = False

        if self.sim_time == 1:
            should_print = True
        elif current_info['state'] != self.encoding_state_map.get(prev_current_state_reg, "UNKNOWN"):
            should_print = True
        elif current_info['current_addr'] != prev_lut_addr_reg and (self.encoding_state_map.get(prev_current_state_reg) != 'IDLE' or current_info['state'] != 'IDLE'):
            should_print = True
        elif current_info['state'] == 'IDLE' and self.encoding_state_map.get(prev_current_state_reg, "UNKNOWN") != 'IDLE':
            should_print = True
        elif current_info['state'] == 'IDLE' and current_info['current_addr'] != prev_lut_addr_reg:
            should_print = True
        elif current_info['state'] == 'IDLE' and self.encoding_state_map.get(prev_current_state_reg) == 'IDLE' and current_info['idle_type'] != prev_idle_type:
            should_print = True
        elif self.encoding_state_map.get(prev_current_state_reg) == 'IDLE' and current_info['state'] == 'IDLE' and (self.data_length_timer != self.get_display_info()['timer_A'] or self.active_repeat_count != self.get_display_info()['active_repeat']):
            should_print = True

        if should_print:
            self.print_line(current_info)

    def get_display_info(self):
        current_state_name = self.encoding_state_map.get(self.current_state_reg, "UNKNOWN")

        display_current_addr = ""
        display_next_addr = ""
        display_repeat_L = ""
        display_active_repeat = ""
        display_length_L = ""
        display_timer_A = ""
        display_eof = ""
        display_sof = ""
        display_idle_type = ""

        if self.current_state_reg == self.state_encoding_map['RST']:
            display_current_addr = 0x00
            display_next_addr = 0x00

        elif self.current_state_reg == self.state_encoding_map['IDLE']:
            current_lut_params = self._get_lut_data_at_addr(self.lut_addr_reg)
            is_programmed_idle_in_lut = (current_lut_params.get('next_state') == 'IDLE')

            if is_programmed_idle_in_lut:
                display_idle_type = "Programmed IDLE"
                display_current_addr = self.lut_addr_reg
                if self.data_length_timer > 0 or self.active_repeat_count > 0:
                    display_next_addr = self.lut_addr_reg
                elif current_lut_params.get('eof', 0) == 1:
                    display_next_addr = 0x00
                else:
                    display_next_addr = self.lut_addr_reg + 1

                display_repeat_L = current_lut_params.get('repeat_count', 1)
                display_length_L = current_lut_params.get('data_length', 1)
                display_eof = current_lut_params.get('eof', 0)
                display_sof = current_lut_params.get('sof', 0)

            else:
                display_idle_type = "Transition IDLE"
                display_current_addr = ""
                display_next_addr = ""
            display_active_repeat = self.active_repeat_count
            display_timer_A = self.data_length_timer

        else:
            display_current_addr = self.lut_addr_reg
            current_command_lut_data = self._get_lut_data_at_addr(self.lut_addr_reg)
            display_repeat_L = current_command_lut_data.get('repeat_count', 1)
            display_length_L = current_command_lut_data.get('data_length', 1)
            display_eof = current_command_lut_data.get('eof', 0)
            display_sof = current_command_lut_data.get('sof', 0)
            display_active_repeat = self.active_repeat_count
            display_timer_A = self.data_length_timer
            if display_active_repeat == 0:
                if display_eof == 1:
                    display_next_addr = 0x00
                elif display_repeat_L == 0 and self.exit_signal:
                    display_next_addr = self.lut_addr_reg + 1
                elif display_repeat_L == 0:
                    display_next_addr = self.lut_addr_reg
                else:
                    display_next_addr = self.lut_addr_reg + 1
            else:
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
            'sof': display_sof,
            'idle_type': display_idle_type
        }

    def print_header(self):
        print(f"{'Time':<4} | {'State':<14} | {'Addr':<4} | {'NextAddr':<8} | {'Repeat(L)':<9} | {'Repeat(A)':<11} | {'Length(L)':<9} | {'Timer(A)':<9} | {'EOF':<3} | {'SOF':<3} | {'Type':<15}")
        print("-" * 135)

    def print_line(self, info):
        formatted_current_addr = f"{info['current_addr']:#04x}" if isinstance(info['current_addr'], int) else str(info['current_addr'])
        formatted_next_addr = f"{info['next_addr']:#08x}" if isinstance(info['next_addr'], int) else str(info['next_addr'])
        idle_type_display = info['idle_type'] if info['state'] == 'IDLE' else ""
        print(f"{info['time']:<4} | {info['state']:<14} | {formatted_current_addr:<4} | {formatted_next_addr:<8} | {str(info['repeat_L']):<9} | {str(info['active_repeat']):<11} | {str(info['length_L']):<9} | {str(info['timer_A']):<9} | {str(info['eof']):<3} | {str(info['sof']):<3} | {idle_type_display:<15}")

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
    fsm.print_line(fsm.get_display_info())
    for _ in range(1, simulation_duration + 1):
        fsm.step()
        if fsm.sim_time == simulation_duration:
            fsm.print_line(fsm.get_display_info())
    print(f"\n--- Simulation Output End ---")
    print(fsm.generate_report())

if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"
    run_simulation(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, simulation_duration=3000)
