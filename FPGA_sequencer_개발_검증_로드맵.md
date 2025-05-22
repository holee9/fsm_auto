# FPGA Sequencer FSM 개발 및 검증 로드맵

이 문서는 FSM (Finite State Machine) 시퀀서의 개발, 시뮬레이션, RTL (Register-Transfer Level) 구현 및 검증을 위한 단계별 로드맵을 제공합니다. `data_length` 및 `repeat` 파라미터의 고급 처리 로직(무한 반복 및 외부 종료 신호 포함)을 중심으로 설명합니다.

---

## 1. 프로젝트 파일 역할

* **`fsm_config.yaml`**: FSM의 전반적인 설정 (상태 인코딩 폭, 상태 목록 등)을 정의합니다.
* **`fsm_lut_ram_data.yaml`**: LUT RAM에 로드될 시퀀스 명령 데이터 (다음 상태, 파라미터: `repeat_count`, `data_length`, `eof`, `sof`, 주소 등)를 정의합니다.
* **`sim_fsm.py`**: Python으로 구현된 FSM의 고수준 시뮬레이션 모델입니다. RTL 개발 전 동작을 빠르게 프로토타이핑하고 검증합니다.
* **`generate_fsm.py`**: `fsm_config.yaml`과 `fsm_lut_ram_data.yaml`을 기반으로 실제 FPGA에 합성될 SystemVerilog RTL 코드(`sequencer_fsm.sv`)를 자동으로 생성합니다.
* **`sequencer_fsm.sv`**: `generate_fsm.py`에 의해 생성되는 FSM의 최종 RTL 코드입니다.
* **`gen_tb.py`**: `sequencer_fsm.sv` (RTL)를 검증하기 위한 SystemVerilog 테스트벤치 코드를 생성합니다.

---

## 2. 개발 및 검증 단계별 로드맵

### 단계 1: FSM 동작 명세 구체화 (완료/진행 중)

* FSM이 `data_length` (현재 상태 유지 클럭 수), `repeat` (상태 반복 횟수), 그리고 `exit_signal` (무한 반복 종료)을 어떻게 처리할지 명확히 정의합니다.
    * **`data_length`**: 해당 명령 상태에 진입했을 때 FSM이 최소한 `data_length` 클럭 수만큼 머물러야 합니다. 내부 타이머 (`data_length_timer`)를 사용하며, 타이머가 0이 되고 관련된 `internal_task_done` 신호가 활성화될 때만 `IDLE`로 전이합니다.
    * **`repeat`**: 한 번의 명령이 `data_length` 조건과 `internal_task_done`으로 완료된 후, 동일한 명령을 `repeat` 횟수만큼 반복합니다.
        * `repeat > 0`: 지정된 횟수만큼 반복하며, 각 반복 사이에는 `IDLE` 상태를 1클럭 이상 경유합니다. (`active_repeat_count` 사용).
        * `repeat == 0`: 외부 `exit_signal`이 들어올 때까지 현재 명령을 무한히 반복합니다. 각 반복 사이에는 `IDLE` 상태를 경유합니다.
    * **`IDLE` 상태 역할 강화**: 명령 완료 후 대기, 다음 명령 준비, 그리고 `repeat` 루프의 진입점 (동일 `Addr`로 재진입) 역할을 수행합니다.

### 단계 2: `sim_fsm.py` (Python 모델) 개발 및 고수준 검증 (현재 진행 중)

* **목표**: RTL 구현 전 FSM의 새로운 동작 로직을 빠르게 프로토타이핑하고 기능적 정확성을 검증합니다.
* **수정 내용**:
    * `SequencerFSM` 클래스에 다음 내부 레지스터 추가:
        * `self.active_repeat_count`: 현재 명령의 남은 반복 횟수.
        * `self.data_length_timer`: 현재 명령 상태의 남은 유지 클럭 수.
        * `self.exit_signal`: 외부에서 인가되는 무한 반복 탈출 신호 (시뮬레이션용).
    * `_simulate_internal_tasks()` 함수 수정:
        * 이제 `data_length_timer`가 0이 되었을 때만 관련 `internal_task_done` 신호들이 발생하도록 로직을 조정합니다. (`data_length`가 최소 대기 시간을 보장).
    * `step()` 메서드 수정:
        * FSM이 `RST` 또는 `IDLE`에서 명령 상태로 진입할 때 `active_repeat_count`를 현재 LUT 명령의 `repeat_count`로, `data_length_timer`를 `data_length`로 초기화합니다.
        * 명령 상태에 있는 동안 `data_length_timer`를 감소시키고, 0이면서 `internal_task_done`이 활성화될 때만 `IDLE`로 전이합니다.
        * `IDLE` 상태에서 `active_repeat_count` 값을 확인하여:
            * `> 0`: `active_repeat_count` 감소 후 현재 LUT 주소로 다시 전이 (반복).
            * `== 0` (무한 반복) **AND** `exit_signal` 활성화: 다음 LUT 주소로 전이 (무한 반복 탈출).
            * `== 0` (유한 반복 종료) **OR** (`== 0` & `NOT exit_signal`) **AND** `EOF` 활성화: 0x00으로 전이 (시퀀스 완료).
            * 그 외: `LUT_Addr + 1`로 전이 (일반적인 다음 명령).
    * `run_simulation()` 함수 내 출력 로직 (`print_line` 조건) 유지하여 주요 전이 시점만 출력되도록 합니다.
* **검증 방법**:
    * 다양한 `repeat_count`와 `data_length` 조합을 가지는 `fsm_lut_ram_data.yaml`을 생성하거나 수정하여 시뮬레이션을 실행합니다.
    * `sim_fsm.py`의 출력을 분석하여 FSM이 의도한 대로 `data_length`만큼 대기하고, `repeat` 횟수만큼 반복하며, `exit_signal`에 따라 무한 반복을 탈출하는지 확인합니다.

### 단계 3: `generate_fsm.py` (SystemVerilog RTL 생성기) 수정

* **목표**: `sim_fsm.py`에서 검증된 FSM 동작 로직을 SystemVerilog RTL 코드로 정확하게 생성합니다.
* **수정 내용**:
    * 생성될 `sequencer_fsm.sv` 파일에 다음 레지스터가 포함되도록 코드 생성 로직 수정:
        * `reg [N-1:0] data_length_timer;` (N은 `data_length`의 최대값에 따른 비트 폭)
        * `reg [M-1:0] active_repeat_count;` (M은 `repeat_count`의 최대값에 따른 비트 폭)
    * `sequencer_fsm.sv`의 포트 목록에 다음 입력 추가:
        * `input wire exit_signal_i,`
    * SystemVerilog `always_ff` 블록 및 `always_comb` 블록 내의 FSM 상태 전이 로직 (`case` 문 등)을 `sim_fsm.py`의 `step()` 메서드 로직과 동일하게 구현되도록 코드 생성 로직을 업데이트합니다.
        * `data_length_timer`의 초기화 및 감소 로직.
        * 명령 상태에서의 전이 조건 (`data_length_timer == 0` 및 외부 완료 신호).
        * `IDLE` 상태에서의 `active_repeat_count` 검사, 감소, 그리고 `exit_signal_i`에 따른 다음 상태/주소 결정 로직.

### 단계 4: `sequencer_fsm.sv` (실제 RTL 코드) 생성 및 검토

* **목표**: 수정된 `generate_fsm.py`로 생성된 RTL 코드가 올바른지 확인합니다.
* **작업**:
    * 수정된 `generate_fsm.py`를 실행하여 새로운 `sequencer_fsm.sv` 파일을 생성합니다.
    * 생성된 `.sv` 파일을 직접 열어보고, `Python` 모델의 로직이 SystemVerilog 구문으로 정확하게 변환되었는지 육안으로 검토합니다. (레지스터 선언, 전이 조건, 카운터 로직 등).

### 단계 5: `gen_tb.py` (SystemVerilog 테스트벤치) 개발 및 기능 검증

* **목표**: 생성된 `sequencer_fsm.sv` RTL 코드가 `data_length` 및 `repeat` 기능을 포함하여 모든 면에서 정확하게 동작하는지 최종 검증합니다.
* **수정 내용**:
    * `gen_tb.py`가 생성하는 테스트벤치 (`sequencer_fsm_tb.sv` 등)에 `exit_signal_i`를 제어할 수 있는 로직을 추가합니다.
    * `initial` 블록 또는 `always` 블록 내에서 다양한 테스트 시나리오를 구현합니다:
        * 특정 `data_length` 값을 가지는 명령에 대해 FSM이 정확히 해당 클럭 수 이상으로 상태를 유지하는지 확인.
        * `repeat` 값을 가지는 명령이 지정된 횟수만큼 `IDLE`을 경유하며 반복되는지 확인.
        * `repeat`가 0인 명령에 대해 무한 반복에 진입하는지 확인하고, 특정 시뮬레이션 시간에 `exit_signal_i`를 활성화하여 루프에서 올바르게 탈출하는지 검증.
        * `EOF` 및 `SOF` 비트가 포함된 전체 시퀀스도 테스트하여 종합적인 동작을 검증합니다.
* **검증 방법**:
    * `gen_tb.py`를 실행하여 테스트벤치 코드를 생성합니다.
    * `Icarus Verilog`, `Vivado Simulator`, `ModelSim` 등과 같은 HDL 시뮬레이터를 사용하여 `sequencer_fsm_tb.sv`를 시뮬레이션하고 파형을 분석합니다.
    * 시뮬레이션 결과(파형, 로그)가 `sim_fsm.py`의 출력 및 예상 동작과 **정확히 일치하는지 확인**하여 RTL 구현의 기능적 정합성을 최종 검증합니다.

---