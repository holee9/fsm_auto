# FPGA Sequencer FSM 개발 및 검증 로드맵

이 문서는 FSM (Finite State Machine) 시퀀서의 개발, 시뮬레이션, RTL (Register-Transfer Level) 구현 및 검증을 위한 단계별 로드맵을 제공합니다. `data_length` 및 `repeat` 파라미터의 고급 처리 로직(무한 반복 및 외부 종료 신호 포함)을 중심으로 설명합니다.

---

## 1. 프로젝트 파일 역할

* **`fsm_config.yaml`**: FSM의 전반적인 설정 (상태 인코딩 폭, 상태 목록 등)을 정의합니다.
* **`fsm_lut_ram_data.yaml`**: LUT RAM에 로드될 시퀀스 명령 데이터 (다음 상태, 파라미터: `repeat_count`, `data_length`, `eof`, `sof`, 주소 등)를 정의합니다.
* **`sim_fsm.py`**: Python으로 구현된 FSM의 고수준 시뮬레이션 모델입니다. RTL 개발 전 동작을 빠르게 프로토타이핑하고 검증합니다.
* **`generate_fsm.py`**: `fsm_config.yaml`과 `fsm_lut_ram_data.yaml`을 기반으로 실제 FPGA에 합성될 SystemVerilog RTL 코드(`sequencer_fsm.sv`)를 자동으로 생성합니다.
* **`sequencer_fsm.sv`**: `generate_fsm.py`에 의해 생성되는 FSM의 최종 RTL 코드입니다.
* **`gen_tb.py`**: `sequencer_fsm.sv` (RTL)를 검증하기 위한 SystemVerilog 테스트벤치 코드(`sequencer_fsm_tb.sv`)를 자동으로 생성합니다.
* **`sequencer_fsm_tb.sv`**: `gen_tb.py`에 의해 생성되는 SystemVerilog 테스트벤치 파일입니다.
* **`compare_logs.py`**: `sim_fsm.py`의 시뮬레이션 결과 로그와 `sequencer_fsm_tb.sv`의 시뮬레이션 결과 로그를 비교하여 기능적 일치 여부를 검증하는 Python 스크립트입니다.
* **`run_verification.sh`**: 전체 검증 프로세스(RTL 및 TB 생성, Python 시뮬레이션, RTL 시뮬레이션, 로그 비교)를 자동화하는 셸 스크립트입니다.

---

## 2. 개발 로드맵

### 단계 1: FSM 및 LUT RAM YAML 설정 파일 정의

* **목표**: FSM의 상태, 인코딩, LUT RAM의 주소 폭 및 파라미터 필드(repeat_count, data_length, eof, sof)를 정의합니다.
* **작업**:
    * `fsm_config.yaml` 파일을 생성하거나 업데이트하여 FSM의 기본 구조(상태, 인코딩 폭)를 정의합니다.
    * `fsm_lut_ram_data.yaml` 파일을 생성하거나 업데이트하여 LUT RAM의 구성(주소 폭, 파라미터 필드 이름 및 비트 폭)과 초기 시퀀스 명령 데이터를 정의합니다. 이 데이터는 예시이며, 실제 동작 검증에 사용될 수 있는 모든 조합을 처리하도록 설계되어야 합니다.

### 단계 2: `sim_fsm.py` (Python 시뮬레이션 모델) 개발

* **목표**: FSM의 핵심 로직을 Python으로 구현하여 RTL 구현 전에 시퀀서의 동작을 빠르게 검증합니다.
* **작업**:
    * `fsm_config.yaml`과 `fsm_lut_ram_data.yaml`을 읽어 FSM 상태 전이 및 LUT RAM 데이터 처리를 시뮬레이션하는 `SequencerFSM` 클래스를 구현합니다.
    * `step()` 메서드는 클럭 한 사이클 동안 FSM의 상태를 업데이트하고, `data_length_timer` 감소, `repeat_count` 처리, `sof`/`eof` 기반의 시퀀스 흐름 제어를 포함해야 합니다.
    * `IDLE` 상태에서 `current_eof_reg` 값을 확인하여 시퀀스 반복 여부와 주소 초기화를 결정하고, `current_sof_reg` 값은 새로운 시퀀스 시작 시 설정되도록 합니다. 이 로직은 LUT RAM의 모든 가능한 값과 조건 변화를 처리할 수 있도록 일반화되어야 합니다.
    * 시뮬레이션 결과를 파일로 출력할 수 있는 기능을 추가하여, 추후 RTL 시뮬레이션 결과와 비교할 수 있도록 준비합니다. (`print_header`, `print_line` 메서드 수정).
    * FSM 상태를 SystemVerilog와 동일한 16진수 인코딩으로 출력하도록 `get_display_info()` 및 `print_line()`을 업데이트합니다.

### 단계 3: `generate_fsm.py` (SystemVerilog 코드 생성기) 업데이트

* **목표**: `fsm_config.yaml`과 `fsm_lut_ram_data.yaml`을 기반으로 `sequencer_fsm.sv`를 자동으로 생성하며, `sim_fsm.py`의 로직과 완벽히 일치하는 RTL 코드를 생성합니다.
* **작업**:
    * `generate_fsm.py`가 `fsm_config.yaml` 및 `fsm_lut_ram_data.yaml`을 파싱하여 FSM 상태, LUT RAM의 필드 너비, 초기 LUT 엔트리 등을 동적으로 읽어오도록 합니다.
    * 생성될 `sequencer_fsm.sv`의 FSM 로직이 `sim_fsm.py`의 `step()` 메서드 로직과 동일하게 구현되도록 코드 생성 로직을 업데이트합니다. 이는 특정 예시 LUT RAM 값에 하드코딩되지 않고, 모든 가능한 LUT RAM 조건과 상태 전이를 처리할 수 있도록 일반화되어야 합니다.
    * 특히 `RST` 상태에서 초기 `current_sof_reg` 값 설정, 명령 상태에서의 `data_length_timer` 감소 및 전이 조건, `IDLE` 상태에서의 `active_repeat_count` 검사, 감소, 그리고 `current_eof_reg`에 따른 다음 상태/주소 결정 로직이 정확히 반영되도록 합니다.
    * `sequencer_fsm.sv`가 `lut_wen_i`를 통해 런타임에 LUT RAM을 업데이트할 수 있는 기능을 포함하는지 확인합니다.

### 단계 4: `sequencer_fsm.sv` (실제 RTL 코드) 생성 및 검토

* **목표**: 수정된 `generate_fsm.py`로 생성된 RTL 코드가 올바른지 확인합니다.
* **작업**:
    * 수정된 `generate_fsm.py`를 실행하여 새로운 `sequencer_fsm.sv` 파일을 생성합니다.
    * 생성된 `.sv` 파일을 직접 열어보고, `Python` 모델의 로직이 SystemVerilog 구문으로 정확하게 변환되었는지 육안으로 검토합니다. (레지스터 선언, 전이 조건, 카운터 로직 등).

### 단계 5: `gen_tb.py` (SystemVerilog 테스트벤치) 개발

* **목표**: 생성된 `sequencer_fsm.sv` RTL 코드를 검증하기 위한 SystemVerilog 테스트벤치 코드(`sequencer_fsm_tb.sv`)를 자동으로 생성합니다.
* **작업**:
    * `gen_tb.py`는 `fsm_config.yaml`과 `fsm_lut_ram_data.yaml`을 읽어와 테스트벤치에 필요한 상수, DUT 인스턴스화, 포트 연결, 클럭 및 리셋 생성 로직을 동적으로 생성해야 합니다.
    * 생성된 테스트벤치(`sequencer_fsm_tb.sv`)는 다음을 포함해야 합니다:
        * RTL 모듈 (`sequencer_fsm`)의 인스턴스화.
        * 클럭 (`clk`) 및 리셋 (`reset_i`) 신호 생성.
        * DUT 인터페이스 신호 연결.
        * **테스트 시나리오:**
            * 리셋 시퀀스 적용.
            * `RST` 상태에서 `lut_wen_i` 및 `lut_write_data_i` 포트를 사용하여 `sequencer_fsm` 내부의 LUT RAM에 초기 데이터를 로드하는 시뮬레이션 시나리오를 구성 (이는 RTL 시뮬레이터가 `initial` 블록 대신 `lut_wen_i`를 통한 RAM 초기화를 검증하도록 함).
            * 시퀀스 실행 (일정 시간 동안 시뮬레이션 진행).
            * `$monitor`를 사용하여 `sim_fsm.py`의 출력 형식과 일치하는 SystemVerilog 시뮬레이션 로그를 생성합니다. (`Time`, `current_state_o` (hex), `busy_o`, `sequence_done_o`, `dut.lut_addr_reg` (hex), `current_repeat_count_o`, `current_data_length_o`, `current_eof_o`, `current_sof_o`).
            * `$dumpfile` 및 `$dumpvars`를 사용하여 파형(VCD)을 덤프합니다.

### 단계 6: `compare_logs.py` 및 `run_verification.sh` 개발 (자동화된 검증)

* **목표**: Python 시뮬레이션 결과와 RTL 시뮬레이션 결과를 자동으로 비교하고 전체 검증 프로세스를 자동화합니다.
* **작업**:
    * **`compare_logs.py` 스크립트 개발**:
        * `sim_fsm_output.log` (Python 시뮬레이션 결과)와 `rtl_sim_output.log` (RTL 시뮬레이션 결과) 두 파일을 입력받습니다.
        * 두 파일의 헤더 라인을 건너뛰고, 각 라인의 필드(시간, 상태, busy, sequence_done, 주소, repeat_count, data_length, eof, sof)를 파싱하여 비교합니다.
        * 16진수 값 (상태, 주소)은 정수로 변환하여 비교하고, 부울 값 (0/1)은 정수로 비교합니다.
        * 차이가 발견되면 해당 라인을 출력하고 차이점을 보고합니다.
        * 모든 라인을 비교한 후, 전체 일치 여부를 요약하여 출력하고 스크립트 종료 코드를 반환합니다 (성공 시 0, 실패 시 1).
    * **`run_verification.sh` 셸 스크립트 개발**:
        * 이전 시뮬레이션 로그 파일 및 생성된 컴파일 결과물(예: `.vvp`, `.vcd`)을 삭제하여 클린 상태에서 시작합니다.
        * `generate_fsm.py`를 실행하여 최신 `sequencer_fsm.sv`를 생성합니다.
        * `gen_tb.py`를 실행하여 최신 `sequencer_fsm_tb.sv`를 생성합니다.
        * `sim_fsm.py`를 실행하여 `sim_fsm_output.log` 파일을 생성합니다.
        * Icarus Verilog (또는 기타 SystemVerilog 시뮬레이터, 예: VCS, QuestaSim)를 사용하여 `sequencer_fsm.sv`와 `sequencer_fsm_tb.sv`를 컴파일하고 시뮬레이션을 실행하여 `rtl_sim_output.log` 파일을 생성합니다. (시뮬레이터 명령줄에서 `$monitor` 출력을 파일로 리다이렉션).
        * `compare_logs.py` 스크립트를 실행하여 두 로그 파일을 비교합니다.
        * 각 단계의 성공/실패 여부를 검사하고, 실패 시 적절한 메시지를 출력하며 종료합니다.
        * 최종 검증 결과를 요약하여 출력합니다.
        * 생성된 VCD 파일(`sequencer_fsm_tb.vcd`)에 대한 정보를 제공하여 파형 뷰어를 통한 육안 검증이 가능하도록 안내합니다.

---