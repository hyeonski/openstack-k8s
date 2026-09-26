# 중간보고서 구현 범위 점검: S4 worker VM 중단 복구

- 점검일: 2026-09-26
- 기준: [장애 시나리오 정의서](failure-scenarios.md)의 S4와 현재 저장소·로컬 검증 증거

> **2026-09-26 최신 판정:** 이 문서의 미구현 항목과 공수는 착수 전 평가다. S4 완료 여부와 보고서 수치의 최신 점검은 [중간보고서 착수 점검](interim-report-readiness-2026-09-26.md)을 따른다.
- 이 문서는 구현 계획과 판정 기준이다. S4 구현·실험을 완료했다는 기록이 아니다.

> **진행 기록:** 2026-09-26에 공통 환경 준비와 S4 사전 조건(고정 worker 2대, worker MHC, HTTP 서비스와 클러스터 외부 검사 경로)을 구현·실환경 검증했다. 장애 주입과 복구 판정은 아직 수행하지 않았다. 결과와 정리 상태는 [S4 실험 준비 검증](s4-preparation-validation-2026-09-26.md)을 따른다. 아래의 "확인한 현재 상태"는 구현 착수 전 조사 결과다.

## 결론

중간보고서의 구현 목표는 **인프라 기동·검증부터 S4 장애 주입, 복구 관측, 결과 분석, 자원 정리까지 한 명령으로 실행하고, 서비스 회복과 worker 용량 회복을 별도로 검증하는 것**으로 잡는다. S4의 복구 주체는 Kubernetes, MHC, CAPI, CAPO이고, 졸업작품에서 직접 만드는 부분은 재현 가능한 실험 자동화, worker 범위의 MHC 정책 통합, Node–Machine–Nova 관계 추적, 서비스·용량 각각의 완료 판정, 단계별 실행 기록과 실패 분류다.

기본 동작이 통과한 뒤 같은 조건으로 독립 실행을 최소 1회 추가해 재현성을 확인한다. 여건이 되면 세 번째 실행과 실패·보류 경로를 확인한다. 중간보고서에 성공률을 쓰려면 시도 횟수와 실패 시도를 모두 제시한다. S1~S3은 이 단계에서 설계와 후속 구현 대상으로 남긴다.

## 확인한 현재 상태

| 영역 | 확인한 상태 | S4에서 필요한 추가 작업 |
|---|---|---|
| 인프라 | GCP controller 1대·compute 2대, OpenStack·management/workload Kubernetes 구성. 2026-09-24 문서와 artifact에 수용 시험 기록 | 새 실행 시 기동·API·quota·유효 worker 2대 상태 재확인 |
| 기존 제어기 | CAPI v1.13.4, CAPO v0.14.6, MachineDeployment와 CA 설치·증감 검증 | worker만 선택하는 MHC 선언·배포·조건 검증. 현재 `kubernetes/capi/workload-cluster.yaml.tpl`에는 MHC 없음 |
| worker 제어 | `auto`/`fixed` 모드, worker 1~3대 수동 제어와 로컬 잠금 | 실험 중 worker 목표 2대로 고정, CA 소유권 상태 기록. MHC 교체와 수동 증감의 동시 변경 방지 |
| 관계·증거 | `workload_state.py`의 Node/providerID–Machine–OSMachine–Nova 조회, autoscaler 실행 snapshot·UID 추적 | 장애 전후 *동일한 대상*의 시간선과 이전/새 VM·Pod UID 연결. 서비스 기준 결과는 새로 구현 |
| 관측 | GCP 지표·로그 전송과 30분 정상 구간 검증. `observability/openstack-inventory.py`는 읽기 전용 Nova 조회 | 빠른 HTTP 검사와 MHC/Node/Pod/Nova 상태 수집. Cloud 저장소를 현재 복구 판정의 단일 의존성으로 사용하지 않음 |
| S4 서비스 | 시험용 stateless HTTP Deployment, 안정된 서비스 진입점, 요청 기록기 없음 | 외부 검사 위치·HTTP 경로, Deployment/Service, Ready와 실제 응답의 별도 판정 |
| S4 복구 검증 | worker *증감*은 검증했지만 VM 중단 후 MHC 자동 교체는 미검증 | 실제 Nova VM 정지 → Node 이상 → MHC 조치 → 대체 worker Ready의 전체 실험 |

2026-09-24 최종 검증은 자동 `1→2→3→2→1→2→1`, Pod UID 33/33 색인, 최종 `worker=1`·`auto`·CA 1개·잔여 시험 자원 0개를 기록했다. 이는 S4의 기반 증거이며 S4 결과는 아니다. 마지막으로 기록된 GCP host 3대 상태는 모두 `TERMINATED`다. 현재 실시간 GCP 상태 조회는 이 세션의 sandbox가 gcloud 사용자 설정·credential DB 쓰기를 막아 확인하지 못했다. 새 실험 직전 실제 상태를 다시 조회해야 한다.

현재 작업 트리에는 기존 `README.md` 수정과 `docs/graduation/` 미추적 파일이 있다. 이 변경은 보존하고 S4 작업을 진행한다. 로컬 `make lint`는 셸 정적 검사와 Python 테스트 99개를 통과했다.

## 중간보고서에 기록할 S4의 정확한 완료 조건

1. **실험 전제:** control plane·OpenStack 관리 경로 정상, worker 2대 Ready, 대상 HTTP Pod가 주입 대상 worker에서 응답, 다른 worker에 대체 Pod 여유, worker 목표 수 2대, 시험 대상 VM의 providerID/Nova ID가 검증됨.
2. **장애:** 시험 대상 worker Nova VM 한 대만 중단하고 실제 `SHUTOFF` 상태를 확인한다. 단순 Node 삭제나 Pod 삭제는 S4의 장애 주입으로 인정하지 않는다.
3. **서비스 회복:** 장애 영향을 받은 HTTP 요청의 실패/지연을 기록하고, 목표 replica가 Ready이며 실제 HTTP 요청이 사전에 정한 안정화 구간 내내 성공함을 확인한다. 서비스 영향이 없었다면 중단 시간이 아니라 복제본·처리 여력 감소로 기록한다.
4. **worker 용량 회복:** MHC가 대상 Machine을 비정상으로 판정한 근거와 시각, 기존 Machine/OSMachine/Nova의 삭제, 새 Machine/OSMachine/Nova/Node 생성·가입, 목표 worker 2대 Ready 및 신규 worker에서의 시험 Pod 실행을 확인한다.
5. **정리와 기록:** 이전 VM/port 잔여 여부, 시험용 서비스·정책·security group 변경의 최종 상태, 실패·타임아웃·누락 지표를 남긴다. 제어기별 책임과 자체 모듈의 판정 결과를 구분한다.

완료 시간은 하나로 합치지 않는다. 서비스 복구 시간은 *서비스 영향 시작 → 실제 HTTP 안정화*, worker 용량 복구 시간은 *VM 중단 → 목표 worker 2대 Ready와 신규 worker 실행 검사 완료*로 정의한다. 사건 시각은 모두 UTC와 동일 실행 ID로 기록한다.

## 구현해야 할 구성요소와 순서

### 0. 전체 자동화의 실행 계약

자동화는 **공통 환경 준비**와 **시나리오별 실험**으로 분리한다. 공통 단계는 먼저 환경 프로필·자원 상태를 확인한다. 이미 정상인 환경은 재설치·재생성·재기동하지 않고 검증만 한다. 기존 환경의 host나 guest가 정지된 경우에만 필요한 자원을 기동·복구하고 management/workload·관측 경로를 검증한다. 환경 자체가 없는 경우에는 암묵적으로 `lab-up`을 실행하지 않고 별도의 명시적 bootstrap 명령을 요구한다. 성공하면 클러스터 접근 정보, 버전·상태, 시작 전 host 상태, 실행 ID, 유효 기간을 포함한 *환경 준비 기록*을 남긴다. S1~S4 실행기는 이 기록과 실제 상태를 다시 확인한 후 각자 필요한 workload·정책·장애 주입·측정·분석을 수행한다. 공통 준비 단계에서 S4 전용 worker 수나 HTTP 서비스를 변경하지 않는다.

목표 사용자 진입점은 공통 환경 확인·필요시 복구를 담당하는 `make graduation-env-ensure`, 이미 준비된 환경에서 실험만 수행하는 `make graduation-s4-run`, 두 단계를 연결하는 선택적 `make graduation-s4-e2e`다. `graduation-s4-e2e`도 환경이 정상이면 공통 단계가 검증만 하고 곧바로 S4로 넘어간다. S4 실행의 내부 단계는 **환경 상태·준비 기록 검증 → worker 2대 고정 및 HTTP 서비스·MHC 준비 → 장애 주입 → 서비스/worker 복구 관측 → 원본 보존·분석 → S4 소유 자원 정리·원래 worker 제어 모드 복원**이다. 합성 명령은 마지막에 이번 실행이 기동한 GCP host만 종료한다. 조회용 환경 상태/정리 명령과 S4 상태·중단 뒤 대조·정리·재분석 명령도 제공한다. 실제 target 이름은 Makefile 구현 때 확정한다. 사람에게 중간 단계별 명령 입력을 요구하지 않는다.

- 기존 보존 환경에서는 `lab-up`을 매번 부르지 않는다. 이 스크립트는 빈 환경을 위한 bootstrap/IaC apply/클러스터 생성까지 포함하며, 이미 CA가 설치된 기존 workload에서 생성 단계를 재적용할 수 없다. 이미 존재하는 환경은 기존 GCP 호스트 상태 확인, 필요한 호스트만 `gcp-start`, `gcp-openstack-recover`, 현재 CAPI Machine UID에 해당하는 guest만 `observability-workload-guests-start`로 기동한 뒤 각 계층을 검증한다. 빈 환경은 별도 명시적 bootstrap 경로에서 기존 `lab-up`을 재사용한다. 두 경로를 자동 추측해 IaC를 변경하지 않는다.
- 사전 조회는 **정확한 세 호스트 이름과 선택된 `ENV_OVERRIDE_FILE`/IaC state**를 사용한다. 기존 `gcp-status`의 환경 label 필터는 과거 검증에서 빈 결과를 낸 적이 있으므로, 그 결과만으로 호스트가 없다고 판단하지 않는다. 호스트의 시작 전 상태·자동 STOP 시각, 현재 worker 수·CA 모드, CP/worker Nova·Machine UID, 기존 정책·시험 자원을 실행 기록에 저장한다.
- GCP 자동 STOP까지 실험·분석·정리에 충분한 시간이 남지 않으면 장애를 주입하지 않는다. 호스트는 성공·실패 모두에서 **이번 실행이 기동한 것만** 종료한다. 원래 RUNNING이던 호스트는 건드리지 않는다. guest·worker 복구 후 ID가 교체될 수 있으므로 복원 목표는 동일 UUID가 아니라 정상 control plane, 목표 worker 수, 원래 CA 모드, 소유 시험 자원 없음이다.
- 준비·주입·측정·정리를 실행 ID와 원자적 상태 기록으로 분리한다. 재실행 때 진행 중인 실행을 새 실험으로 덮어쓰거나 이미 수행한 VM 정지를 반복하지 않는다. 실패/중단 뒤에는 실제 GCP·Nova·Kubernetes 상태와 기록된 UID를 대조한 후 재개 가능한 단계만 재개한다. 사용자가 별도 작업 중인 클러스터는 범위 밖의 변경이므로 충돌 시 중단한다.
- 종료 흐름은 **원본 증거 저장 → 결과 판정/분석 → 실행 소유 서비스·NodePort/FIP·보안그룹 변경 정리 → 원래 worker 제어 모드 복구 → 합성 명령이 이번에 켠 GCP host 종료**로 잡는다. 독립적으로 띄운 공통 환경은 S4 실행기가 임의로 종료하지 않고 환경 정리 명령에 맡긴다. 실패 시에도 가능한 증거를 저장하고, 합성 실행의 host 기동 비용을 닫되, 소유권이나 실제 상태가 불명확한 자원은 강제 삭제하지 않고 실패 상태와 재조정 진입점을 남긴다.

### 1. 검증 가능한 서비스 경로

- 작은 stateless HTTP 서비스의 Deployment와 Service를 전용 namespace·소유 label로 정의한다. PVC와 노드 로컬 데이터는 사용하지 않는다. readiness와 자원 requests를 명시한다.
- 한 worker에 최초 Pod가 놓이도록 **선호 배치**를 주되, 장애 후 다른 worker에서 기동할 수 있어야 한다. 특정 노드를 반드시 요구하는 selector나 `nodeName`을 Deployment template에 고정하지 않는다. 실행 전 실제 배치를 확인한다.
- 서비스 검사기는 장애 대상 worker 밖의 고정된 관리 위치에서 계속 실행한다. **현재 이 경로는 없음.** 우선 control-plane VM의 기존 Floating IP와 시험용 NodePort의 조합을 검토하고, control-plane의 kube-proxy·보안그룹·route·노드 간 통신을 실측해 확인한다. 이 구성이 맞지 않으면 안정된 다른 관리 위치를 확정한 뒤 장애를 주입한다. 실패 worker 자체의 IP를 검사 대상으로 사용하지 않는다.
- 요청마다 시각, 응답 상태, 지연, 오류 유형을 남긴다. 모니터 중단·네트워크 오류를 서비스 실패로 섞지 않도록 검사기 자체 heartbeat도 기록한다.

### 2. MHC와 worker 제어 정책

- management cluster에 `cluster.x-k8s.io/v1beta2` MachineHealthCheck를 별도 선언한다. 실제 worker Machine에 존재했던 `cluster.x-k8s.io/deployment-name=osk8s-workload-md-0` label로 범위를 좁히고 control plane은 포함하지 않는다.
- `checks.unhealthyNodeConditions`에서 Ready `Unknown`/`False`의 지속 시간을 명시한다. `remediation.triggerIf.unhealthyLessThanOrEqualTo: 1`로 동시에 비정상 worker가 둘 이상이면 새 교체를 막는 방향을 검토한다. 현재 설치된 CRD에서 필드가 지원되는지 배포 전 확인한다.
- MachineSet 소유 worker는 MHC의 복구 대상이다. MHC가 실제로 기존 Machine을 삭제하고 MachineSet/CAPO가 새 VM을 만드는지 상태와 이벤트로 확인한다. [CAPI v1.13 MHC 문서](https://release-1-13.cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking)
- 정지된 Node의 Pod eviction, PDB, Machine drain, 볼륨 분리 대기, Node 삭제 설정을 확인한다. 재현을 위해 이들 제어기를 임의로 건너뛰지 않는다. 이 S4 workload에는 영구 볼륨을 두지 않는다. [CAPI Machine 삭제 절차](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/machine_deletions)
- CA와 MHC가 서로 다른 이유로 worker 수를 바꾸지 않도록 실험 동안 기존 `fixed` 모드로 worker 목표를 2대에 고정한다. MHC는 MachineDeployment replica 수를 유지하는 교체를 담당한다. 실험 종료 시 원래 모드와 상태를 확인해 복원한다.

### 3. S4 통합 관측·완료 판정 모듈

- 기존 `workload_state.Client`의 Kubernetes/OpenStack 조회와 `autoscaler_cycle.identities`의 ID 연결을 재사용하되, S4에 필요한 Pod–Node–Machine–Nova와 이전/새 UID 관계를 명시적으로 검증한다.
- 상태를 정상 기준선 → VM 정지 확인 → Node 이상 → MHC 교체 시작 → HTTP 안정화 → 새 worker Ready → 최종 정리로 기록한다. 서비스와 용량의 완료 상태는 독립적으로 유지한다.
- 누락·모호한 providerID, 다른 Machine을 대상으로 한 MHC, Nova 상태 조회 실패, 목표 worker 불일치, HTTP 검사기 중단은 성공으로 처리하지 않는다. 단계별 대기 상한과 실패 이유를 남긴다.
- 기존 전체 `Client.snapshot`은 여러 API를 순차 조회하므로 매 HTTP 요청마다 실행하지 않는다. HTTP 결과는 짧은 간격으로, Kubernetes/MHC/Nova snapshot은 별도 주기로 수집하고 단계 변화 시 원본을 저장한다.
- 실행 ID, 코드·구성 해시, 관련 UID, 정책 임계값, 요청 패턴, 원본 응답과 판단 결과를 실행별 디렉터리에 보존한다. 중단 뒤에는 기록을 기준으로 실제 자원을 재조회해야 한다. 자동 재실행은 중복 VM 중단을 만들지 않도록 범위를 제한한다.

### 4. 작업 진입점·자동 분석과 국소 테스트

- 상단의 전체 진입점과 내부 단계별 함수는 동일한 실행 상태 파일을 사용하고 기존 `WorkerControl` 잠금·모드 상태와 충돌하지 않게 한다. 소유 label과 UID 조건으로 시험 자원만 정리한다.
- 분석기는 실행 원본에서 HTTP 요청 성공률·오류 유형·지연, 영향 시작·감지·MHC 조치·HTTP 안정화·worker 용량 회복 시각, 이전/새 자원 ID, 최종 잔여 자원을 계산한다. 실행별 JSON/CSV와 중간보고서에 옮길 수 있는 표·시간선 데이터를 자동 생성한다. 원본을 수정하지 않고 재분석할 수 있어야 한다. 조회 실패·관측 공백은 별도 항목으로 표시한다.
- MHC template 렌더링·선택자·한 대만 허용하는 정책, 관계 매핑, 서비스/용량 별도 판정, 데이터 누락과 시간 초과, 결과 시간 계산을 국소 테스트로 확인한다. 기존 99개 테스트와 정적 검사를 다시 통과시킨다.
- GCP·Nova·Kubernetes 외부 명령을 대역한 전체 실행 테스트에서 단계 순서, 실패 직후 증거 보존, 이중 VM 정지 방지, 부분 기동 후 종료, 원래 실행 중인 host 보호, 잘못된 프로필·UID 거부를 확인한다. 정상 환경에서 서비스 경로와 데이터 수집을 먼저 시험한 다음 단일 VM 중단 실험을 실행한다. 실패 시 원본을 보존하고, 원인을 수정한 후 새 실행 ID로 다시 시도한다.

## 실험 순서와 보고서 분석 자료

| 순서 | 실행 | 남겨야 할 자료 |
|---|---|---|
| 1 | 자동 진입점에서 실환경 기동·계층별 상태·quota·worker 2대 확인 | 버전, 배치, 원래 host 상태·CA 모드, Node/Machine/Nova UID, 사전 기준선 |
| 2 | HTTP 서비스/외부 검사 경로 구성·정상 요청 측정 | Deployment/Service 설정, 실제 Pod 위치, 요청 결과, 검사기 heartbeat |
| 3 | MHC 정책 적용·정상 상태 검증 | 렌더링된 spec, CRD 수용, 선택된 worker 2대, control plane 제외 |
| 4 | 대상 Nova VM 정지 및 관측 | Nova 실제 상태, Node condition/taint, Pod 상태, MHC condition/event, 이전 UID |
| 5 | 서비스·용량 각각의 회복 관측 | HTTP 요청별 결과, 새 Pod/Node/Machine/OSMachine/Nova UID, 단계별 UTC 시각 |
| 6 | 독립 실행 최소 1회 추가, 한 가지 보류·실패 경로 국소 검증 | 실행별 원본과 차이, 테스트/실환경 증거의 구분 |
| 7 | 원본 보존·자동 분석·정리·기준선 복원 | 남은 자원 0 또는 명시된 잔여, CA 모드, host 상태, JSON/CSV·표·시간선·한계 |

보고서용 표는 `실행 ID / 요청 수 / HTTP 실패 구간 / 서비스 복구 시간 / worker 용량 복구 시간 / MHC 조치 / 최종 잔여 자원 / 결과`를 권장한다. 그림은 시스템 구성, 직접 구현과 기존 제어기의 책임, S4 시간선 3개를 직접 그린다. 정상·장애·복구 구간을 같은 시간축에 놓고, Pod `Running`과 서비스 정상 응답을 혼동하지 않는다.

## 구현 경계와 주요 확인점

- 중간보고서 구현 완료의 범위는 **S4 한 개 시나리오와 그 재현·판정·증거 수집 기반**이다. S1~S3은 최종보고서까지 이어지는 설계·계획으로 둔다.
- Kubernetes는 Pod를 재생성하고, MHC/CAPI는 비정상 Machine 교체를 시작하며, CAPO는 Nova VM을 관리한다. 직접 구현 성과는 이를 안전하게 연결해 서비스·용량 회복을 구분하고 검증하는 데 있다.
- Kubernetes는 일반 Pod에 `not-ready`/`unreachable` taint에 대한 기본 300초 toleration을 적용할 수 있다. 실제 설치 설정을 확인하고 응답 회복의 지연 요소로 기록한다. [Kubernetes 공식 문서](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)
- worker 2대·한 compute당 4 vCPU/16 GiB의 기존 테스트베드에서 가용 자원·quota와 물리 배치를 먼저 확인한다. 장애 VM 교체 중 다른 worker에 앱 Pod를 수용할 여유가 있어야 한다.
- 새 MHC와 HTTP 진입 경로는 실환경 수용 전까지 설계·국소 테스트 결과로만 표기한다. 최종 합격 조건은 **실제 VM 중단 후 HTTP 서비스 안정화와 대체 worker Ready를 모두 증명하는 것**이다.

하루 8시간은 인프라 준비·복원까지 포함한 S4 전체 자동화를 안정적으로 끝내기에는 빠듯하다. 서비스 진입 경로와 MHC 정책, 관측·판정 모듈, 실행기 수명주기와 원본 기반 자동 분석, 국소 테스트, 실환경 기동·대기·재실행이 모두 필요하다. **총 공수는 기존 11~18시간 추정보다 커질 가능성이 높으며**, 세부 작업의 실제 시간은 구현 중 측정한다. 첫 작업은 기존 보존 환경의 기동·복구 경로와 시험 서비스 진입점을 코드로 고정하는 것이다. 8시간 안에 모든 단계가 끝났다는 가정으로 보고서를 쓰지 않는다.
