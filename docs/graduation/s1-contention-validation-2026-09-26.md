# S1 동일 compute CPU 경합·수동 재배치 실측 — 2026-09-26

## 조건과 증거

[실행 절차](s1-contention.md)에 따라 기존 S1 HTTP 서비스에 PBKDF2-SHA256 100,000회 연산을 요청했다. workload control-plane의 Job에서 직접 Service로 5 RPS를 780초 동안 유지했다. 먼저 서비스를 `osk8s-compute02`의 worker VM `305f27e8-b1e7-4366-af9a-f1007f9dcd09`에 고정했다. 요청 VM과 목적지 worker VM `5d44af5c-a379-4c0b-8965-8e86740ff776`은 `osk8s-compute01`에 있었다. 경쟁 VM `4e2226aa-9c33-427d-81a6-63c686a5e280`은 Nova의 host 조회로 서비스와 같은 `osk8s-compute02`에 `ACTIVE`임을 확인했다.

최종 실행 ID는 `s1c-757d9ad8ebed`다. 원본은 `artifacts/cloud-gcp-amd64-greenfield/graduation-s1-contention-20260926T095057Z-a6845aa3/`에 보관한다. 이 디렉터리는 로컬 실험 산출물로 Git에 포함하지 않는다. `run.json`에는 Pod·Node·Machine·Nova 식별자와 주입·이동 시각이 있고, `http.jsonl`은 3,900개 요청 원본이다. `hosts-*.json`, `pod-cpu-*.json`, `contender-server.json`, `contender-console.txt`, `summary.json`은 경합과 판정의 근거다.

## 결과

| 구간 | 요청·성공 | p50 | p95 | p99 | 성공 RPS |
|---|---:|---:|---:|---:|---:|
| 정상 60초 | 300/300 | 65.413ms | 76.427ms | 84.647ms | 5.0 |
| 같은 compute CPU 경합 60초 | 300/300 | 133.796ms | 162.559ms | 212.797ms | 5.0 |
| 다른 compute 재배치 후 60초 | 300/300 | 68.796ms | 83.980ms | 104.539ms | 5.0 |

경합 p95는 같은 실행의 정상 구간보다 **2.13배**, 재배치 후 p95는 **1.10배**였다. 미리 정한 영향 기준 1.5배 초과와 회복 기준 1.2배 이하를 모두 만족했다. 전체 **3,900/3,900 요청이 성공**했고 인덱스는 0~3,899에서 누락·중복이 없었다. 재배치 명령 전 10초부터 후 30초까지의 200개 요청에서도 실패가 없었고 최대 지연은 270.666ms였다.

서비스 compute의 구간 평균 CPU 사용률은 정상 **12.421%**에서 경합 **99.780%**로, CPU PSI `some` 비율은 **0.651%**에서 **23.787%**로 올랐다. 목적지 compute의 경합 구간 CPU 사용률은 **16.932%**, CPU PSI는 **0.910%**였다. 경합 전후 서비스 Pod cgroup CPU 카운터는 정상 증가했고 throttling 횟수·시간 증가가 없었다. 따라서 서비스 자체 CPU 제한보다 동일 compute의 별도 VM 작업이 성능 악화의 유력 원인이다. 이는 함께 관측한 배치·서비스 지연·호스트 압박을 바탕으로 한 추론이다.

Deployment의 `nodeSelector` 변경 후 새 Pod UID `f7978a19-c42a-4a12-87eb-119eb6d11886`가 목적지 worker에서 Ready가 됐다. 기존 Pod UID `bbf6dba8-06f5-46a7-9425-e0b2fae8e2ec`와 이미지 ID, 목적지 Nova·compute를 기록했다. 단일 복제본과 요청률은 유지했고, 경쟁 VM은 이동 후 관측 동안 실행 상태였다. `summary.json`은 사전 정의한 지표 품질·서비스 영향·회복·호스트 압박 조건을 모두 만족해 `passed`로 판정했다.

## 첫 시도와 정리

첫 시도 `s1c-01de9044f1d9`는 경쟁 VM의 CPU 작업이 실제로 호스트 압박을 만들었지만, 게스트의 `nohup` 출력이 Nova 콘솔이 아닌 파일로 재지정되어 시작 확인 신호를 수집하지 못했다. 안전 검사에서 재배치를 진행하지 않고 `failed`로 종료했으며, 전용 VM·flavor·Job을 삭제했다. 신호 경로를 수정한 뒤 별도 실행 ID로 다시 측정했다. 첫 시도의 요청을 최종 결과와 합치지 않았다.

최종 실행 후 Nova 목록에서 전용 VM·flavor가 각각 0개이고 S1 Job이 0개임을 확인했다. 이동한 HTTP Pod가 종료 직전에도 Ready임을 확인한 뒤 S1 namespace를 삭제하고 worker 제어를 실험 전 `auto`·1대로 복원했다. 환경 실행이 기동한 GCP `osk8s-controller`, `osk8s-compute01`, `osk8s-compute02`는 모두 `TERMINATED`로 확인했다. 최종 코드에서 `make lint`의 150개 테스트와 셸 정적 검사가 통과했다.

한 번의 성공 실행으로 이 구성에서 경합 재현과 **수동** 재배치 효과를 확인했다. 자동 감지·목적지 선택·조치 중복 방지는 아직 구현하지 않았다. 다른 부하 강도나 compute 배치에서 재현되는지, 같은 compute 내 재시작과 비교해 호스트 변경 효과가 얼마나 독립적인지는 후속 실험이 필요하다.
