# FPGA Sequencer FSM Generator and Simulator

## Overview

This project provides tools to define, simulate, and generate hardware description code for a Finite State Machine (FSM) based sequencer. The behavior of the FSM and the data for its Look-Up Table (LUT) RAM are configured through YAML files. The main script can:

1.  Simulate the FSM's behavior in Python.
2.  Generate SystemVerilog HDL code for the FSM, suitable for FPGA synthesis.
3.  Generate a Mermaid state diagram for visualization of the FSM.

## Core Components

*   **`generate_fsm.py`**: This is the main Python script. It parses the YAML configuration files and performs simulation, HDL generation, and/or Mermaid diagram generation.
*   **`fsm_config.yaml`**: This YAML file defines the structure of the FSM. It includes:
    *   FSM name.
    *   State encoding width.
    *   Input and output ports.
    *   A list of states, their corresponding output values, and transition conditions.
*   **`fsm_lut_ram_data.yaml`**: This YAML file configures the LUT RAM, which is used by the FSM (typically in an `IDLE` state) to determine the next state and associated parameters based on a `command_id_i` input. It defines:
    *   LUT RAM address width.
    *   Parameter fields (e.g., `repeat_count`, `data_length`) and their bit widths.
    *   Initial entries for the LUT RAM, mapping specific addresses (command IDs) to next states and parameter values.

## Functionality

### FSM Simulation
The `generate_fsm.py` script includes a Python-based FSM simulator (`FsmSimulator` class). This allows for pre-FPGA verification of the FSM logic by stepping through states based on configured inputs and LUT RAM data.

### SystemVerilog Generation
The script can generate a SystemVerilog HDL module (`sequencer_fsm.sv` by default) that implements the FSM and its LUT RAM. The generated Verilog is intended to be synthesizable for FPGA deployment. The LUT RAM can be written to and read from during runtime when the FSM is in a specific state (e.g., `RST`) via dedicated control signals.

### Mermaid Diagram Generation
To help visualize the FSM structure, the script can generate a state diagram in Mermaid markdown format (`fsm_diagram.md` by default). This diagram shows the states and transitions based on the `fsm_config.yaml` and `fsm_lut_ram_data.yaml`.

## Usage

1.  **Prepare Configuration Files:**
    *   Ensure `fsm_config.yaml` and `fsm_lut_ram_data.yaml` are present, ideally in the root directory alongside `generate_fsm.py`.
    *   The script `generate_fsm.py` includes a `__main__` block that demonstrates its usage. If these YAML files are not found when the script is run directly from its location, it will create dummy versions. For actual use, you should create and customize these files to define your specific FSM.
    *   Example configuration files can be found in the `test/` directory. You can copy `test/fsm_config.yaml` and `test/fsm_lut_ram_data.yaml` to the root directory as a starting point.

2.  **Run the Script:**
    Execute the script from the root directory of the project:
    ```bash
    python generate_fsm.py
    ```
    This will typically:
    *   Run a short Python simulation sequence (as defined in the `__main__` block of the script).
    *   Generate `sequencer_fsm.sv` (SystemVerilog code).
    *   Generate `fsm_diagram.md` (Mermaid diagram).

## Key Files and Directories

*   `generate_fsm.py`: Main script for FSM generation and simulation.
*   `fsm_config.yaml`: Defines FSM states, transitions, inputs, and outputs.
*   `fsm_lut_ram_data.yaml`: Defines LUT RAM parameters and initial entries.
*   `sequencer_fsm.sv`: Generated SystemVerilog FSM module.
*   `fsm_diagram.md`: Generated Mermaid state diagram.
*   `README.md`: This file.
*   `test/`: Contains example configuration files, a Verilog testbench (`sequencer_fsm_tb.sv`), and other test-related utilities.

## Development Notes

*   The FSM's `IDLE` state typically uses the `command_id_i` input to look up the next state and parameters from the LUT RAM.
*   The `RST` state in the example configuration allows for reading from and writing to the LUT RAM via dedicated inputs (`lut_access_en_i`, `lut_read_write_mode_i`, `lut_write_data_i`).
*   The Python simulator (`FsmSimulator`) provides a way to test FSM logic before synthesizing the Verilog.
```
