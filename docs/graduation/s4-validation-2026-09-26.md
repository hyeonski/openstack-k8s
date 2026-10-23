# S4 준비·장애 주입·자동화·통합 검증 — 2026-09-26

2026-09-26의 단계별 기록을 시간순으로 통합했다.
[준비](#preparation) → [첫 장애 주입](#fault) → [자동 실행·분석](#automated) → [통합·재개 경로](#integration).
각 절의 “아직”, “남은 검증”과 명령 예제는 당시 구현 시점에 해당한다.
현재 절차는 [S4 실행 가이드](experiments.md#s4), 이후 실환경 중단·재개와 반복 결과는
[최종 평가](final-evaluation-results-2026-10-03.md)를 따른다. 원래 실행의 수치·예외·증거 경로는 유지했다.

<a id="preparation"></a>

## S4 실험 준비 자동화 검증 (2026-09-26)

이 기록은 공통 환경 준비와 S4 **사전 조건**의 실환경 검증이다. worker VM 장애 주입과 복구 시간 측정은 아직 수행하지 않았다.

재실행 진입점은 다음과 같다. `graduation-env-ensure`는 이미 정상인 호스트를 다시 시작하지 않고, `graduation-s4-prepare`는 장애를 주입하지 않는다.

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s4-prepare
make graduation-s4-verify
make graduation-s4-cleanup
make graduation-env-down
```

### 공통 환경 준비

- 실환경 프로필: `ENV_OVERRIDE_FILE=config/environments/local.env`, `cloud-gcp-amd64-greenfield`.
- 환경 실행 ID: `env-8ce8680f68c7`. 시작 전 GCP controller 1대·compute 2대는 모두 `TERMINATED`였고, 준비 실행이 세 호스트를 기동했다. 기존 IaC나 클러스터는 재생성하지 않았다.
- 첫 복구 시 workload control-plane Nova VM이 다시 `SHUTOFF`로 남아 workload API 확인이 시간 초과됐다. 환경 기록의 호스트 소유권을 재조정하고 해당 CAPI 게스트만 재기동한 뒤 같은 실행 ID로 준비가 통과했다. 이를 반영해 게스트 기동 스크립트에 `ACTIVE` 안정 확인과 최대 1회 재시도를 추가했다.
- 두 번째 cold start(`env-8a53c39c6e22`)에서도 게스트 안정 검사 1차 실행이 실패했다. 게스트 복구 명령을 직접 재실행하고 환경을 재조정한 뒤 준비가 통과했다. 이어 공통 실행기에 제한된 게스트 복구 재시도와 실패 진단 기록을 추가했다.
- 세 번째 cold start(`env-d27a62139a0f`)는 **수동 개입 없이** 준비 완료됐다. control-plane·worker 게스트 모두 첫 시작 시도 후 `ACTIVE` 안정 확인을 통과했고, management/workload API와 기존 worker 1대가 Ready였다. 공통 실행기의 재시도 분기는 단위 테스트를 통과했지만, 이 세 번째 실환경 실행에서는 필요하지 않아 실제 재시도 상황의 수용 시험은 남아 있다.
- 준비 완료 시 management control plane 1대, workload control plane 1대, worker 1대가 Ready였다. 다시 `graduation-env-ensure`를 실행한 경우 GCP 호스트 시작 시각·ID가 그대로였고, 새 호스트 시작 없이 준비 상태를 확인했다.

### S4 사전 조건

- 기존 `worker-control` 기록의 `auto`·worker 1대에서 시작했다. 기존 제어 경로를 통해 `fixed`·worker 2대로 전환하고 MachineDeployment의 desired/ready/available 2대를 확인했다.
- management cluster에 worker 전용 `MachineHealthCheck`를 배포했다. `cluster.x-k8s.io/deployment-name=osk8s-workload-md-0` 선택자로 MachineSet 소유 worker 2대만 선택하고 control plane 1대는 제외했다. MHC 상태는 `expectedMachines=2`, `currentHealthy=2`였다.
- workload cluster에 PVC 없는 stateless HTTP Deployment 1개와 Service를 배포했다. Pod 1개가 Ready였고, 실제 배치 Node와 Machine UID, `openstack:///` providerID의 Nova VM ID를 연결했다.
- 장애 대상 worker 밖의 클라이언트에서 workload API의 Service 프록시를 통해 `/healthz`를 요청했다. 준비 직후 5회와 독립 재검증 5회, 총 **10/10회 `ok`**였다. 관측 지연의 중앙값은 **273.22ms**, 최대는 **293.98ms**다. 이 값은 API 터널·서비스 프록시를 포함하므로 일반 사용자 ingress 지연으로 해석하지 않는다.
- 원본 snapshot의 `errors`는 비어 있었고, Machine 3대·Node 3대·Nova VM 3대가 기록됐다. 원본과 MHC 객체, worker Machine, 두 차례 HTTP 결과는 [실행 증거](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-preparation-20260926T013427Z-a71fe05b)에 있다.
- 두 번째 독립 준비 실행에서도 MHC `expectedMachines=2`·`currentHealthy=2`, HTTP **10/10회 `ok`**, snapshot 조회 오류 없음으로 통과했다. HTTP 측정 지연 중앙값은 **265.42ms**였다. [두 번째 실행 증거](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-preparation-20260926T020803Z-3d94dc4b)에 원본을 보존했다.

### 정리와 남은 검증

두 S4 준비 실행 모두 전용 MHC·HTTP 자원을 제거하고 worker 1대·`auto` 모드로 복원했다. 각 환경 실행이 기동한 GCP 호스트 세 대만 종료했다. 세 번째 cold-start 검증 후에도 소유 GCP 호스트 세 대가 모두 `TERMINATED`로 돌아왔다. 로컬 정적 검사·단위 테스트는 `make lint`에서 117개가 통과했다.

이 기록은 S4 복구 성공 증거가 아니다. 다음 실험에서는 동일 준비를 다시 실행한 후 정확한 Nova worker VM 한 대를 중단하고, HTTP 서비스 안정화와 대체 worker 용량 회복을 독립적으로 측정해야 한다. 현재 HTTP 측정 경로는 Kubernetes API Service 프록시이므로, 최종 결과를 일반 서비스 ingress 기준으로 제시하려면 별도 고정 진입 경로를 검증해야 한다.

<a id="fault"></a>

## S4 단일 worker VM 중단 실험 검증 (2026-09-26)

이 문서는 S4의 첫 실환경 장애 주입 결과다. 공통 환경 준비와 S4 사전 조건은 별도 실행했다. **한 번의 성공 실험이므로 반복 성공률이나 일반 서비스 ingress 성능을 의미하지 않는다.** 모든 시각은 UTC다.

### 실행과 대상

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s4-prepare
make graduation-s4-run
make graduation-s4-cleanup
make graduation-env-down
```

- 환경 실행 ID: `env-ea29d76bad1d`; S4 실행 ID: `s4-e7a4fd084e56`.
- worker 목표 2대와 MHC `expectedMachines=2`, `currentHealthy=2`를 확인했다. Pod–Node–Machine–Nova 매핑과 HTTP 사전 검사 5/5, 전체 baseline snapshot의 조회 오류 없음, GCP 호스트 ID 및 자동 STOP 잔여 시간을 확인한 뒤 주입했다.
- 대상 HTTP Pod UID: `85e601fb-2d1a-431d-97fb-6b3c723a669e`; 대상 Machine UID: `0269c8f2-bedd-4600-9e19-50c82e2e6131`; 대상 Nova VM: `e205ace2-f83e-4d9f-891d-e69cdc753706`.
- Nova `server stop` 명령을 이 UUID에만 실행하고 `SHUTOFF`를 별도 조회로 확인했다. 다른 worker와 control plane VM은 중단 대상에서 제외했다.

### 관측 결과

| 사건 | UTC 시각 | 근거 |
|---|---|---|
| VM 중단 명령 직전 기록 | 02:56:54.884 | 내구 `stop-intent` 기록 |
| 첫 HTTP 실패 표본 | 02:57:04.989 | 외부 `kubectl` Service proxy 요청 로그 |
| 대상 VM `SHUTOFF` 확인 | 02:58:07.749 | Nova 개별 조회 원본 |
| 마지막 HTTP 실패 표본 | 02:58:15.193 | 요청별 원본 |
| 첫 정상 HTTP 응답 | 02:58:16.503 | 요청별 원본 |
| MHC의 기존 Machine 삭제 시작 | 02:59:45 | Machine deletionTimestamp와 `UnhealthyNode` 조건 |
| 목표 worker·신규 worker HTTP 검사 첫 충족 표본 | 03:01:31.320 | 2대 Ready, 기존 Machine/Node/Nova 제거, 새 VM ACTIVE, 새 worker 검사 Pod Ready |
| 안정화까지 충족한 최종 표본 | 03:02:14.447 | MHC 2/2, MachineDeployment 2/2, 신규 worker의 HTTP 검사 Pod Ready |

중단 명령 이후 수집한 HTTP 요청 **226회 중 29회가 실패**했고 197회가 성공했다. 첫 실패 표본에서 첫 정상 응답 표본까지 **71.515초**였다. 이는 요청 간격과 최대 5초 API 타임아웃을 포함한 *관측 구간*이며 실제 서비스 중단의 정확한 시작·종료 시각은 아니다. 초기 실패에는 API Service proxy의 응답 타임아웃과 `no endpoints available`이 모두 포함된다. Service proxy는 workload API 터널을 거치므로 일반 사용자 ingress의 지연/가용성으로 환산할 수 없다. HTTP 성공은 이후 30초 이상 연속으로 확인했다.

MHC는 Node `Ready=Unknown`이 2분 넘게 지속됐다는 이유로 원래 Machine을 삭제했다. 대체 Machine UID `98aa95c2-bd1b-4221-ad7c-5211d07a70f4`, 새 Nova VM `dc99ee16-7ab7-4a23-be18-6d453512fe14`가 생성됐다. 두 worker의 Machine·Node가 Ready, MHC 2/2, MachineDeployment 2/2/2, 새 Nova VM ACTIVE였다. 원래 Machine·Node·OpenStackMachine·Nova VM은 최종 목록에서 사라졌으며, 새 worker에 별도 검사 Pod를 실행해 클러스터 내부 HTTP 서비스를 읽었다. `SHUTOFF` 확인부터 목표 용량과 검사 Pod의 **첫 충족 표본까지 203.570초**, 안정화 확인까지 **246.697초**였다. HTTP 복구와 worker 용량 복구는 각각 독립 판정했다.

### 원본과 해석상 주의

- [실행 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T025550Z-e022fb3e): `baseline.json`, `stopped-nova.json`, `http.jsonl`, `observations/*.json`, `result.json`, `run.json`.
- 실행 도중 초기 집계기가 `SHUTOFF` **확인 이후**의 HTTP 요청만 계산해 6회 실패로 표시했다. 전체 중단 명령 이후 구간을 재계산해 `result.json`과 `run.json`을 정정했으며, 이전 결과는 `result-original.json`에 보존했다. 정정 시각·이유도 `analysis_revision`에 남겼다.
- API 요청은 약 1초 간격으로 시작하도록 했지만 5초 타임아웃 때 다음 표본 간격이 늘었다. 관측 시작 시각 간 최대 공백은 약 6.114초다. 이 실험만으로 엄밀한 사용자 체감 중단 시간이나 통계적 성공률을 주장하지 않는다.
- 복구 동작은 Kubernetes의 Pod 재배치와 MHC·CAPI·CAPO의 Machine/VM 교체가 수행했다. 자체 S4 모듈은 정확한 대상 확인, 단일 장애 주입, 서비스와 용량의 별도 관측·판정 및 원본 보존을 담당했다.

### 정리 상태

S4 전용 MHC·HTTP 서비스·검사 Pod를 제거하고 원래 `auto` 모드·worker 1대로 복원했다. 환경 실행이 시작한 GCP controller와 compute 2대, 총 세 호스트만 중단했으며 2026-09-26 03:14:03 UTC 최종 조회에서 모두 `TERMINATED`였다.

<a id="automated"></a>

## S4 통합 실행·자동 분석 검증 (2026-09-26)

공통 환경 준비와 시나리오 실행은 분리한다. 이미 Ready인 환경에서는 `make graduation-s4-run`이 S4 fixture 준비, 단일 worker VM 정지, 서비스·용량 관측, 원본 분석, 소유 자원 정리를 한 번에 수행한다. 호스트가 정지된 환경에서 전체 과정을 실행하려면 `make graduation-s4-e2e`를 사용한다. 이 명령의 환경 단계는 기존 자원만 확인·기동하며, 종료할 때 **그 환경 실행이 기동한 GCP 호스트만** 중단한다. 독립 재분석은 호스트가 꺼져 있어도 `make graduation-s4-analyze`로 실행할 수 있다. 과거 실행은 `EVIDENCE_DIR=... make graduation-s4-analyze`로 선택한다.

분석기는 원본 `http.jsonl`의 **Nova stop 명령 직전 기록부터** 요청을 재집계한다. Kubernetes API 프록시 연결 실패와 Service 엔드포인트 부재를 분리하고 Node taint, Pod 퇴출·대체 Ready, MHC 삭제, 신규 worker HTTP 검사와 용량 안정화를 같은 UTC 시간선에 놓는다. 산출물은 각 실행의 `analysis/summary.json`, `http-requests.csv`, `infrastructure-timeline.csv`, `events.csv`, `report-row.csv`, `report-table.md`다. 원본 파일의 SHA-256을 결과에 남기고 원본 자체는 수정하지 않는다. 관측 공백·조회 오류·중단 후 재개 여부도 별도 표기한다.

### 독립 실험 비교

| 실행 | stop 이후 HTTP 성공/전체 | API 프록시 오류 / 엔드포인트 부재 | 첫 실패→첫 정상 응답 | Node 이상 판정 대기 | Pod 퇴출 대기 | `SHUTOFF`→worker 안정화 |
|---|---:|---:|---:|---:|---:|---:|
| [1차 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T025550Z-e022fb3e) `s4-e7a4fd084e56` | 197/226 | 7 / 22 | 71.515초 | 39.011초 | 30.000초 | 246.697초 |
| [2차 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T034042Z-3bd154aa) `s4-055ac54a8adf` | 191/221 | 7 / 23 | 73.413초 | 41.161초 | 30.000초 | 246.495초 |

두 실행 모두 Node 이상 판정 후 명시한 30초 toleration이 만료됐고, 새 Pod는 그 약 2초 뒤 Ready였다. MHC가 기존 Machine을 삭제하고 CAPO가 다른 Nova VM을 만든 뒤 worker 2대와 신규 worker HTTP 검사 Pod가 안정화됐다. 첫 실패→첫 정상 응답 값은 표본 간격과 5초 API 타임아웃의 영향을 받는 **관측값**이다. 검사 경로가 Kubernetes API Service proxy이므로 일반 사용자 ingress 중단시간이나 성공률로 해석하지 않는다. 두 번의 독립 성공은 경로 재현을 보여주지만 통계적 신뢰도나 모든 장애 조건의 성공률을 뜻하지 않는다.

1차 분석에서 초기에는 `SHUTOFF` 확인 **이후**의 요청만 세는 오류가 있었다. 4단계 분석기는 stop 명령 직전 기록을 기준으로 원본 전부를 재계산해 두 실행 모두 같은 규칙으로 비교한다. 1차의 이전 결과는 `result-original.json`으로 남아 있다.

### 검증 범위와 복원

국소 테스트는 통합 단계 순서, 이미 준비된 환경에서 불필요한 환경 단계를 건너뛰는 경로, 불확실한 장애 주입 시 소유 자원과 호스트를 강제로 정리하지 않는 경로, HTTP 오류 분류와 안정화 판정을 확인한다. 실환경에서는 `graduation-s4-e2e`로 준비→주입→분석→정리→호스트 종료를 **추가 명령 없이** 실행했다. workflow 실행 ID는 `s4-workflow-b55529d05af2`, 환경 실행 ID는 `env-38e5981ef9a2`다. 환경 준비 중 control-plane 게스트가 첫 안정화 검사에서 실패했지만 제한된 재시도로 무개입 복구됐다.

최종 `finalization.json`과 재분석된 `summary.json`에서 S4 fixture는 `restored`, worker 제어는 원래 `auto`·1대, 환경은 `stopped`였다. GCP controller와 compute 2대가 모두 `TERMINATED`로 확인됐다. 실환경 종료 시 workflow·S4 실험·분석 상태는 각각 `completed`·`completed`·`complete`였다.

<a id="integration"></a>

## S4 5단계 통합 검증 (2026-09-26)

### 실행 경계

공통 환경과 S4 시나리오는 독립 실행할 수 있다. 호스트 3대가 `TERMINATED`인 상태에서 `graduation-env-ensure`로 **기존** 호스트와 게스트를 회복했고, 환경 실행 `env-e1e936b809fd`가 `ready`가 된 뒤 `graduation-s4-run`만 호출했다. 상위 workflow `s4-workflow-f02d8106c5c3`의 모드는 `scenario`이고 `ensuring-environment` 단계 없이 준비→주입→관측→분석→정리를 완료했다. 시나리오 종료 당시 환경은 `ready`로 남았으며, 별도 `graduation-env-down`으로 이번 환경 실행이 켠 호스트 3대만 중지했다.

정상 환경에서 `graduation-env-ensure`를 한 번 더 실행한 결과, 동일 환경 실행 ID와 `started_hosts` 소유권을 유지하고 실제 호스트·클러스터 상태만 조회해 약 8초 만에 종료됐다. 이 경로는 SSH 대기, OpenStack 복구, 게스트 시작 루틴을 다시 호출하지 않는다. 상태 검사가 실패하면 기존 복구 경로로 돌아간다.

### 세 번째 독립 실험

원본: [S4 실행 디렉터리](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3). 실행 ID `s4-ec4f3851e726`, 원본 기반 [분석 요약](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3/analysis/summary.json), [보고서 표](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3/analysis/report-table.md).

| 항목 | 관측값 |
|---|---:|
| Nova stop intent 이후 HTTP 성공/전체 | 182/212 |
| API Service proxy 연결 실패 / Service 엔드포인트 부재 | 8 / 22 |
| 첫 HTTP 실패→첫 정상 응답 | 78.649초 |
| 첫 실패→Node 이상 판정 | 46.474초 |
| Node 이상 판정→Pod 퇴출 | 30초 |
| Pod 퇴출→대체 Pod Ready | 1초 |
| `SHUTOFF` 확인→worker 용량 안정화 | 245초 |

실험·분석 상태는 각각 `completed`·`complete`이며, 인프라 스냅샷 조회 오류와 중단 후 재개 공백은 없었다. HTTP 표본 시작 간격 2.5초 초과 구간은 8개였다. 이 HTTP 경로는 Kubernetes API Service proxy이므로 78.649초를 일반 사용자 ingress의 중단시간으로 해석할 수 없다. 1·2차 결과와 비교하면 [이전 통합 검증](s4-validation-2026-09-26.md#automated)의 첫 실패→성공 71.515초·73.413초, 용량 안정화 246.697초·246.495초와 같은 범위의 재현 사례다. 표본 3회는 성공률의 통계적 추정치가 아니다.

### 중단·재개와 최종 정리

상위 실행기에 `make graduation-s4-resume`을 추가했다. `stop-intent`가 같은 환경·실험 기록에 있을 때에만 개별 실험의 `observe`로 이어지며 **Nova stop을 재호출하지 않는다**. 관측 중단으로 표본 공백이 생기면 분석의 `incomplete`를 보존하고, 다른 오류가 없고 서비스·용량 회복 증거가 충분한 경우에만 workflow를 `completed_with_gap`으로 표시한다. 불확실한 stop 결과나 다른 실행 ID는 거부한다. 정리 중단 시에는 이미 제거한 자원을 다시 소유권 확인하며 정리하고, 호스트 종료 중단 시에는 소유 호스트만 재대조한다.

이 재개·거부·중단 단계는 외부 명령 대역 테스트로 검증했다. **실환경에서 의도적으로 장애 실험 프로세스를 중단해 재개한 것은 아니다.** 실환경 통합 검증은 중단 없는 독립 3차 실행이며, 재개 경로의 실제 장애 후 동작은 최종보고서 전 추가 검증 대상으로 남긴다.

정리 후 S4 fixture는 `restored`, worker 제어는 원래 `auto`·1대, 환경 기록은 `stopped`다. GCP controller·compute 2대 모두 최종 `TERMINATED`로 확인됐다. 시나리오의 `finalization.json`은 해당 시나리오 종료 시점에 환경이 `ready`였음을 기록한다. 별도 환경 종료의 최종 상태는 `graduation-environment.json`에 남는다. `make lint`와 단위 검사는 최종 코드로 다시 실행한다.
