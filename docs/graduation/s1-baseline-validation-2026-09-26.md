# S1 정상 기준선 실측 — 2026-09-26

## 범위와 환경

이 검증은 [S1 준비 절차](s1-baseline.md)의 서비스·부하·정상 기준선 단계다. CPU 경합 주입과 Pod 재배치 실험은 포함하지 않는다.

- 환경 실행: `env-df6a58352542`, workload control-plane 1대와 worker 2대.
- 서비스: 단일 HTTP Pod, PBKDF2-SHA256 100,000회, CPU request 250m, CPU limit 없음.
- 요청: workload control-plane의 Job에서 ClusterIP Service로 직접 5 RPS. 각 실행은 60초 워밍업 후 300초 측정한다.
- 배치: 서비스 Pod → worker `osk8s-workload-md-0-s7rz4-2mdjv` → Nova `37432c3e-0eea-4fa5-8263-bcf1ac2fe414` → `osk8s-compute02`. 요청 VM과 대체 worker는 `osk8s-compute01`에 있다. Nova 관리자 조회로 확인했다.
- 증거 위치: `artifacts/cloud-gcp-amd64-greenfield/graduation-s1-baseline-*`의 요청별 `http.jsonl`, 앞뒤 snapshot 및 `summary.json`. 이 디렉터리는 로컬 실행 산출물로 Git에 포함하지 않는다.

처음 `graduation-env-ensure` 실행에서는 workload control-plane Nova VM이 `SHUTOFF` 상태가 되어 Ready 대기 시간이 만료됐다. 기존 guest 기동 절차를 다시 실행하고 환경을 reconcile한 뒤 `graduation-env-ensure`가 완료됐다. 이후 세 기준선 실행에서는 해당 VM과 서비스 Pod 식별자가 유지됐다. 환경 기동 재현성은 별도 확인 과제로 남는다.

## 측정 결과

| 실행 ID | 측정 요청 | 성공 | 성공 RPS | p50 | p95 | p99 | 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| `s1-4142a4c8eb07` | 1,500 | 1,500 | 5.0 | 65.524ms | 74.423ms | 93.034ms | complete |
| `s1-92fd487ab11f` | 1,500 | 1,500 | 5.0 | 65.198ms | 75.007ms | 83.663ms | complete |
| `s1-bb64913eff62` | 1,500 | 1,500 | 5.0 | 65.573ms | 76.736ms | 118.068ms | complete |

세 실행 모두 요청 누락·중복·HTTP 오류가 없고, 측정 전후 서비스 Pod·Nova VM과 인프라 상태가 유지됐다. 마지막 실행에서 요청 Job Pod는 선택한 control-plane Node에서 `Succeeded`로 종료됐다. 서비스·요청·대체 worker의 compute 배치도 전후 동일했다. 마지막 실행의 평균 CPU 사용률은 `compute01` 17.402%, `compute02` 12.322%, CPU pressure `some` 비율은 각각 0.959%, 0.596%였다. 최대 요청 시작 간격은 순서대로 0.209초, 0.207초, 0.209초로 목표 주기 0.2초에 근접했다.

표의 `complete`는 각 실행 당시 코드의 판정이다. 세 실행은 HTTP 기준선 반복 측정이며, 최종 판정 항목인 서비스·요청·대체 worker 배치와 호스트 CPU·PSI 증거를 모두 갖춘 실행은 마지막 한 번이다. 첫 실행에는 compute 배치·호스트 CPU 자료가 없고, 두 번째 실행에도 대체 worker 배치와 PSI 자료가 없다. 이후 추가한 S1 실행 잠금·Pod CPU 카운터 필수 검사·실패 정리 절차는 이 실측 이후 코드에서 검증했으며, 클라우드 기준선은 다시 실행하지 않았다.

사전 짧은 동작 확인(`s1-344569079024`)에서는 10,000회 연산·2 RPS로 15초 측정 요청 30개가 모두 성공했다. 이 결과는 위의 100,000회 연산 기준선 통계에 합치지 않았다.

## 해석

동일 설정의 세 정상 실행에서 p50은 65.2~65.6ms, p95는 74.4~76.7ms로 관측됐다. 이 값은 이 테스트베드의 직접 Service 경로와 해당 부하에서 얻은 기준선이다. 일반 사용자 Ingress 경로의 지연이나 CPU 경합 시 복구 효과를 나타내지 않는다. 다음 S1 단계에서는 이 정상 분포와 호스트 CPU pressure를 바탕으로 서비스 영향 판정 기준을 사전에 고정해야 한다.

## 정리 확인

S1 namespace를 삭제하고 worker 제어를 실험 전 `auto`·1대로 복원했다. 환경 실행이 기동한 `osk8s-controller`, `osk8s-compute01`, `osk8s-compute02`는 모두 `TERMINATED`로 확인됐고, 로컬 workload API 터널도 종료했다.
