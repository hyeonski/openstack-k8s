# 기반작업 1순위 수정·종합 검증 — 2026-09-24

단일 운영 클라이언트, 기존 GCP/OpenStack 기반, 내부 자동 증감 시험을 대상으로 코드 검토의 네 결함을 수정하고 실환경 수용 시험을 수행했다. 아래 시간은 UTC다. 상세 원본은 로컬 `artifacts/foundation-final-20260924/`에 보존한다. 실패·준비 구간도 삭제하거나 성공 결과로 덮어쓰지 않았다.

**최종 판정: 기반작업 1~5는 단일 운영 클라이언트·기존 GCP·worker 1~3대의 내부 증감 시험 범위에서 수정과 수용 검증을 완료했다.** 검증 종료 후 GCP 호스트 3대도 원래 중지 상태로 복원했다.

## 수정 내용

| 검토 항목 | 수정 | 검증 근거 |
|---|---|---|
| F1: runner SIGKILL 후 변경 명령이 잠금 밖에서 계속 실행 | 명령 supervisor가 동일한 파일 잠금을 상속하고 부모 생존 pipe를 감시한다. 부모 종료·명령 제한 시간·종료 신호에 자식 process group을 종료하고 회수한 뒤 잠금을 놓는다. | 실제 `kubectl create` 실행 중 runner SIGKILL, 자식과 supervisor 소멸 후 reconcile, 중복 실행 차단. OS 프로세스 기반 회귀 테스트 |
| F2: 가장 최근 표본 하나가 다른 대상의 누락을 은폐 | 고정 호스트와 기대 노드 각각의 시작·중간·끝 공백 검사. manifest의 생성·삭제 수명 반영. 호스트 heartbeat, 노드 filelog heartbeat, Nova 조회 상태로 로그 경로 검사 | 정상 30분, 전체 증감 구간, 개별 수집기·gateway 중단과 복귀 시험 |
| F3: 수동 증감 실패 EXIT trap이 CA를 조기 복원 | 실패 시 CA=0과 복구 journal 유지. 목표 worker 수·안정 상태·CA 소유권 확인 후에만 CA 복원과 journal 해제 | 의도적 수동 timeout, 명시적 recover, 정상 축소, fixed 모드 유지·auto 복귀 |
| F4: 마지막 snapshot만 색인해 짧게 존재한 Pod UID 유실 | schema v2 manifest에 전체 snapshot 및 probe 생성 기록의 UID 합집합, 최초·최종 관측 시각, 삭제된 노드 수명 보존. 기존 manifest 불변 | 최종 56개 snapshot, 자원 5개, 실행 소유 Pod UID 33개 모두 색인. 삭제된 worker 3개 과거 로그·Nova 배치 조회 |

추가로 서로 다른 환경 프로필의 CA가 host gateway와 Kubernetes 수집기에 적용되는 문제를 차단했다. 클러스터 배포 전 CA SHA-256이 다르면 변경 전에 거부한다. Nova inventory 서비스도 선택한 환경 파일을 읽고, `make observability-verify`는 해당 환경의 host cluster 이름을 전달한다. 실제 CA 불일치 거부와 같은 프로필 재배포를 확인했다.

## 정적·단위 검증과 구성 고정

- `make lint`: Python 테스트 **99개**, shell 구문·ShellCheck 등 정적 검사 통과. 최종 설정 기준 기록은 `final-transport/lint.log`이며 앞선 검사도 `lint-final.log`에 보존했다.
- 배포 입력의 수집기 이미지 태그는 `otel/opentelemetry-collector-contrib:0.140.0`이다. 관측된 self-metrics의 `service_version` 값은 `0.140.1`이며, 이미지 태그와 이 값을 원본 그대로 보존했다.
- OpenStack 설정, 두 compute의 실제 nested KVM, management Kubernetes, CAPI/CAPO/ORC, 자격 증명 접근, CA 계층 검증 통과. `layers.log`, `layers-passed.txt`.
- 제어 시험의 동결 기록은 `code-sha256.json`, `final-cycle-code-match.json`이다. 최종 수집기 설정은 `final-transport/code-sha256.json`의 80개 해시로 다시 고정하고 종료 시 대조했다. 비공개 `local.env`도 최종 시험 전 `final-transport/profile-before.json`과 종료 후 `final-transport/final-evidence-check.json`으로 불변성을 확인했다.
- 조회 전후 Calico spec/generation 및 Pod UID가 같음을 확인. `normal-final/read-only-result.json`.

## 1차 구성의 정상 수집 30분

2026-09-24 **11:51:13.505701–12:21:13.505701**, 호스트 3대와 management/workload의 대상별 지표·주기적 로그 경로가 모두 `complete`, `missing=[]`였다. 최대 지표 공백 **15.103181초**, 최대 주기적 로그 공백 **65.000998초**로 시험 기준 120초 이내다.

수집기 8개의 전후 self-metrics에서 전송 실패·수신 거부 증가가 없었고 큐 포화도 없었다. `normal-final/normal-coverage.json`, `normal-final/collector-comparison.json`이 근거다. 과거 누적 오류 카운터가 0이라고 주장하지 않으며 이 구간의 증가량을 비교했다.

## 수명주기와 자동 증감

`lifecycle/exercise.json`에 다음 결과를 보존했다.

1. 전체 제한 시간 60초 실행이 `timed_out`으로 종료되고 새 실행을 차단했다. 명시적 cleanup 후 재실행 가능했다.
2. 부하 Deployment 생성 후 동시 실행을 차단하고 취소 요청을 `cancelled`로 기록했다.
3. cleanup에 SIGTERM을 보내 `cleanup_failed`를 별도 기록했다. resume이 소유 자원을 정리하고 CA의 자연 축소를 기다렸다.
4. **12:52:11.855957** 실제 management probe `kubectl create` 중 runner를 SIGKILL했다. **12:52:14.912237** 자식·supervisor가 모두 사라졌고 내구 상태는 남았다. 중복 실행 차단 → reconcile의 `interrupted` 전환 → resume을 확인했다.
5. 마지막 attempt는 중간 코드·배포 개입 없이 **1→2→3→2→1→2→1** 전체를 통과했다.

이 수명주기 시험의 성공 run은 `autoscaler-run-20260924T122845Z-472b7cc6`, attempt는 `autoscaler-cycle-attempt-003`이다. manifest 구간은 **12:58:35.962892–14:02:06.730313**이다.

| 단계 | 최종 snapshot 시각 | snapshot 수 |
|---|---|---:|
| baseline | 13:00:30.744 | 2 |
| workers 2 | 13:05:10.909 | 4 |
| workers 3 | 13:10:16.311 | 4 |
| workers 2 | 13:25:15.147 | 13 |
| workers 1 | 13:39:38.812 | 13 |
| workers 2 | 13:44:18.376 | 4 |
| workers 1 | 13:59:04.960 | 13 |
| final clean | 14:01:37.740 | 2 |

전체 구간 Cloud Monitoring/Logging 조회는 대상별 수명을 반영해 `complete`, `missing=[]`였다. 최대 지표 공백 **15.515202초**, 주기적 로그 공백 **65.000741초**로 기준 300초 이내다. `cycle-observability/coverage-retry.json`.

소유 Pod UID **33/33**을 manifest에서 확인했다. 삭제된 worker `7d75t`, `5wsjz`, `v28rw` 각각에 대해 과거 로그 5건과 Nova 배치 기록 5건을 조회했고 Node/Machine UID → Nova server ID → `osk8s-compute02` 연결을 확인했다. `cycle-observability/result.json`. 조회 제한 5건은 총 로그 발생량을 뜻하지 않는다.

## 수동 제어와 Pod 실패

수동 scale 2에 상태 제한 시간 1초를 설정해 검증 실패를 유도했다. 공개 명령이 종료된 뒤에도 **CA=0, manual journal 유지**를 확인했다. worker 목표 수렴을 확인하고 `control-recover`로 CA=1과 journal 해제를 확인했다. 이후 정상 scale 1, fixed 모드에서 수동 no-op 후 CA=0 유지, auto 복귀까지 통과했다. `manual/result.json`.

실환경 recover 시점에는 이미 worker가 수렴해 있었다. 따라서 **미수렴 recover 거부는 단위 테스트의 증거**이며 실환경에서 그 분기를 강제로 실행했다고 주장하지 않는다.

작은 실행 소유 Pod에서 `exit 42`를 반복해 **CrashLoopBackOff, restartCount=3**을 관찰했다. **14:22:04.588464** Pod 삭제 후 UID `2f1f2a2f-bb1c-44b9-a91f-14945e8dd1df`로 중앙 로그 **5건**과 재시작 지표 최댓값 **4**를 조회했다. 이전 컨테이너 로그와 Events도 보존했다. `pod-failure/result.json`. 고객 서비스 복구 시간 시험은 아니며 장애 관측·삭제 후 추적 시험이다.

## 수집기 중단·복귀와 최종 상태

개별 compute 수집기와 controller gateway를 순차 중단한다. OpenStack 서비스나 VM은 이 시험에서 중단하지 않는다. 각 중단에는 독립적인 원격 8분 자동 복구 timer를 두고 finally에서도 복원한다.

compute02 수집기는 **14:23:50.016913–14:27:18.824557** 중단했다. 해당 호스트의 CPU·메모리·디스크·네트워크·heartbeat만 누락으로 판정했고 다른 CPU 대상들은 완전했다. 복구 후 5분 구간 전체가 `complete`였다. 생존 수집기 7개에서 오류 카운터 증가가 없었고 재시작한 compute02도 새 프로세스의 오류 카운터가 0이었다. 전·중·후 표본의 큐 크기는 모두 0이었다. `collector-faults/host-collector/{during,after,result}.json`, `collector-faults/counter-analysis.json`.

gateway는 **14:36:19.538035–14:39:19.503912** 중단했다. controller 및 management/workload의 지표·heartbeat·Nova 경로 누락은 정확히 감지했다. 하지만 복구 직후 gateway 로그에 **`Points must be written in order` 및 `Exporting failed. Dropping data.`**가 확인되었다. 기존 병렬 queue consumer가 오래된 표본의 재전송 순서를 바꾸는 문제다. 복구 후 최근 자료가 다시 보이는 것만으로 이 시험을 통과 처리하지 않는다. `final-collector-logs/osk8s-controller.log`에 원본을 보존했다.

최종 카운터에서 새 gateway의 전송 실패 지표가 **27,563 points**였으며, management node-agent는 재시도 소진으로 **로그 55건**을 버렸다. `original-gateway-completed-logs/`, `collector-faults/counter-analysis.json`이 근거다. 실패 points 카운터를 Cloud 저장소의 고유 누락 표본 수와 동일시하지 않는다.

Kubernetes OTLP queue와 호스트의 GMP metric queue에 `num_consumers: 1`을 명시하고, OTLP 재시도 한도를 gateway 기동·gRPC 재연결 시간을 포함한 **10분**으로 정했다. queue 용량은 1,000 batches로 유지한다. exporterhelper의 consumer는 dequeue 병렬도를 제어한다([공식 설명](https://github.com/open-telemetry/opentelemetry-collector/blob/main/exporter/exporterhelper/README.md)). 호스트 JSONL의 heartbeat·Nova 로그도 `body.time`을 timestamp로 파싱해 지연 재생 시 원래 발생 시각을 보존한다([timestamp parser](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/pkg/stanza/docs/types/timestamp.md)).

첫 수정 재시험은 `ordered-queues/`에 분리했다. 순서 역전 오류는 사라졌지만 gateway의 batch processor가 지연된 여러 시점을 합치면서 **동일 시계열의 여러 points를 한 요청에 넣는 오류**가 확인되었다. 초기 캡처에서 4개 드롭 기록, `dropped_items` 합계 2,429가 있었고 이 시험도 실패로 보존했다. 해당 API는 요청마다 시계열별 한 point만 받는다([Cloud Monitoring API](https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/create)).

최종 수정은 gateway의 `metrics/guest`에서 추가 batch processor를 제거해 agent가 만든 각 수집 묶음을 순서대로 전달한다. 증거는 **`final-transport/`**에 분리한다. 호스트 설정 3개와 클러스터 ConfigMap 4개가 생성된 최종 설정과 일치함을 `applied-config-check.json`으로 확인했다.

최종 gateway 중단은 **15:09:26.394150–15:12:23.731490**이다. 중단 중 37개 누락 판정, 관측 최대 queue 16/1,000 batches를 기록했다. 복구 구간 **15:14:00.840540–15:19:00.840540**은 `complete`, 최대 지표 공백 **15.100615초**, 주기적 로그 공백 **65초**였다.

최종 gateway 시험 구간에서 영구 드롭과 전송 실패·수신 거부의 **새 증가량은 0**이며, 새 gateway 프로세스의 해당 누적 카운터도 0이다. 추가 표본에서 모든 queue는 **0**이다. 첫 복구 후 표본에서 정상 전송 중인 gateway 로그 queue 1개가 잡혀 검증 harness가 일단 멈췄다. 원본 `gateway-loss-check.json`을 보존하고 설정·프로세스를 바꾸지 않은 추가 표본(15:22:29 완료)으로 queue가 비워짐을 확인했다. 최종 판정은 **`gateway-loss-check-final.json`**이며 코드 결함으로 처리하거나 최초 표본을 덮어쓰지 않았다.

중단 당시 구간을 다시 조회한 **`gateway-backfill/coverage.json`**에서 management/workload의 지표와 모든 주기적 로그가 복원됐다. guest 지표 최대 공백은 **15.104453초**, 로그는 **65초**다. 중단한 controller 자신의 CPU·메모리·디스크·네트워크는 당시 표본을 생성할 수 없으므로 이 네 누락은 그대로 남았다. 이는 대기 중이던 guest 자료의 전송 손실과 구분한다.

## 최종 구성의 정상 수집 30분

**15:24:52.541650–15:54:52.541650 UTC**의 중앙 수집은 `complete`, `missing=[]`였다. 최대 지표 공백 **15.30386초**, 주기적 로그 공백 **65초**로 기준 120초 이내다. 수집기 8개 모두 전후 오류 카운터 증가가 없었으며, 중간 표본에서도 오류 증가·queue 누적이 없었다. 조회 전후 Calico generation 2와 Pod UID 14개가 유지됐다.

근거는 `final-transport/normal-final/{normal-coverage,collector-comparison,mid-check,read-only-result}.json`이다. 제어 장애 시험 이후 바뀐 실행 파일은 수집기 template 5개이며, 제어 코드는 같음을 `revision-comparison.json`으로 확인했다. 최종 구성의 전체 증감과 종료 상태는 다음 절에 기록했다.

## 최종 구성의 전체 증감과 종료 상태

최종 run은 `autoscaler-run-20260924T155719Z-e3a9687a`, attempt는 `autoscaler-cycle-attempt-001`이다. **2026-09-24T15:58:46.428828+00:00–2026-09-24T17:02:27.008993+00:00**에 **1→2→3→2→1→2→1** 및 마지막 정리를 통과했다. 실행 중 코드·배포·수동 증감 개입은 없었다.

| 단계 | 최종 snapshot 시각(UTC) | snapshot 수 |
|---|---|---:|
| 00-baseline | 16:00:36.326959 | 2 |
| 01-workers-2 | 16:05:14.233320 | 4 |
| 02-workers-3 | 16:10:23.438780 | 4 |
| 03-workers-2 | 16:25:23.476385 | 13 |
| 04-workers-1 | 16:40:20.557877 | 14 |
| 05-workers-2 | 16:44:50.320659 | 4 |
| 06-workers-1 | 16:59:25.171513 | 13 |
| 07-final-clean | 17:01:58.039078 | 2 |

총 **56개 snapshot**, Machine/Node/Nova 관계 **5개**, 실행 소유 Pod UID **33/33개**를 보존했다. 최종 manifest의 `missing_data`는 `[]`다. 중앙 수집은 `complete`, `missing=[]`, 최대 지표 공백 **16.640719초**, 주기적 로그 공백 **65.0초**로 기준 300초 이내다.

삭제된 worker `osk8s-workload-md-0-s7rz4-lxvk8`, `osk8s-workload-md-0-s7rz4-7jfq4`, `osk8s-workload-md-0-s7rz4-vbbvk` 각각의 과거 로그와 Nova 배치 기록을 조회했다. 조회한 기록은 각 경로 5건이며 총 발생량을 뜻하지 않는다. Node/Machine UID → Nova server ID → compute host 연결도 보존했다.

최종 정상 30분 시작부터 전체 증감 종료까지 중앙의 Kubernetes 수집기 오류 검색과 현재 수집기의 원본 로그 검사를 통과했다. 중앙에서 영구 드롭·순서 역전·중복 시계열·파서·최대 표본 빈도 오류 검색 결과는 **0건**, 생존 수집기 **8개**의 오류 카운터 증가량은 0이며 마지막 관측 최대 queue는 **1 batch**이며 큐 포화는 없었다. 삭제된 수집기는 현재 카운터와 혼동하지 않고 중앙 로그 조회 범위에 포함했다. 최대 worker 3대일 때 수집기 10개에서도 오류 증가 없이 queue 0을 확인했다.

공개 `verify`·`probe`와 제어 상태 검사 후 **worker 1대 안정, auto 모드, CA 1개 정상 가동, journal 없음, 실행 소유 잔여 자원 0개**를 확인했다. 실행 파일·설정 **80개**의 해시가 최종 시험 전과 같고 비공개 `local.env`도 사전 기록과 같았다. 이후 **2026-09-24T17:11:13.153488+00:00**에 GCP 호스트 `osk8s-controller`, `osk8s-compute01`, `osk8s-compute02` 모두 **TERMINATED**임을 확인했다. 기존 디스크와 OpenStack 기반은 보존했다.

## 보존한 예외와 범위

- 준비 단계에 기존 호스트/클러스터의 CA 불일치와 TLS 전송 실패가 있었다. 같은 환경으로 정렬한 뒤 쌓인 표본의 replay에서 out-of-order 오류가 **11:47:54.252**까지 발생했다. 원본 로그와 제외 구간을 보존하고 그 이후 별도의 연속 정상 30분을 측정했다. `normal-final/preparation-exclusion.json`, `controller-normal-logs.txt`.
- 최종 설정 재배포 직후 **15:06:43.570** compute02의 GMP 전송에서 최대 표본 빈도 제한으로 실패 points 카운터 **246**이 기록됐다. 최종 gateway 시험 전·후, 정상 30분 전·후, worker 3대 시점과 전체 증감 종료까지 같은 값이며 새 증가는 없었다. 준비 단계 기록 `final-transport/compute02-deployment-logs.txt`와 각 구간의 카운터 표본을 보존했다. 이 카운터를 고유 누락 표본 수로 해석하지 않는다.
- 1차 전체 증감의 로컬 snapshot **2개**에서 Neutron port 목록 조회 직후 삭제가 진행되어 `port show`가 실패했다. `03-workers-2/0009`, `04-workers-1/0009`이며 다음 조회는 회복했다. manifest에 **`missing_data: ["nova"]`를 그대로 보존**했다. 중앙 Nova 주기적 조회와 전체 Cloud 수집 검사는 완전했으나, 모든 로컬 snapshot이 완전했다고 평가하지 않는다.
- 최초 전체 구간 Cloud 조회가 `HTTPError`로 실패했다. 원본 `cycle-observability/coverage.err`를 보존했다. 같은 코드·구간·인자로 다시 조회한 결과가 `coverage-retry.json`이며 성공했다. 최초 HTTP 실패의 상태 코드·원인은 확정하지 않았다.
- 최종 구성의 전체 구간 조회도 첫 두 번은 `HTTPError`로 실패했고, 같은 코드·구간·인자의 세 번째 조회가 성공했다. `final-transport/cycle-observability/query-{1,2}.err`와 `query-3.json`을 모두 보존했다. 실패 응답의 상태 코드·원인은 확정하지 않았으며 수집 누락과 조회 실패를 구분한다.
- 완료 범위는 단일 운영 클라이언트의 내부 시험, worker 1–3대, GCP 지표·로그·UID 추적이다. 다중 운영 클라이언트, worker 자동 복구, 고객 HTTP 연속성·성능·격리, Ingress/HPA/PDB 시나리오, CAPI/CA 내부 reconcile 메트릭과 Grafana 화면은 포함하지 않는다.
- Cloud Logging 검색 보존은 현재 30일, 호스트 JSONL은 일 단위 회전 7개다. GCS 보존 정책과 업로드 명령은 기존 설계를 따른다. 이번 종합 검증 증거는 로컬에 보존했으며 새 GCS 업로드는 수행하지 않았다.

## 주요 원본 증거

| 검증 | 로컬 원본 |
|---|---|
| timeout·cancel·cleanup 중단·실제 create 중 SIGKILL·전체 resume | [수명주기 결과](../artifacts/foundation-final-20260924/lifecycle/exercise.json) |
| 수동 실패·복구·fixed/auto | [수동 제어 결과](../artifacts/foundation-final-20260924/manual/result.json) |
| 실패 Pod 삭제 후 로그·재시작 지표 | [Pod 실패 결과](../artifacts/foundation-final-20260924/pod-failure/result.json) |
| 최종 배포 설정 대조 | [7개 설정 해시](../artifacts/foundation-final-20260924/final-transport/applied-config-check.json) |
| 최종 gateway 오류·queue 배출 | [최종 손실 검사](../artifacts/foundation-final-20260924/final-transport/gateway-loss-check-final.json) |
| 중단 구간의 지연 지표·로그 재조회 | [backfill 조회](../artifacts/foundation-final-20260924/final-transport/gateway-backfill/coverage.json) |
| 제어 시험 이후의 변경 범위 | [실행 파일 해시 비교](../artifacts/foundation-final-20260924/final-transport/revision-comparison.json) |
| 최종 정상 30분의 대상별 연속성 | [중앙 수집 판정](../artifacts/foundation-final-20260924/final-transport/normal-final/normal-coverage.json) |
| 최종 정상 구간의 수집기 전후 오류 증가량 | [카운터 비교](../artifacts/foundation-final-20260924/final-transport/normal-final/collector-comparison.json) |
| 최종 전체 증감의 대상별 연속성 | [중앙 수집 판정](../artifacts/foundation-final-20260924/final-transport/cycle-observability/coverage.json) |
| 전체 UID 색인·삭제된 worker 로그 및 Nova 관계 | [UID 추적 결과](../artifacts/foundation-final-20260924/final-transport/cycle-observability/result.json) |
| 최종 중앙·로컬 수집기 오류 및 해시 검사 | [종료 증거 검사](../artifacts/foundation-final-20260924/final-transport/final-evidence-check.json) |
| worker·CA·journal·소유 자원 정리 | [종료 상태](../artifacts/foundation-final-20260924/final-transport/final-state.json) |
| GCP 호스트 3대 원상 복원 | [중지 확인](../artifacts/foundation-final-20260924/final-host-stop-result.json) |

`artifacts/`는 Git 추적 대상이 아니다. 위 링크는 이번 검증을 수행한 로컬 workspace의 원본을 가리킨다.
