import yaml
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def generate_systemverilog_testbench(fsm_config_path, lut_ram_config_path, output_file):
    with open(fsm_config_path, 'r') as f:
        fsm_config = yaml.safe_load(f)
    with open(lut_ram_config_path, 'r') as f:
        lut_ram_config = yaml.safe_load(f)

    fsm_name = "sequencer_fsm"
    state_width = fsm_config['state_encoding_width']
    states_data = fsm_config['states']
    
    state_encoding_map = {state['name']: state['encoding'] for state in states_data}

    address_width = lut_ram_config['lut_ram_config']['address_width']
    param_fields = lut_ram_config['lut_ram_config']['param_fields']
    
    repeat_count_width = 0
    data_length_width = 0
    eof_width = 0
    sof_width = 0

    for field in param_fields:
        if field['name'] == 'repeat_count':
            repeat_count_width = field['width']
        elif field['name'] == 'data_length':
            data_length_width = field['width']
        elif field['name'] == 'eof':
            eof_width = field['width']
        elif field['name'] == 'sof':
            sof_width = field['width']

    # Determine bit slicing for packing data into 29-bit lut_write_data_i
    current_bit_pos = 0
    next_state_start_bit = current_bit_pos
    next_state_end_bit = next_state_start_bit + state_width - 1
    current_bit_pos = next_state_end_bit + 1

    repeat_count_start_bit = current_bit_pos
    repeat_count_end_bit = repeat_count_start_bit + repeat_count_width - 1
    current_bit_pos = repeat_count_end_bit + 1

    data_length_start_bit = current_bit_pos
    data_length_end_bit = data_length_start_bit + data_length_width - 1
    current_bit_pos = data_length_end_bit + 1

    eof_start_bit = current_bit_pos
    eof_end_bit = eof_start_bit + eof_width - 1
    current_bit_pos = eof_end_bit + 1

    sof_start_bit = current_bit_pos
    sof_end_bit = sof_start_bit + sof_width - 1

    tb_code_lines = []

    tb_code_lines.append(f"`timescale 1ns / 1ps")
    tb_code_lines.append(f"module {fsm_name}_tb();")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"    localparam CLOCK_PERIOD = 10;")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"    logic                   clk;")
    tb_code_lines.append(f"    logic                   reset_i;")
    tb_code_lines.append(f"    logic                   lut_wen_i;")
    tb_code_lines.append(f"    logic [28:0]            lut_write_data_i;")
    tb_code_lines.append(f"    logic                   lut_rden_i;")
    tb_code_lines.append(f"    wire  [28:0]            lut_read_data_o;")
    tb_code_lines.append(f"    wire  [2:0]             current_state_o;")
    tb_code_lines.append(f"    wire  logic             busy_o;")
    tb_code_lines.append(f"    wire  logic             sequence_done_o;")
    tb_code_lines.append(f"    wire  logic             panel_enable_o;")
    tb_code_lines.append(f"    wire  logic             bias_enable_o;")
    tb_code_lines.append(f"    wire  logic             flush_enable_o;")
    tb_code_lines.append(f"    wire  logic             expose_enable_o;")
    tb_code_lines.append(f"    wire  logic             readout_enable_o;")
    tb_code_lines.append(f"    wire  logic             aed_enable_o;")
    tb_code_lines.append(f"    wire  [7:0]             current_repeat_count_o;")
    tb_code_lines.append(f"    wire  [15:0]            current_data_length_o;")
    tb_code_lines.append(f"    wire  [0:0]             current_eof_o;")
    tb_code_lines.append(f"    wire  [0:0]             current_sof_o;")
    tb_code_lines.append(f"")

    tb_code_lines.append(f"    {fsm_name} dut (")
    tb_code_lines.append(f"        .clk(clk),")
    tb_code_lines.append(f"        .reset_i(reset_i),")
    tb_code_lines.append(f"        .lut_wen_i(lut_wen_i),")
    tb_code_lines.append(f"        .lut_write_data_i(lut_write_data_i),")
    tb_code_lines.append(f"        .lut_rden_i(lut_rden_i),")
    tb_code_lines.append(f"        .lut_read_data_o(lut_read_data_o),")
    tb_code_lines.append(f"        .current_state_o(current_state_o),")
    tb_code_lines.append(f"        .busy_o(busy_o),")
    tb_code_lines.append(f"        .sequence_done_o(sequence_done_o),")
    tb_code_lines.append(f"        .panel_enable_o(panel_enable_o),")
    tb_code_lines.append(f"        .bias_enable_o(bias_enable_o),")
    tb_code_lines.append(f"        .flush_enable_o(flush_enable_o),")
    tb_code_lines.append(f"        .expose_enable_o(expose_enable_o),")
    tb_code_lines.append(f"        .readout_enable_o(readout_enable_o),")
    tb_code_lines.append(f"        .aed_enable_o(aed_enable_o),")
    tb_code_lines.append(f"        .current_repeat_count_o(current_repeat_count_o),")
    tb_code_lines.append(f"        .current_data_length_o(current_data_length_o),")
    tb_code_lines.append(f"        .current_eof_o(current_eof_o),")
    tb_code_lines.append(f"        .current_sof_o(current_sof_o)")
    tb_code_lines.append(f"    );")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"    always #(CLOCK_PERIOD / 2) clk = ~clk;")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"    initial begin")
    tb_code_lines.append(f"        clk = 1'b0;")
    tb_code_lines.append(f"        reset_i = 1'b1;")
    tb_code_lines.append(f"        lut_wen_i = 1'b0;")
    tb_code_lines.append(f"        lut_write_data_i = 29'd0;")
    tb_code_lines.append(f"        lut_rden_i = 1'b0;")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"        repeat(2) @(posedge clk);")
    tb_code_lines.append(f"        reset_i = 1'b0;")
    tb_code_lines.append(f"        @(posedge clk);")
    tb_code_lines.append(f"")
    
    # Pack function for convenience in TB
    tb_code_lines.append(f"        function automatic logic [28:0] pack_lut_entry(")
    tb_code_lines.append(f"            input logic [{state_width-1}:0] next_state_in,")
    tb_code_lines.append(f"            input logic [{repeat_count_width-1}:0] repeat_count_in,")
    tb_code_lines.append(f"            input logic [{data_length_width-1}:0] data_length_in,")
    tb_code_lines.append(f"            input logic [{eof_width-1}:0] eof_in,")
    tb_code_lines.append(f"            input logic [{sof_width-1}:0] sof_in")
    tb_code_lines.append(f"        );")
    tb_code_lines.append(f"            pack_lut_entry = (sof_in         << {sof_start_bit}) |")
    tb_code_lines.append(f"                             (eof_in         << {eof_start_bit}) |")
    tb_code_lines.append(f"                             (data_length_in << {data_length_start_bit}) |")
    tb_code_lines.append(f"                             (repeat_count_in << {repeat_count_start_bit}) |")
    tb_code_lines.append(f"                             (next_state_in  << {next_state_start_bit});")
    tb_code_lines.append(f"        endfunction")
    tb_code_lines.append(f"")

    # Initial LUT RAM loading via write port in RST state (alternative to initial block in DUT)
    tb_code_lines.append(f"        // Simulate loading LUT RAM via write port in RST state")
    tb_code_lines.append(f"        reset_i = 1'b1;") # Re-assert reset to enter RST state for loading
    tb_code_lines.append(f"        @(posedge clk);") # Wait for 1 clock cycle to enter RST
    tb_code_lines.append(f"")
    tb_code_lines.append(f"        lut_wen_i = 1'b1;") # Enable write
    
    # State parameter definitions for TB functions
    tb_code_lines.append(f"        // FSM State Parameters for TB Functions")
    for state in states_data:
        tb_code_lines.append(f"        localparam logic [{state_width-1}:0] {state['name']} = {state_width}'b{state_encoding_map[state['name']]};")
    tb_code_lines.append(f"")

    for entry in lut_ram_config['lut_entries']:
        addr = entry['address']
        next_state_name = entry['next_state']
        next_state_val = state_encoding_map[next_state_name]
        
        param_values = {}
        for field in param_fields:
            param_values[field['name']] = entry[field['name']]
        
        # Use the pack_lut_entry function
        tb_code_lines.append(f"        lut_write_data_i = pack_lut_entry({next_state_name}, {repeat_count_width}'d{param_values['repeat_count']}, {data_length_width}'d{param_values['data_length']}, {eof_width}'b{param_values['eof']}, {sof_width}'b{param_values['sof']});")
        tb_code_lines.append(f"        @(posedge clk);")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"        lut_wen_i = 1'b0;")
    tb_code_lines.append(f"        reset_i = 1'b0;") # De-assert reset to start sequence
    tb_code_lines.append(f"        @(posedge clk);")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"        // Monitor and simulate sequence for a duration")
    tb_code_lines.append(f"        repeat(5000) @(posedge clk);")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"        $finish;")
    tb_code_lines.append(f"    end")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"    initial begin")
    tb_code_lines.append(f"        $dumpfile(\"{fsm_name}_tb.vcd\");")
    tb_code_lines.append(f"        $dumpvars(0, {fsm_name}_tb);")
    tb_code_lines.append(f"        $display(\"Time\\tState\\tBusy\\tSeqDone\\tAddr\\tRptCnt\\tDataLen\\tEOF\\tSOF\");")
    tb_code_lines.append(f"        $monitor(\"%0t\\t%h\\t%b\\t%b\\t%h\\t%d\\t%d\\t%b\\t%b\",")
    tb_code_lines.append(f"                 $time, current_state_o, busy_o, sequence_done_o,")
    tb_code_lines.append(f"                 dut.lut_addr_reg, current_repeat_count_o, current_data_length_o,")
    tb_code_lines.append(f"                 current_eof_o, current_sof_o);")
    tb_code_lines.append(f"    end")
    tb_code_lines.append(f"")
    tb_code_lines.append(f"endmodule")

    with open(output_file, 'w') as f:
        f.write("\n".join(tb_code_lines))
    logging.info(f"SystemVerilog Testbench module generated successfully: {output_file}")


if __name__ == "__main__":
    FSM_CONFIG_PATH = "fsm_config.yaml"
    LUT_RAM_DATA_PATH = "fsm_lut_ram_data.yaml"
    TB_OUTPUT_PATH = "sequencer_fsm_tb.sv"

    logging.info(f"Generating SystemVerilog Testbench to {TB_OUTPUT_PATH}...")
    generate_systemverilog_testbench(FSM_CONFIG_PATH, LUT_RAM_DATA_PATH, TB_OUTPUT_PATH)
    logging.info("Testbench generation complete.")