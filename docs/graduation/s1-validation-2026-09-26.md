# S1 기준선·CPU 경합·수동 재배치 검증 — 2026-09-26

2026-09-26의 [기준선](#baseline)과 [경합·재배치](#contention) 기록을 통합했다.
아래 수치·실행 ID·한계는 당시 조건의 기록이며 현재 환경의 재검증 결과가 아니다.
이후 자동 복구와 반복 비교 결과는 [최종 평가](final-evaluation-results-2026-10-03.md)를 따른다.

<a id="baseline"></a>

## S1 정상 기준선 실측 — 2026-09-26

### 범위와 환경

이 검증은 [S1 준비 절차](experiments.md#s1-baseline)의 서비스·부하·정상 기준선 단계다. CPU 경합 주입과 Pod 재배치 실험은 포함하지 않는다.

- 환경 실행: `env-df6a58352542`, workload control-plane 1대와 worker 2대.
- 서비스: 단일 HTTP Pod, PBKDF2-SHA256 100,000회, CPU request 250m, CPU limit 없음.
- 요청: workload control-plane의 Job에서 ClusterIP Service로 직접 5 RPS. 각 실행은 60초 워밍업 후 300초 측정한다.
- 배치: 서비스 Pod → worker `osk8s-workload-md-0-s7rz4-2mdjv` → Nova `37432c3e-0eea-4fa5-8263-bcf1ac2fe414` → `osk8s-compute02`. 요청 VM과 대체 worker는 `osk8s-compute01`에 있다. Nova 관리자 조회로 확인했다.
- 증거 위치: `artifacts/cloud-gcp-amd64-greenfield/graduation-s1-baseline-*`의 요청별 `http.jsonl`, 앞뒤 snapshot 및 `summary.json`. 이 디렉터리는 로컬 실행 산출물로 Git에 포함하지 않는다.

처음 `graduation-env-ensure` 실행에서는 workload control-plane Nova VM이 `SHUTOFF` 상태가 되어 Ready 대기 시간이 만료됐다. 기존 guest 기동 절차를 다시 실행하고 환경을 reconcile한 뒤 `graduation-env-ensure`가 완료됐다. 이후 세 기준선 실행에서는 해당 VM과 서비스 Pod 식별자가 유지됐다. 환경 기동 재현성은 별도 확인 과제로 남는다.

### 측정 결과

| 실행 ID | 측정 요청 | 성공 | 성공 RPS | p50 | p95 | p99 | 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| `s1-4142a4c8eb07` | 1,500 | 1,500 | 5.0 | 65.524ms | 74.423ms | 93.034ms | complete |
| `s1-92fd487ab11f` | 1,500 | 1,500 | 5.0 | 65.198ms | 75.007ms | 83.663ms | complete |
| `s1-bb64913eff62` | 1,500 | 1,500 | 5.0 | 65.573ms | 76.736ms | 118.068ms | complete |

세 실행 모두 요청 누락·중복·HTTP 오류가 없고, 측정 전후 서비스 Pod·Nova VM과 인프라 상태가 유지됐다. 마지막 실행에서 요청 Job Pod는 선택한 control-plane Node에서 `Succeeded`로 종료됐다. 서비스·요청·대체 worker의 compute 배치도 전후 동일했다. 마지막 실행의 평균 CPU 사용률은 `compute01` 17.402%, `compute02` 12.322%, CPU pressure `some` 비율은 각각 0.959%, 0.596%였다. 최대 요청 시작 간격은 순서대로 0.209초, 0.207초, 0.209초로 목표 주기 0.2초에 근접했다.

표의 `complete`는 각 실행 당시 코드의 판정이다. 세 실행은 HTTP 기준선 반복 측정이며, 최종 판정 항목인 서비스·요청·대체 worker 배치와 호스트 CPU·PSI 증거를 모두 갖춘 실행은 마지막 한 번이다. 첫 실행에는 compute 배치·호스트 CPU 자료가 없고, 두 번째 실행에도 대체 worker 배치와 PSI 자료가 없다. 이후 추가한 S1 실행 잠금·Pod CPU 카운터 필수 검사·실패 정리 절차는 이 실측 이후 코드에서 검증했으며, 클라우드 기준선은 다시 실행하지 않았다.

사전 짧은 동작 확인(`s1-344569079024`)에서는 10,000회 연산·2 RPS로 15초 측정 요청 30개가 모두 성공했다. 이 결과는 위의 100,000회 연산 기준선 통계에 합치지 않았다.

### 해석

동일 설정의 세 정상 실행에서 p50은 65.2~65.6ms, p95는 74.4~76.7ms로 관측됐다. 이 값은 이 테스트베드의 직접 Service 경로와 해당 부하에서 얻은 기준선이다. 일반 사용자 Ingress 경로의 지연이나 CPU 경합 시 복구 효과를 나타내지 않는다. 다음 S1 단계에서는 이 정상 분포와 호스트 CPU pressure를 바탕으로 서비스 영향 판정 기준을 사전에 고정해야 한다.

### 정리 확인

S1 namespace를 삭제하고 worker 제어를 실험 전 `auto`·1대로 복원했다. 환경 실행이 기동한 `osk8s-controller`, `osk8s-compute01`, `osk8s-compute02`는 모두 `TERMINATED`로 확인됐고, 로컬 workload API 터널도 종료했다.

<a id="contention"></a>

## S1 동일 compute CPU 경합·수동 재배치 실측 — 2026-09-26

### 조건과 증거

[실행 절차](experiments.md#s1-contention)에 따라 기존 S1 HTTP 서비스에 PBKDF2-SHA256 100,000회 연산을 요청했다. workload control-plane의 Job에서 직접 Service로 5 RPS를 780초 동안 유지했다. 먼저 서비스를 `osk8s-compute02`의 worker VM `305f27e8-b1e7-4366-af9a-f1007f9dcd09`에 고정했다. 요청 VM과 목적지 worker VM `5d44af5c-a379-4c0b-8965-8e86740ff776`은 `osk8s-compute01`에 있었다. 경쟁 VM `4e2226aa-9c33-427d-81a6-63c686a5e280`은 Nova의 host 조회로 서비스와 같은 `osk8s-compute02`에 `ACTIVE`임을 확인했다.

최종 실행 ID는 `s1c-757d9ad8ebed`다. 원본은 `artifacts/cloud-gcp-amd64-greenfield/graduation-s1-contention-20260926T095057Z-a6845aa3/`에 보관한다. 이 디렉터리는 로컬 실험 산출물로 Git에 포함하지 않는다. `run.json`에는 Pod·Node·Machine·Nova 식별자와 주입·이동 시각이 있고, `http.jsonl`은 3,900개 요청 원본이다. `hosts-*.json`, `pod-cpu-*.json`, `contender-server.json`, `contender-console.txt`, `summary.json`은 경합과 판정의 근거다.

### 결과

| 구간 | 요청·성공 | p50 | p95 | p99 | 성공 RPS |
|---|---:|---:|---:|---:|---:|
| 정상 60초 | 300/300 | 65.413ms | 76.427ms | 84.647ms | 5.0 |
| 같은 compute CPU 경합 60초 | 300/300 | 133.796ms | 162.559ms | 212.797ms | 5.0 |
| 다른 compute 재배치 후 60초 | 300/300 | 68.796ms | 83.980ms | 104.539ms | 5.0 |

경합 p95는 같은 실행의 정상 구간보다 **2.13배**, 재배치 후 p95는 **1.10배**였다. 미리 정한 영향 기준 1.5배 초과와 회복 기준 1.2배 이하를 모두 만족했다. 전체 **3,900/3,900 요청이 성공**했고 인덱스는 0~3,899에서 누락·중복이 없었다. 재배치 명령 전 10초부터 후 30초까지의 200개 요청에서도 실패가 없었고 최대 지연은 270.666ms였다.

서비스 compute의 구간 평균 CPU 사용률은 정상 **12.421%**에서 경합 **99.780%**로, CPU PSI `some` 비율은 **0.651%**에서 **23.787%**로 올랐다. 목적지 compute의 경합 구간 CPU 사용률은 **16.932%**, CPU PSI는 **0.910%**였다. 경합 전후 서비스 Pod cgroup CPU 카운터는 정상 증가했고 throttling 횟수·시간 증가가 없었다. 따라서 서비스 자체 CPU 제한보다 동일 compute의 별도 VM 작업이 성능 악화의 유력 원인이다. 이는 함께 관측한 배치·서비스 지연·호스트 압박을 바탕으로 한 추론이다.

Deployment의 `nodeSelector` 변경 후 새 Pod UID `f7978a19-c42a-4a12-87eb-119eb6d11886`가 목적지 worker에서 Ready가 됐다. 기존 Pod UID `bbf6dba8-06f5-46a7-9425-e0b2fae8e2ec`와 이미지 ID, 목적지 Nova·compute를 기록했다. 단일 복제본과 요청률은 유지했다. `summary.json`은 당시의 지표 품질·서비스 영향·회복·호스트 압박 조건을 모두 만족해 `passed`로 판정했다.

이 실측은 재배치 이후 경쟁 VM의 Nova 상태와 요청 Job 완료 뒤 호스트 압박을 통과 조건으로 추가하기 전에 수행했다. 저장된 호스트 지표는 이동 후 120초 동안의 압박을 보여주지만, 현재 코드의 `contender-after.json`과 Job 완료 뒤 30초 압박 측정은 없다. 따라서 당시의 `passed`는 현재 추가된 두 조건의 실환경 검증 결과를 뜻하지 않는다.

### 초기 실측의 첫 시도와 정리

첫 시도 `s1c-01de9044f1d9`는 경쟁 VM의 CPU 작업이 실제로 호스트 압박을 만들었지만, 게스트의 `nohup` 출력이 Nova 콘솔이 아닌 파일로 재지정되어 시작 확인 신호를 수집하지 못했다. 안전 검사에서 재배치를 진행하지 않고 `failed`로 종료했으며, 전용 VM·flavor·Job을 삭제했다. 신호 경로를 수정한 뒤 별도 실행 ID로 다시 측정했다. 첫 시도의 요청을 최종 결과와 합치지 않았다.

최종 실행 후 Nova 목록에서 전용 VM·flavor가 각각 0개이고 S1 Job이 0개임을 확인했다. 이동한 HTTP Pod가 종료 직전에도 Ready임을 확인한 뒤 S1 namespace를 삭제하고 worker 제어를 실험 전 `auto`·1대로 복원했다. 환경 실행이 기동한 GCP `osk8s-controller`, `osk8s-compute01`, `osk8s-compute02`는 모두 `TERMINATED`로 확인했다. 당시 코드에서 `make lint`의 150개 테스트와 셸 정적 검사가 통과했다.

### 보강한 판정의 재측정

실행 ID `s1c-5226eabf8dae`로 같은 설정(5 RPS, 연산 100,000회, 780초)을 다시 측정했다. 원본은 `artifacts/cloud-gcp-amd64-greenfield/graduation-s1-contention-20260926T110906Z-4eac2092/`에 보관한다. 정상·경합·재배치 후 60초 구간의 p95는 각각 **90.222ms, 167.182ms, 87.232ms**였다. 경합 p95는 정상의 **1.85배**, 재배치 후 p95는 정상의 **0.97배**다. 전체 **3,900/3,900 요청이 성공**했고 원본 인덱스 0~3,899의 누락·중복이 없으며, 원본에서 재계산한 세 p95가 `summary.json`과 일치한다.

원래 서비스 compute `osk8s-compute02`의 CPU 사용률은 정상 **14.923%**, 경합 **99.738%**, 이동 후 **99.970%**, Job 완료 뒤 30초 **99.964%**였다. 같은 구간의 CPU PSI `some` 비율은 각각 **0.649%, 24.554%, 9.282%, 8.615%**였다. Job 완료 뒤 `contender-after.json`의 경쟁 VM은 같은 compute에서 `ACTIVE`였고, 이동 전후 HTTP 이미지 ID가 같으며 Pod throttling 증가는 없었다. 새 통과 항목 `competitor_active_on_source`, `source_contention_persisted`, `source_contention_at_completion`, `image_unchanged`가 모두 참으로 기록되어 최종 `summary.json`이 `passed`다.

환경 기동 첫 시도에서 workload control-plane VM이 복구 직후 `SHUTOFF`로 바뀌어 준비 검사가 시간 초과됐다. Nova 이벤트의 `stop`을 확인한 뒤 기존 게스트 복구 스크립트로 VM을 다시 기동하고 환경 기록을 reconcile했다. 두 번째 준비 검사에서 control-plane과 worker가 Ready였으며, 그 뒤 S1 fixture를 준비해 위 실험을 시작했다. 시험 뒤 전용 Nova VM·flavor와 S1 Job이 각각 0개였고, S1 namespace를 제거해 worker 제어를 원래 `auto`·1대로 복원했다. 환경 실행이 기동한 GCP 호스트 3대는 모두 `TERMINATED`로 확인했다. 수정 코드에서 `make lint`의 153개 테스트와 셸 정적 검사가 통과했다.

초기 실측과 보강 판정 재측정에서 이 구성의 경합 재현과 **수동** 재배치 효과를 확인했다. 자동 감지·목적지 선택·조치 중복 방지는 아직 구현하지 않았다. 다른 부하 강도나 compute 배치에서 재현되는지, 같은 compute 내 재시작과 비교해 호스트 변경 효과가 얼마나 독립적인지는 후속 실험이 필요하다.
