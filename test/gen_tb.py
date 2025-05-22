import yaml
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_testbench(fsm_config_path, lut_ram_config_path, tb_output_file):
    """
    Generates a SystemVerilog testbench for the sequencer_fsm module.
    This testbench will:
    1. Generate clock and reset.
    2. Load LUT RAM data into the DUT's internal RAM during the RST state.
    3. Monitor FSM state and outputs.
    4. Terminate simulation.
    """
    # Check if config files exist
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
    
    state_encoding_map = {state['name']: state['encoding'] for state in states_data}

    lut_address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    lut_entries = lut_ram_config['lut_entries']
    
    # Calculate lut_data_width
    total_param_width = sum(field['width'] for field in param_fields)
    lut_data_width = state_width + total_param_width 

    tb_code = []
    tb_code.append(f"`timescale 1ns / 1ps")
    tb_code.append(f"")
    tb_code.append(f"module {fsm_name}_tb;")
    tb_code.append(f"")
    
    # Testbench Signals
    tb_code.append(f"    // Testbench Signals")
    tb_code.append(f"    logic clk;")
    tb_code.append(f"    logic reset_i;")
    tb_code.append(f"    logic lut_wen_i;")
    tb_code.append(f"    logic [{lut_data_width-1}:0] lut_write_data_i;")
    tb_code.append(f"    logic lut_rden_i;")
    tb_code.append(f"")
    
    # DUT Outputs (to be connected to TB wires)
    tb_code.append(f"    // DUT Outputs (connected to TB wires/logics)")
    tb_code.append(f"    logic [{state_width-1}:0] current_state_o;")
    tb_code.append(f"    logic busy_o;")
    tb_code.append(f"    logic sequence_done_o;")
    tb_code.append(f"    logic [{lut_data_width-1}:0] lut_read_data_o;")
    
    # Other FSM outputs
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] or out['name'].startswith('current_'):
            continue
        tb_code.append(f"    logic {out['name']};")
    
    # Outputs for LUT parameters (current values)
    for field in param_fields:
        tb_code.append(f"    logic [{field['width']-1}:0] current_{field['name']}_o;")
    tb_code.append(f"")

    # Instantiate DUT
    tb_code.append(f"    // Instantiate Device Under Test (DUT)")
    tb_code.append(f"    {fsm_name} dut (")
    tb_code.append(f"        .clk(clk),")
    tb_code.append(f"        .reset_i(reset_i),")
    tb_code.append(f"        .lut_wen_i(lut_wen_i),")
    tb_code.append(f"        .lut_write_data_i(lut_write_data_i),")
    tb_code.append(f"        .lut_rden_i(lut_rden_i),")
    tb_code.append(f"        .current_state_o(current_state_o),")
    tb_code.append(f"        .busy_o(busy_o),")
    tb_code.append(f"        .sequence_done_o(sequence_done_o),")
    tb_code.append(f"        .lut_read_data_o(lut_read_data_o),")
    
    # Connect other outputs
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] or out['name'].startswith('current_'):
            continue
        tb_code.append(f"        .{out['name']}({out['name']}),")
    
    # Connect current_param_o outputs
    for field in param_fields:
        tb_code.append(f"        .current_{field['name']}_o(current_{field['name']}_o),")

    # Remove the last comma and close parentheses
    if tb_code[-1].endswith(','):
        tb_code[-1] = tb_code[-1][:-1]
    tb_code.append(f"    );")
    tb_code.append(f"")

    # Clock Generation
    tb_code.append(f"    // Clock Generation")
    tb_code.append(f"    always #5 clk = ~clk; // 10ns period, 100MHz clock")
    tb_code.append(f"")

    # Main Test Sequence
    tb_code.append(f"    // Main Test Sequence")
    tb_code.append(f"    initial begin")
    tb_code.append(f"        clk = 1'b0;")
    tb_code.append(f"        reset_i = 1'b1; // Assert reset")
    tb_code.append(f"        lut_wen_i = 1'b0;")
    tb_code.append(f"        lut_rden_i = 1'b0;")
    tb_code.append(f"        lut_write_data_i = '0;")
    tb_code.append(f"")
    tb_code.append(f"        #100; // Hold reset for a while")
    tb_code.append(f"")
    
    tb_code.append(f"        // --- LUT RAM Configuration (during RST state) ---")
    tb_code.append(f"        $display(\"\\n--- Initializing LUT RAM ---\");")
    tb_code.append(f"        reset_i = 1'b1; // Ensure reset is high for LUT write")
    tb_code.append(f"        lut_wen_i = 1'b1; // Enable LUT write")
    tb_code.append(f"        lut_rden_i = 1'b0; // Disable LUT read during write")
    tb_code.append(f"")

    # Generate LUT RAM write sequence
    # For each entry, pack data and write
    for entry in lut_entries:
        addr = entry['address']
        next_state_encoding = state_encoding_map[entry['next_state']]
        
        # Build lut_write_data_i
        packed_data_str = f"{state_width}'d{next_state_encoding}"
        
        # Add parameter fields (LSB to MSB)
        for field in reversed(param_fields): # Iterate in reverse for correct concatenation order
            field_name = field['name']
            field_width = field['width']
            field_value = entry[field_name]
            packed_data_str = f"{field_width}'d{field_value}, {packed_data_str}" 

        tb_code.append(f"        // Write LUT Entry {hex(addr)}: State={entry['next_state']}, Repeat={entry.get('repeat_count')}, DataLen={entry.get('data_length')}, EOF={entry.get('eof')}, SOF={entry.get('sof')}")
        tb_code.append(f"        lut_write_data_i = {{{packed_data_str}}};")
        tb_code.append(f"        @(posedge clk); // Wait for one clock cycle for write to complete and dut.lut_addr_reg to increment")
    
    tb_code.append(f"        lut_wen_i = 1'b0; // Disable LUT write")
    tb_code.append(f"        $display(\"--- LUT RAM Initialized ---\\n\");")
    tb_code.append(f"")

    tb_code.append(f"        // De-assert reset to start FSM operation")
    tb_code.append(f"        reset_i = 1'b0;")
    tb_code.append(f"        @(posedge clk); // Wait for FSM to transition out of RST")
    tb_code.append(f"")

    tb_code.append(f"        // --- Monitor FSM State and Outputs ---")
    tb_code.append(f"        $display(\"Time\\tState\\tBusy\\tSeqDone\\tPanel\\tBias\\tFlush\\tExpose\\tReadout\\tAED\\tRPT\\tDATA\\tEOF\\tSOF\\tLUT_ADDR\");")
    tb_code.append(f"        $monitor(\"%0t\\t%s\\t%b\\t%b\\t%b\\t%b\\t%b\\t%b\\t%b\\t%b\\t%d\\t%d\\t%b\\t%b\\t%h\",")
    tb_code.append(f"                 $time,")
    tb_code.append(f"                 state_name_from_encoding(current_state_o),")
    tb_code.append(f"                 busy_o, sequence_done_o,")
    
    output_names = []
    for out in fsm_config['outputs']:
        if out['name'] not in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o'] and not out['name'].startswith('current_'):
            output_names.append(out['name'])
    tb_code.append(f"                 {', '.join(output_names)},")

    param_output_names = []
    for field in param_fields:
        param_output_names.append(f"current_{field['name']}_o")
    tb_code.append(f"                 {', '.join(param_output_names)},")
    tb_code.append(f"                 dut.lut_addr_reg);") # Access internal lut_addr_reg of DUT
    tb_code.append(f"")

    tb_code.append(f"        #20000; // Run simulation for a substantial amount of time")
    tb_code.append(f"        $display(\"\\n--- Simulation Timeout ---\");")
    tb_code.append(f"        $finish;")
    tb_code.append(f"    end")
    tb_code.append(f"")

    # Helper function to display state names
    tb_code.append(f"    function string state_name_from_encoding(logic [{state_width-1}:0] encoding);")
    tb_code.append(f"        case(encoding)")
    for state_name, encoding_val in state_encoding_map.items():
        tb_code.append(f"            {state_name}: state_name_from_encoding = \"{state_name}\";")
    tb_code.append(f"            default: state_name_from_encoding = \"UNKNOWN\";")
    tb_code.append(f"        endcase")
    tb_code.append(f"    endfunction")
    tb_code.append(f"")

    tb_code.append(f"endmodule")

    with open(tb_output_file, 'w') as f:
        f.write("\n".join(tb_code))
    logging.info(f"SystemVerilog Testbench generated successfully: {tb_output_file}")


if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"
    TB_OUTPUT_PATH = "sequencer_fsm_tb.sv"

    logging.info(f"Generating SystemVerilog Testbench to {TB_OUTPUT_PATH}...")
    generate_systemverilog_testbench(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, TB_OUTPUT_PATH)

    logging.info("Testbench generation complete. You can now use a SystemVerilog simulator (e.g., 'iverilog -o sequencer_fsm_tb sequencer_fsm.sv sequencer_fsm_tb.sv && vvp sequencer_fsm_tb') to verify the DUT.")