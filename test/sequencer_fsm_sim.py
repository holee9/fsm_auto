import yaml

class SequencerFSMSim:
    """
    Python simulation model for sequencer_fsm.sv.
    Simulates FSM state transitions, LUT command execution, repeat, timer, next_address field logic, and exit_signal handling.
    """
    def __init__(self, fsm_config_path, lut_ram_path):
        """
        Initialize FSM simulator with YAML configuration files.
        """
        with open(fsm_config_path, 'r') as f:
            self.fsm_config = yaml.safe_load(f)
        with open(lut_ram_path, 'r') as f:
            self.lut_ram_config = yaml.safe_load(f)

        # State encoding mapping
        self.state_encoding_map = {s['name']: int(s['encoding']) for s in self.fsm_config['states']}
        self.encoding_state_map = {int(s['encoding']): s['name'] for s in self.fsm_config['states']}
        self.state_width = self.fsm_config['state_encoding_width']

        # LUT parameter fields and entries
        self.param_fields = self.lut_ram_config['lut_ram_config']['param_fields']
        def parse_address(addr):
            if isinstance(addr, str):
                return int(addr, 0)
            return addr
        self.lut_entries = {parse_address(e['address']): e for e in self.lut_ram_config['lut_entries']}
        self.address_width = self.lut_ram_config['lut_ram_config']['address_width']

        self.reset()

    def reset(self):
        """
        Reset FSM to initial state.
        """
        self.current_state = self.state_encoding_map['RST']
        self.lut_addr = 0
        self.repeat_count = 0
        self.data_length = 0
        self.eof = 0
        self.sof = 0
        self.next_address = 0
        self.busy = False
        self.sequence_done = False
        self.cycle = 0
        self.load_lut_entry(self.lut_addr)
        self.data_length_timer = self.data_length
        self.active_repeat_count = self.repeat_count
        self.exit_signal_latched = False
        self.exit_signal = False

    def load_lut_entry(self, addr):
        """
        Load LUT entry at given address and update command parameters.
        """
        entry = self.lut_entries.get(addr, None)
        if entry is None:
            # Default: go to RST
            self.next_state = self.state_encoding_map['RST']
            self.repeat_count = 1
            self.data_length = 1
            self.eof = 0
            self.sof = 0
            self.next_address = 0
        else:
            self.next_state = self.state_encoding_map[entry['next_state']]
            self.repeat_count = entry['repeat_count']
            self.data_length = entry['data_length']
            self.eof = entry['eof']
            self.sof = entry['sof']
            self.next_address = entry.get('next_address', (addr + 1) & ((1 << self.address_width) - 1))

    def step(self, reset_i=0, exit_signal=False):
        """
        Simulate one FSM clock cycle. If reset_i is asserted, reset FSM.
        Implements repeat_count, data_length_timer, exit_signal, and sequence_done logic exactly as the module.
        Returns True if a new LUT entry is loaded or repeat/exit/sequence_done is active, else False.
        """
        self.cycle += 1
        self.sequence_done = False
        printed = False
        if exit_signal:
            self.exit_signal_latched = True
        self.exit_signal = exit_signal

        if reset_i:
            self.reset()
            return True

        # RST state: on reset deassert, enter first command
        if self.current_state == self.state_encoding_map['RST']:
            self.lut_addr = 0
            self.load_lut_entry(self.lut_addr)
            self.current_state = self.next_state
            self.data_length_timer = self.data_length
            self.active_repeat_count = self.repeat_count
            self.lut_addr = self.next_address
            printed = True
            return printed

        # Command execution state (not IDLE)
        if self.current_state != self.state_encoding_map['IDLE']:
            if self.data_length_timer > 0:
                self.data_length_timer -= 1

            # On command completion
            if self.data_length_timer == 0:
                if self.active_repeat_count > 0:
                    self.active_repeat_count -= 1
                    self.data_length_timer = self.data_length
                    printed = True
                else:
                    self.current_state = self.state_encoding_map['IDLE']
                    printed = True

        # IDLE state: always load next command
        else:
            if self.eof == 1 and self.exit_signal_latched:
                self.lut_addr = (self.lut_addr + 1) & ((1 << self.address_width) - 1)
                self.sequence_done = True
                self.exit_signal_latched = False
            else:
                self.lut_addr = self.next_address
                self.sequence_done = False
            self.load_lut_entry(self.lut_addr)
            self.current_state = self.next_state
            self.data_length_timer = self.data_length
            self.active_repeat_count = self.repeat_count
            printed = True

        return printed or self.exit_signal or self.sequence_done

    def get_outputs(self):
        """
        Return current FSM outputs as a dictionary.
        """
        state_name = self.encoding_state_map[self.current_state]
        return {
            'cycle': self.cycle,
            'state': state_name,
            'addr': self.lut_addr,
            'next_addr': self.next_address,
            'repeat_count': self.repeat_count,
            'active_repeat_count': self.active_repeat_count,
            'data_length': self.data_length,
            'data_length_timer': self.data_length_timer,
            'eof': self.eof,
            'sof': self.sof,
            'sequence_done': self.sequence_done,
            'exit_signal': int(self.exit_signal)
        }

if __name__ == "__main__":
    fsm_config_path = "fsm_config.yaml"
    lut_ram_path = "fsm_lut_ram_data.yaml"
    sim = SequencerFSMSim(fsm_config_path, lut_ram_path)

    print("cycle | state         | addr | next_addr | repeat | active_r | length | timer | eof | sof | done | exit")
    print("---------------------------------------------------------------------------------------------------")
    for i in range(2000):
        exit_signal = (i == 1000 or i == 1500 or i == 1700)
        printed = sim.step(reset_i=1 if i == 0 else 0, exit_signal=exit_signal)
        out = sim.get_outputs()
        if printed:
            print(f"{out['cycle']:5} | {out['state']:12} | {out['addr']:4} | {out['next_addr']:9} | {out['repeat_count']:6} | {out['active_repeat_count']:8} | {out['data_length']:6} | {out['data_length_timer']:5} | {out['eof']:3} | {out['sof']:3} | {int(out['sequence_done']):4} | {out['exit_signal']:4}") 