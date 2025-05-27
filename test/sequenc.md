[ ] 기능 구현 요구 사항.
. power on
. reset
. lut ram write
. rese 해제
. state fsm 동작
.. 1. panel stable
.. 1.1. back bias
.. 1.2. flush
.. 2. panel stable 반복 횟수 만큼 1 반복
.. 3. 4~5 실행
.. 4. expose time
.. 5. readout
.. 4~5 반복, 외부에서 shot ready 신호 set 까지 반복
.. 만약 4 에서 shot ready 신호 set 되면 5 상태까지 진행후 expose ready 신호 출력 하고 4로 전이
.. 만약 5 에서 shot ready 신호 set 되면 5 상태까지 진행후 expose ready 신호 출력 하고 4로 전이
.. 4~5 진행후 6 번 진행
.. 6. 1 상태돌아가서 실행
. reset 상태에서 lut ram 의 write / read 가 가능해야함.
. 모든 상태는 반복횟수가 완료후 idle 상태를 거쳐서 lut ram 의 다음 상태를 확인하고 전이되어야 함.
. 비-idle 에서 idle 로 전이되었을때 lut ram 으로 부터 다음을 읽어와야 하므로, lut ram 의 어드레스 제어가 되어야함.
