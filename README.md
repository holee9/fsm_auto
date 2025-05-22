# fsm_auto
fsm fpga 설계 자동화

상태 (State)	설명	3-bit 인코딩
IDLE	대기 상태. 다음 시퀀스를 LUT RAM에서 읽어 판단.	3'b000
RST	시스템 리셋 또는 초기화 작업 수행.	3'b001
BACK_BIAS	백-바이어스 인가/조정.	3'b010
FLUSH	이전 데이터 또는 잔류 전하 플러시.	3'b011
EXPOSE_TIME	이미지 노출 시간 제어 (셔터 등).	3'b100
READOUT	센서에서 데이터 읽기.	3'b101
AED_DETECT	AED (Automatic Exposure Detection) 감지 로직.	3'b110
PANEL_STABLE	패널 안정화 대기.	3'b111

비트 폭을 할당합니다. 이 값들은 LUT RAM에 다음 상태와 함께 저장됩니다.

반복 횟수 (repeat_count): 특정 작업을 몇 번 반복할지 지정합니다.
예: 8비트 (2 
8
 =256회 반복 가능)
데이터 길이 (data_length): 읽거나 처리할 데이터의 길이/크기를 지정합니다.
예: 16비트 (2 
16
 =65536 길이)
EOF (End Of Frame): 프레임 종료를 나타내는 플래그.
예: 1비트 (0 또는 1)
SOF (Start Of Frame): 프레임 시작을 나타내는 플래그.
예: 1비트 (0 또는 1)
총 파라미터 비트 폭: 8+16+1+1=26 비트

파라미터들은 하나의 param_value 필드로 묶어 LUT RAM에 저장

LUT RAM의 각 엔트리는 IDLE 상태에서 특정 **명령 ID (Command ID)**가 주어졌을 때, 다음으로 전이할 상태 인코딩과 해당 상태에서 사용될 파라미터 값을 정의합니다.

LUT RAM 엔트리 필드:

address (명령 ID): IDLE 상태에서 FSM이 수신하는 외부 입력 값 (예: 8비트 커맨드 레지스터 값). 이 주소에 해당하는 LUT RAM 값을 읽어옵니다.
예: 8비트 주소 (총 2 
8
 =256개의 시퀀스 정의 가능)
next_state_encoding: 다음 상태의 3비트 인코딩 값.
param_value: 다음 상태로 전이될 때 함께 전달될 26비트 파라미터 값.
{repeat_count[7:0], data_length[15:0], eof[0], sof[0]} 형태로 비트 연결 (concatenation)하여 저장합니다.
LUT RAM Data Bit Width: 3(next_state)+26(param_value)=29 비트

