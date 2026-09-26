# S1 동일 compute CPU 경합·수동 재배치 실험

## 범위와 판정

정상 기준선의 직접 ClusterIP Service 경로, 5 RPS, PBKDF2-SHA256 100,000회를 유지한다. 측정 전에 요청 VM과 다른 compute의 worker로 서비스를 고정해 부하 생성기가 경합 원인에 섞이지 않게 한다. 그 compute에 4 vCPU의 별도 Ubuntu VM을 배치하고, guest 안에서 CPU 작업 4개를 실행한다. CPU 작업 시간은 최소 20분이며 요청 측정 시간에 6분의 여유를 더한 값과 비교해 긴 쪽을 사용한다(측정 최대 30분일 때 CPU 작업 최대 36분). 서비스 Pod는 CPU limit이 없는 단일 복제본으로 유지한다. 다른 compute에 있는 기존 worker로 Deployment의 `nodeSelector`를 변경해 새 Pod가 Ready가 된 뒤 이전 Pod가 종료되도록 한다. 자동 장애 판단·자동 재배치는 다음 구현 단계다.

관측 구간은 경쟁 VM 생성 직전 60초, CPU 작업 시작 뒤 재배치 직전 60초, 재배치 완료 30~90초 후다. 각 구간의 요청별 원본에서 성공률·성공 RPS·p50/p95/p99와 기록 공백을 계산한다. 서비스 영향의 사전 기준은 경합 p95가 정상 p95의 1.5배 초과이거나 HTTP 실패가 증가하는 것이다. 회복 기준은 재배치 후 실패가 0이고 p95가 같은 실행의 정상 p95의 1.2배 이하다. compute 원인의 근거로 서비스 compute의 CPU 사용률 70% 이상과 CPU PSI `some` 비율 2% 이상 또는 정상 구간의 2배 이상을 요구한다. 재배치 후 120초와 요청 Job 완료 뒤 30초에도 원래 compute의 CPU 사용률·PSI가 같은 기준을 만족해야 하며, Job 완료 뒤 경쟁 VM도 그 compute에서 `ACTIVE`여야 한다. 이동 전후 HTTP 컨테이너 이미지 ID가 달라지거나 Pod CPU 카운터가 누락·감소하거나 throttling이 있으면 통과로 판정하지 않는다. 이 값은 이번 실험의 사전 판정 기준이며 일반 사용자 SLO는 아니다.

## 실행

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
bash scripts/gcp-workload-api-tunnel.sh ensure
make graduation-s1-prepare
make graduation-s1-verify
make graduation-s1-contention RATE=5 ROUNDS=100000 SECONDS=780
make graduation-s1-contention-cleanup
make graduation-s1-cleanup
make graduation-env-down
```

작업 환경에서 API 터널을 기동한 셸·실행 세션을 유지한다. 터널이 끊겼다면 재연결 후 같은 실행의 상태를 먼저 확인한다. `graduation-s1-contention`은 준비·기준선·정리와 같은 S1 잠금을 사용한다. 중단 시 `graduation-s1-contention-status`의 실행 ID와 Nova VM·Job 식별자를 확인하고, 같은 환경에서 `graduation-s1-contention-cleanup`을 재시도한다. 소유 Job의 상태와 조회 가능한 로그를 저장한 뒤 Job을 삭제하고 경쟁 VM·flavor도 소유 식별자를 대조해 삭제한다. 한쪽의 정리가 실패해도 다른 쪽은 시도하며 실패 항목을 기록한다. S1 namespace와 원래 worker 모드는 별도 `graduation-s1-cleanup`으로 복원한다.

실행 증거는 `artifacts/<environment>/graduation-s1-contention-*`에 보관한다. `run.json`에는 원래 Pod·VM·compute, 목적지 worker·VM·compute, 주입·이동 시각과 시험 설정을 기록한다. `job.json`, `probe-pod.json`, 요청별 `http.jsonl`, 단계별 호스트 CPU·PSI와 Pod cgroup CPU, 경쟁 VM의 Nova 정보·콘솔 로그, Job 완료 뒤 VM 상태 `contender-after.json`, 구간별 `summary.json`이 재계산 근거다. 실패하거나 실행이 중단되어 별도 정리를 수행하면 Job 삭제 전에 조회 가능한 요청 로그·Job·Pod 상태와 조회 오류를 `failure-evidence.json` 등에 보존한다. 경쟁 VM이 실제 같은 compute에서 `ACTIVE`가 되지 않거나 CPU 작업 시작이 확인되지 않으면 실험을 진행하지 않는다. 결과가 `needs_review`면 장애 재현 또는 회복이 입증된 것으로 해석하지 않는다.
