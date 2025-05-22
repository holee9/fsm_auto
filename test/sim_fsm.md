
---

## 개요

`sim_fsm.py` 스크립트는 Python을 사용하여 FSM의 동작을 모델링하고 시뮬레이션합니다. 이 스크립트는 `fsm_config.yaml`에서 구성 데이터를 읽고 `fsm_lut_ram_data.yaml`에서 LUT RAM 데이터를 읽습니다. 주요 기능은 다음과 같습니다:

- LUT 데이터를 기반으로 한 상태 전환.
- 내부 작업 시뮬레이션.
- 시뮬레이션 중 FSM 상태 및 매개변수 표시.
- 시뮬레이션 보고서 생성.

---

## 주요 구성 요소

### 1. **임포트 및 로깅 설정**
스크립트는 다음 라이브러리를 사용합니다:

- `yaml`: YAML 구성 파일을 파싱하기 위해 사용.
- `logging`: 오류, 경고 및 디버그 정보를 로깅하기 위해 사용.
- `os` 및 `sys`: 파일 경로 유효성 검사 및 스크립트 종료를 위해 사용.

로깅은 기본적으로 경고와 오류를 표시하도록 설정되어 있습니다:

```python
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
```

---

### 2. **`SequencerFSM` 클래스**
`SequencerFSM` 클래스는 FSM을 모델링하고 시뮬레이션을 처리합니다. 주요 메서드와 속성은 아래와 같습니다:

#### **2.1 초기화 (`__init__`)**
- YAML 파일에서 FSM 구성 및 LUT RAM 데이터를 로드합니다.
- FSM 상태, LUT 주소 및 내부 카운터를 초기화합니다.
- 필수 상태(`RST` 및 `IDLE`)의 존재를 확인합니다.

주요 속성:
- `state_encoding_map`: 상태 이름을 인코딩 값에 매핑.
- `encoding_state_map`: 인코딩 값을 상태 이름에 매핑.
- `lut_ram`: 시뮬레이션을 위한 LUT RAM 데이터.

#### **2.2 LUT 데이터 패킹 및 언패킹**
- `_pack_lut_entry`: 단일 LUT 항목을 비트 필드로 패킹.
- `_unpack_lut_data`: 비트 필드를 매개변수 딕셔너리로 언패킹.
- `_pack_lut_entries`: 모든 LUT 항목을 시뮬레이션을 위한 딕셔너리로 패킹.

#### **2.3 상태 전환 로직 (`step`)**
FSM 상태 전환을 다음을 기반으로 처리합니다:

- 현재 상태.
- LUT RAM 데이터.
- 내부 작업 완료 신호.

주요 로직:
- **RST 상태**: 항상 첫 번째 LUT 항목(`0x00`)으로 전환.
- **IDLE 상태**: 프로그래밍된 IDLE 명령과 과도 IDLE 상태를 처리.
- **명령 상태**: 작업을 실행하고 완료 시 `IDLE`로 전환.

#### **2.4 내부 작업 시뮬레이션**
현재 상태를 기반으로 내부 작업 완료 신호를 시뮬레이션합니다:

- `internal_task_done`: 일반 작업 완료 신호.
- `internal_adc_ready`: `READOUT` 상태에 특정.
- `internal_sensor_stable`: `PANEL_STABLE` 상태에 특정.
- `internal_aed_detected`: `AED_DETECT` 상태에 특정.

#### **2.5 표시 및 보고**
- `get_display_info`: 표시를 위한 FSM 매개변수 딕셔너리를 반환.
- `print_header` 및 `print_line`: 포맷된 시뮬레이션 데이터를 출력.
- `generate_report`: 시뮬레이션 요약을 생성.

---

### 3. **시뮬레이션 실행기 (`run_simulation`)**
`run_simulation` 함수는 FSM을 초기화하고 지정된 기간 동안 시뮬레이션을 실행합니다. 주요 작업:

1. 초기 상태를 출력합니다.
2. 지정된 주기 동안 FSM을 단계별로 실행합니다.
3. 최종 상태를 출력하고 시뮬레이션 보고서를 생성합니다.

---

## 코드 구조

### **초기화**
```python
fsm = SequencerFSM(fsm_config_path, lut_ram_config_path)
```
- FSM 및 LUT RAM 구성을 로드합니다.
- 필수 상태(`RST` 및 `IDLE`)를 확인합니다.

### **시뮬레이션 루프**
```python
for _ in range(1, simulation_duration + 1):
    fsm.step()
    if fsm.sim_time == simulation_duration:
        fsm.print_line(fsm.get_display_info())
```
- 지정된 기간 동안 FSM을 단계별로 실행합니다.
- 최종 상태가 출력되었는지 확인합니다.

### **보고서 생성**
```python
print(fsm.generate_report())
```
- 시뮬레이션을 요약합니다. 포함 내용:
  - 총 시뮬레이션 시간.
  - 시퀀스 완료 횟수.
  - 최종 상태 및 매개변수.

---

## 출력 예시

### **시뮬레이션 헤더**
```
Time | State          | Addr | NextAddr | Repeat(L) | Repeat(A) | Length(L) | Timer(A) | EOF | SOF
-----------------------------------------------------------------------------------------------
```

### **시뮬레이션 데이터**
```
0    | RST            | 0x00 | 0x000000 |           |           |           |          |     |    
1    | PANEL_STABLE   | 0x00 | 0x000001 | 1         | 0         | 1024      | 1024     | 0   | 1  
2    | IDLE           | 0x01 | 0x000002 |           |           |           |          |     |    
```

### **시뮬레이션 보고서**
```
--- Simulation Report ---
FSM Name: sequencer_fsm
Total Simulation Time: 3000 cycles
Number of Full Sequence Completions (EOF detected and looped to 0x00): 5

--- Final State ---
Final State: IDLE
Final LUT Address: 0x01
Final Active Repeat Count: 0
Final Data Length Timer: 0
-------------------------
```

---

## 개선 사항 및 권장 사항

### **1. 오류 처리**
- LUT RAM 데이터의 `next_state` 값이 유효한 FSM 상태인지 확인하는 유효성 검사를 추가하세요.
- 무효한 LUT 주소를 경고와 함께 처리하세요.

### **2. 디버깅**
- 상태 전환 및 LUT 데이터 읽기를 위한 디버그 수준 로깅을 추가하세요.

### **3. 코드 가독성**
- 상태 전환 로직을 각 상태 유형에 대한 별도 메서드(e.g., `_handle_rst_state`, `_handle_idle_state`)로 리팩터링하세요.

### **4. 시뮬레이션 유연성**
- EOF 감지 또는 사용자 정의 조건에 따라 동적 시뮬레이션 기간을 허용하세요.

---

## 결론

`sim_fsm.py` 스크립트는 FSM 동작을 시뮬레이션하기 위한 강력한 프레임워크를 제공합니다. 권장된 개선 사항을 적용하면 유지 관리 가능성, 유연성 및 디버깅 용이성이 향상될 것입니다.