```mermaid
stateDiagram-v2
    direction LR
    state RST
    state IDLE
    state PANEL_STABLE : panel_enable_o=1, bias_enable_o=0, flush_enable_o=0, expose_enable_o=0, readout_enable_o=0, aed_enable_o=0
    state BACK_BIAS : panel_enable_o=0, bias_enable_o=1, flush_enable_o=0, expose_enable_o=0, readout_enable_o=0, aed_enable_o=0
    state FLUSH : panel_enable_o=0, bias_enable_o=0, flush_enable_o=1, expose_enable_o=0, readout_enable_o=0, aed_enable_o=0
    state AED_DETECT : panel_enable_o=0, bias_enable_o=0, flush_enable_o=0, expose_enable_o=0, readout_enable_o=0, aed_enable_o=1
    state EXPOSE_TIME : panel_enable_o=0, bias_enable_o=0, flush_enable_o=0, expose_enable_o=1, readout_enable_o=0, aed_enable_o=0
    state READOUT : panel_enable_o=0, bias_enable_o=0, flush_enable_o=0, expose_enable_o=0, readout_enable_o=1, aed_enable_o=0


    [*] --> RST : Reset asserted (reset_i = 1) / lut_addr_reg <= 0x00
    RST --> PANEL_STABLE : Reset de-asserted (reset_i = 0 falling edge) / lut_addr_reg <= 0x00 (re-init for seq)
    RST : LUT RAM R/W enabled (using auto-incrementing lut_addr_reg with lut_wen_i/lut_rden_i)
    PANEL_STABLE --> IDLE : Task Done
    BACK_BIAS --> IDLE : Task Done
    FLUSH --> IDLE : Task Done
    EXPOSE_TIME --> IDLE : Task Done
    READOUT --> IDLE : Task Done
    IDLE --> State_Evaluation_in_IDLE : lut_addr_reg increments (+1)
    State_Evaluation_in_IDLE --> PANEL_STABLE : if current_eof == 1 / lut_addr_reg <= 0x00 (loop)
    State_Evaluation_in_IDLE --> BACK_BIAS : if current_eof == 0 (for command at 0x0)
    State_Evaluation_in_IDLE --> FLUSH : if current_eof == 0 (for command at 0x1)
    State_Evaluation_in_IDLE --> EXPOSE_TIME : if current_eof == 0 (for command at 0x2)
    State_Evaluation_in_IDLE --> READOUT : if current_eof == 0 (for command at 0x3)
    default --> RST : Unexpected state / lut_addr_reg <= 0x00

    note right of RST
        - **Reset (Active High)**: When `reset_i=1`, FSM enters `RST` state. `lut_addr_reg` initializes to `0x00`.
        - **LUT RAM Configuration (in RST)**: While in `RST` state, `lut_wen_i` asserted writes `lut_write_data_i` to `lut_ram[lut_addr_reg]`, and `lut_rden_i` asserted reads `lut_ram[lut_addr_reg]` to `lut_read_data_o`. For both R/W operations, `lut_addr_reg` automatically increments (`+1`) to sequential addresses. **External logic must manage when to de-assert `reset_i` after the LUT RAM is fully configured.**
        - **Automatic Sequence Start**: When `reset_i` falls to `0`, FSM transitions directly from `RST` to the state defined by `lut_ram[0x00]` (e.g., `PANEL_STABLE`). `lut_addr_reg` is reset to `0x00` at this point to start the sequence from the beginning.
        - **Step-by-Step Sequence Execution**: Each command state (e.g., `PANEL_STABLE`, `BACK_BIAS`) performs its task. Upon task completion, the FSM always transitions to the **`IDLE` state**. At this point, `lut_addr_reg` still holds the address of the *just completed* command.
        - **`IDLE` State Logic**: When in `IDLE`, the `lut_addr_reg` is first **incremented by `+1`**. Then, the **`eof` bit of the *previously completed command* (i.e., `current_eof` which reflects the LUT entry before the increment)** is checked:
            - If `current_eof = 1` (meaning the last command was the end of the sequence), the FSM **loops back** to the beginning: `lut_addr_reg` is reset to `0x00`, and the FSM transitions to the state defined by `lut_ram[0x00]`.
            - If `current_eof = 0` (meaning there are more commands in the sequence), the FSM transitions to the state defined by `lut_ram[new_lut_addr_reg]` (the newly incremented address).
        - **`sequence_done_o`**: This output is asserted for one cycle when the FSM is in `IDLE` and the *previous* command indicated `eof=1`. It signals the completion of one full sequence loop.
    end note
```