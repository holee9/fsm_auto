import yaml
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_testbench(fsm_config_path, lut_ram_config_path, output_tb_file, fsm_module_name):
    """
    Generates a SystemVerilog testbench for the FSM module.
    It includes basic clocking, reset, and stimulus for LUT RAM configuration
    and FSM sequence execution, including data_length, repeat, and exit_signal.
    """
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

    # Extract necessary FSM and LUT RAM configuration details
    state_width = fsm_config['state_encoding_width']
    lut_address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    total_param_width = sum(field['width'] for field in param_fields)
    lut_data_width = state_width + total_param_width
    lut_entries = lut_ram_config['lut_entries']
    
    # Determine the maximum width for data_length and repeat_count for the testbench
    max_data_length = 0
    max_repeat_count = 0
    for entry in lut_entries:
        for field in param_fields:
            if field['name'] == 'data_length':
                max_data_length = max(max_data_length, entry.get('data_length', 0))
            if field['name'] == 'repeat_count':
                max_repeat_count = max(max_repeat_count, entry.get('repeat_count', 0))

    data_length_width = (max_data_length - 1).bit_length() if max_data_length > 0 else 1
    repeat_count_width = (max_repeat_count - 1).bit_length() if max_repeat_count > 0 else 1

    tb_code = []
    tb_code.append("`timescale 1ns / 1ps")
    tb_code.append("")
    tb_code.append(f"module {fsm_module_name}_tb;")
    tb_code.append("")

    # --- Testbench Signals Declaration ---
    tb_code.append("    // Clock and Reset signals")
    tb_code.append("    logic clk;")
    tb_code.append("    logic reset_i;")
    tb_code.append("    logic exit_signal_i; // External signal for infinite loop exit")
    tb_code.append("")
    tb_code.append("    // LUT RAM interface signals")
    tb_code.append(f"    logic lut_wen_i; // LUT Write Enable (active high, only in RST state)")
    tb_code.append(f"    logic [{lut_data_width-1}:0] lut_write_data_i; // Data to write to LUT RAM")
    tb_code.append(f"    logic lut_rden_i; // LUT Read Enable (active high, only in RST state)")
    tb_code.append(f"    wire [{lut_data_width-1}:0] lut_read_data_o; // Data read from LUT RAM")
    tb_code.append("")

    # --- Internal FSM Signals (Outputs of FSM, Inputs of TB) ---
    tb_code.append("    // FSM Outputs")
    tb_code.append(f"    wire [{state_width-1}:0] current_state_o;")
    tb_code.append("    wire busy_o;")
    tb_code.append("    wire sequence_done_o;")
    
    # Add other FSM outputs from config (assuming 1-bit or specified width)
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o']:
            continue # Already declared
        if out['name'].startswith('current_'): # 'current_eof_o', 'current_data_length_o', etc.
            tb_code.append(f"    wire [{out['width']-1}:0] {out['name']};")
        else: # Other general outputs like panel_power_o
            if out['width'] == 1:
                tb_code.append(f"    wire {out['name']};")
            else:
                tb_code.append(f"    wire [{out['width']-1}:0] {out['name']};")
    tb_code.append("")

    # --- Instantiate the FSM module ---
    tb_code.append(f"    // Instantiate FSM module")
    tb_code.append(f"    {fsm_module_name} u_fsm (")
    tb_code.append("        .clk(clk),")
    tb_code.append("        .reset_i(reset_i),")
    tb_code.append("        .exit_signal_i(exit_signal_i),") # New port
    tb_code.append("        .lut_wen_i(lut_wen_i),")
    tb_code.append("        .lut_write_data_i(lut_write_data_i),")
    tb_code.append("        .lut_rden_i(lut_rden_i),")
    tb_code.append("        .lut_read_data_o(lut_read_data_o),")
    tb_code.append("        .current_state_o(current_state_o),")
    tb_code.append("        .busy_o(busy_o),")
    tb_code.append("        .sequence_done_o(sequence_done_o)")
    
    # Map other FSM outputs from config
    for out in fsm_config['outputs']:
        if out['name'] in ['current_state_o', 'busy_o', 'sequence_done_o', 'lut_read_data_o']:
            continue
        tb_code.append(f"        ,.{out['name']}({out['name']})")
    tb_code.append("    );")
    tb_code.append("")

    # --- Clock Generation ---
    tb_code.append("    // Clock Generation")
    tb_code.append("    initial begin")
    tb_code.append("        clk = 0;")
    tb_code.append("        forever #5 clk = ~clk; // 10ns period, 100MHz clock")
    tb_code.append("    end")
    tb_code.append("")

    # --- Test Scenario ---
    tb_code.append("    // Test Scenario")
    tb_code.append("    initial begin")
    tb_code.append("        $dumpfile(\"sequencer_fsm_tb.vcd\");")
    tb_code.append("        $dumpvars(0, {fsm_module_name}_tb);")
    tb_code.append("")
    
    tb_code.append("        // 1. Initial Reset")
    tb_code.append("        reset_i = 1;")
    tb_code.append("        lut_wen_i = 0;")
    tb_code.append("        lut_rden_i = 0;")
    tb_code.append("        lut_write_data_i = '0;")
    tb_code.append("        exit_signal_i = 0;") # Ensure exit_signal is low
    tb_code.append("        #20; // Hold reset for 20ns (2 clock cycles)")
    tb_code.append("")

    tb_code.append("        // 2. Configure LUT RAM (using RST state auto-increment)")
    tb_code.append("        // FSM remains in RST while configuring, lut_addr_reg auto-increments with lut_wen_i/lut_rden_i")
    tb_code.append("        lut_wen_i = 1; // Enable LUT write")
    for i, entry in enumerate(lut_entries):
        # Reconstruct the LUT entry data based on param_fields order and state encoding
        data_value = 0
        current_bit_pos = 0
        
        # Add parameter fields (LSB to MSB)
        for field in reversed(param_fields):
            param_val = entry.get(field['name'], 0) # Use .get() for safety
            data_value |= (param_val << current_bit_pos)
            current_bit_pos += field['width']
        
        # Add next_state (MSB side)
        state_encoding = fsm_config['states_map'][entry['next_state']]
        data_value |= (state_encoding << current_bit_pos)

        tb_code.append(f"        lut_write_data_i = {lut_data_width}'d{data_value}; // Address {hex(entry['address'])}")
        tb_code.append(f"        #10; // Write data and auto-increment lut_addr_reg")
    tb_code.append("        lut_wen_i = 0; // Disable LUT write")
    tb_code.append("        #10;")
    tb_code.append("")

    tb_code.append("        // 3. De-assert reset to start FSM sequence")
    tb_code.append("        reset_i = 0;")
    tb_code.append("        #10;") # Allow one clock cycle for FSM to transition out of RST
    tb_code.append("        $display(\"\\n--- FSM Sequence Started ---\");")
    tb_code.append("        $display(\"Time\\tState\\tAddr\\tDataLen\\tRepeat\\tEOF\\tSOF\\tBusy\\tSeqDone\\tExitSig\");")
    
    # --- Sequence Execution Loop ---
    # This loop runs for a sufficient number of cycles to cover most scenarios,
    # especially repeat and infinite loop with exit.
    tb_code.append("        for (int i = 0; i < 200; i++) begin // Run for a fixed number of cycles to observe behavior")
    tb_code.append("            $display(\"%-4d\\t%h\\t%h\\t%h\\t%h\\t%b\\t%b\\t%b\\t%b\\t%b\", ")
    tb_code.append("                $time, current_state_o, u_fsm.lut_addr_reg, u_fsm.data_length_timer, u_fsm.active_repeat_count,")
    tb_code.append("                current_eof_o, current_sof_o, busy_o, sequence_done_o, exit_signal_i);")
    
    # Specific stimulus for exit_signal_i (e.g., enable after some cycles)
    tb_code.append("            if ($time == 150) begin // Example: Assert exit_signal_i at 150ns (after some sequence iterations)")
    tb_code.append("                exit_signal_i = 1;")
    tb_code.append("                $display(\"\\n*** ASSERTING exit_signal_i ***\\n\");")
    tb_code.append("            end else if ($time == 160) begin")
    tb_code.append("                exit_signal_i = 0;")
    tb_code.append("                $display(\"\\n*** DE-ASSERTING exit_signal_i ***\\n\");")
    tb_code.append("            end")

    tb_code.append("            #10; // Wait for next clock edge")
    tb_code.append("        end")
    tb_code.append("")
    tb_code.append("        $display(\"\\n--- Simulation Finished ---\");")
    tb_code.append("        $finish;")
    tb_code.append("    end")
    tb_code.append("")
    tb_code.append("endmodule")

    with open(output_tb_file, 'w') as f:
        f.write("\n".join(tb_code))
    logging.info(f"SystemVerilog testbench generated successfully: {output_tb_file}")

# Main execution block
if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"
    SV_MODULE_NAME = "sequencer_fsm" # The module name generated by generate_fsm.py
    TB_OUTPUT_PATH = "sequencer_fsm_tb.sv"

    # Ensure fsm_config.yaml has a 'states_map' for encoding lookup in TB
    # (generate_fsm.py already creates this mapping for internal use, but we need it here too)
    try:
        with open(FSM_CONFIG_PATH, 'r') as f:
            fsm_config = yaml.safe_load(f)
            if 'states_map' not in fsm_config:
                # Add a states_map if not present (this helps in TB generation)
                states_data = fsm_config['states']
                fsm_config['states_map'] = {state['name']: state['encoding'] for state in states_data}
                with open(FSM_CONFIG_PATH, 'w') as f_write:
                    yaml.dump(fsm_config, f_write, default_flow_style=False, sort_keys=False)
                logging.info(f"Added 'states_map' to {FSM_CONFIG_PATH} for testbench generation.")
    except Exception as e:
        logging.error(f"Error updating fsm_config.yaml: {e}")
        sys.exit(1)

    logging.info(f"Generating SystemVerilog Testbench to {TB_OUTPUT_PATH}...")
    generate_systemverilog_testbench(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, TB_OUTPUT_PATH, SV_MODULE_NAME)
    logging.info("Testbench generation complete. Please use an HDL simulator to run the testbench.")