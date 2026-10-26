# S1 정상 보정 재시도 사전 등록 — 2026-10-26

사용자가 첫 준비 실패 뒤 정상 보정을 한 번 재시도하도록 요청했다. 최초 [프로토콜](s1-baseline-calibration-protocol-2026-10-26.md)의 calibration3×300초→후보 동결→validation2×300초, workload·SLO 선정·검증 수용 규칙을 그대로 사용한다. 실패한 run-v1과 기존 DEV는 보존하며 재사용하지 않는다. 새 artifact는 `artifacts/baseline-calibration-2026-10-26/run-v2/`다. 새 기동 요청부터120분, 그중 cleanup30+down30분 예약을 등록한다. 기존 전체 가동/비용 원장을 이어 쓰며 세션 reserve20000원을 다시 더하지 않는다.

## 이전 증거의 해석 정정

`artifacts/cloud-gcp-amd64-greenfield/workload-status-20261026T102421Z-094cc9a8/0001.json`의19:28:07 KST snapshot은 worker MD의 replicas/readyReplicas/availableReplicas=2, MachinesReady=True, worker/control-plane Nova 모두 ACTIVE를 담고 있다. Node·Pod·Calico는 실제 준비 불충족이 아니라 local API16444 연결 거절로 조회하지 못했다. 따라서 이전 전체 준비 실패를 VM 자체 준비 실패로 단정하지 않는다. 터널이 끊긴 근본 원인은 미확정이며 당시 guest Node 상태를 과거로 소급 채우지 않는다.

## 이번 실행 경로 변경

환경 Ready·기존 터널 확인 뒤, initial worker 준비와 최종 소유 cleanup 동안 local workload API listener를10초 간격 TCP 연결로 확인한다. TCP 연결 실패 때만 기존 `gcp-workload-api-tunnel.sh ensure`를 호출한다. 준비와 cleanup 각각 재연결 최대2회·각60초이며 기존 whole-phase deadline 안에 포함한다. 장시간 VM/worker 명령은 중단·재실행하지 않는다. 실제 VM/Node/Pod/Calico의 준비 조건과 identity/배치 검증은 기존 consumer가 그대로 확인한다. 로컬 터널 재연결은 VM·서비스 복구 조치나 장애 주입이 아니다.

연결 감시기는 첫 정상 요청 전 종료하고 모든300초 측정 중에는 실행하지 않는다. 정상 부하5회 사이의 fixture reset/준비 및 필요한 기존 접속 확인은 매 회 동일하다. 각 연결 실패/재연결 시각·명령 결과·기존 터널 로그를 보존한다. 감시기 자체는 local TCP 연결 확인과 조건부 SSH 연결 준비이며 새 서비스 probe workload를 만들지 않는다. timeout/예외에서 감시기를 종료·회수한 뒤 소유 cleanup으로 이동한다.

cold ensure900초·initial workers600초·매 run420초·매 남은 run의420초 예약·후보 동결60초·최초3600초 work deadline은 그대로다. 연결 재설정이 실패하거나 실제 준비 조건이 충족되지 않으면 동일 deadline에서 중단한다. 관측 축소·상한 자동 연장·성공할 때까지 반복은 없다. 이번 retry도 실패하면 기록·소유 cleanup·호스트 정지 후 인계한다.

원 프로토콜 문서와 이 부록은 registration의 파일명/SHA/복사본으로 동결해 실행 전과 각 run 후 확인한다. code 변경을 먼저 검증·커밋하고 새 snapshot을 만든 뒤 기동한다. 기존 primary 입력 경로 밖에서만 수행한다. 경쟁 VM·장애 주입·A 재시작·DEV·pilot·main은 실행하지 않는다. validation 통과 전 새 confirmed SLO profile을 내지 않는다.
