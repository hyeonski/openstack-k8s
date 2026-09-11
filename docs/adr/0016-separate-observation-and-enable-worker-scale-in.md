# ADR-0016: 환경 준비·관측·능동 검사를 분리하고 worker 1~3대 자동 증감을 검증한다

- 상태: 채택됨 — 구현·로컬 검증·실환경 수동 및 자동 증감 수용 통과(2026-09-11)
- 결정일: 2026-09-11
- 관계: ADR-0013/0014 유지. ADR-0015의 계층 순서와 증거 보존 원칙을 유지하고, 8·9단계의 증감 범위를 확장한다. ADR-0015 원문과 과거 결과는 변경하지 않는다.

## 배경

조회 중 Calico 설정을 patch하면 관측 실패가 구성 변경으로 가려진다. 또한 기존
CA 시험은 CPU requests로 Pending을 만든 worker 1→2 증설이며, 자동 축소나
고객 HTTP 요청 처리의 증거가 아니다. 고정 이름의 시험 Pod가 남으면 이후 축소를
방해하고, 노드 개수만 세면 삭제 중인 Machine이나 고아 Neutron 포트를 놓친다.

## 결정

### 계층과 용량

- GCP controller 1대·compute 2대는 고정한다. management kind/CAPI/CAPO/CA는 controller에서 실행한다.
- workload control plane은 Nova VM 1대 고정, worker Nova VM은 min=1/max=3, 총 VM 2~4대다.
- compute별 4 vCPU·16 GiB, CP/worker별 2 vCPU·2 GiB·20 GB를 유지한다. 3 workers는 기능 검증 상한이며 성능 여유의 검증값이 아니다.
- GCP 호스트 수·사양, flavor, quota, 초과 할당 정책을 변경하지 않는다.

### 명령 책임

| 책임 | 진입점 | 부작용과 판정 |
|---|---|---|
| 환경 준비 | `workload-cluster-create`, `workload-cluster-prepare` | 구축 시 Calico 설치 및 의도한 probe 설정 적용. 기존 환경에서는 prepare를 명시 호출 |
| 상태 조회 | `workload-cluster-status`, `workload-cluster-verify` | 기존 kubeconfig로 GET/목록 조회. verify는 동일 관측을 제한 시간 동안 반복. 구성 patch·복구·시험 Pod·터널 자동 생성 없음 |
| 능동 검사 | `workload-cluster-probe` | management의 TCP API 접근, 클라이언트의 API readyz, 각 Node에서 CNI/DNS 확인. 실행별 UID/label을 가진 임시 Pod 사용 |
| 수동 증감 | `workload-cluster-scale WORKERS=1..3` | CA replica 저장→중지→이전 소유 시험 자원 증거 저장·정리→MD scale→조회·능동 검사→CA 원래 replica 복원 |
| 자동 증감 | `cluster-autoscaler-test` | CA를 계속 실행하고 시험 Deployment의 replica만 변경. MD/Node/Nova 직접 증감 금지 |

상태는 ready(0), preparing(10), mismatch(20), unavailable(30), timeout(40)으로
나눈다. 조회 API 오류를 0개 자원으로 변환하지 않는다. 삭제 중·부팅 중·desired와
available의 차이는 preparing이다. 구성 drift는 명시적인 prepare가 필요하며 즉시
실패한다. verify는 기본 3,600초 이내 수렴해야 하며, 마지막 관측 상태도 보존한다.
`make` 자체는 하위 명령의 nonzero를 일반 실패 코드로 반환하므로 자동화는 JSON
결과 또는 스크립트의 직접 종료 코드를 사용한다.

### CA v1.35.0 정책

- `scale-down-enabled=true`, node group annotation `1:3`.
- scan 10초, 신규 Pod 증설 판단 지연 30초. Pending은 실시간 상태 또는 해당 Pod UID의 FailedScheduling 이벤트로 입증한다.
- 증설 후 축소 대기 10분, 불필요 노드 유지 10분, 삭제 후 1분, 실패 후 3분.
- 축소 utilization threshold 0.5(CPU/메모리 requests), unready 유지 20분, 동시 축소 1대.
- 시스템 Pod 이동 허용(`skip-nodes-with-system-pods=false`). 단일 worker로 복귀할 때 복제된 CoreDNS/Calico controller가 후보 노드에 있다는 이유만으로 제외하지 않는다. PDB·배치 가능성 검사는 그대로 적용하며 로컬 저장소 보호는 유지한다.
- Pod 종료 대기 600초, provisioning 15분은 고정 CA 기본값을 명시한다. 실패하면 이 기준을 늘려 통과시키지 않는다.

CPU 실제 사용률이나 HTTP 요청량은 본 시험의 증감 신호가 아니다. 시험은 최초
worker의 기존 requests와 allocatable을 저장하고, 빈 worker에서도 둘이 들어갈 수
없도록 allocatable의 절반보다 큰 CPU request를 선택한다. 그 값이 현재 가용
requests 예산을 넘으면 자원 부족으로 실패한다. 이후 requests는 변경하지 않고
replica만 조정한다. 각 단계에서 실제 Pod requests·Ready·배치 Node·종료 중 Pod
부재를 확인한다. 향후 requests를 변경한다면 기존 Pod UID가 교체되었거나 실제
resize 반영이 완료됐다는 검증을 추가해야 한다.

### 수용 경로와 증거

1. ADR-0015의 1~7계층을 선행 확인한다. 계층 실패를 복구로 숨긴 채 상위 시험을 진행하지 않는다.
2. 수동 1→2→3→2→1에서 CA 중지/복원과 상태·API/CNI/DNS를 확인한다.
3. 자동 1→2→3→2→1을 검증하고, 다시 1→2→1을 실행한다. 시험 replica는 2,3,2,1,2,1이다.
4. 단계마다 기본 3,600초 제한, 목표 상태 연속 60초 유지, CAPI/MD/MS/Machine/OSM/Node/Nova 식별자와 시각을 보존한다. 신규 Pod UID에 연결된 `TriggeredScaleUp`, 삭제 Node UID에 연결된 `ScaleDown` 이벤트와 CA 로그를 요구한다.
5. 삭제된 worker의 Machine/OSM/Node/Nova server 및 Nova device ID로 확인한 Neutron port/FIP가 사라졌는지 대조한다. 남은 CP·worker의 UID/providerID, shared network/subnet/router/security group과 유지되는 FIP를 보존한다. prefix는 의심 잔존 서버 탐지에만 사용하며 삭제 권한으로 사용하지 않는다.
6. 매 단계 management→workload API, 모든 Node의 CNI/DNS, 신규 worker의 고아 calico-ipam 부재를 검사한다. 최종 시험 Deployment와 Pod를 정리하고 1 worker 및 능동 검사를 재확인한다.

PDB·affinity·local storage·자원 부족 등은 Pod/PDB JSON, CA 이벤트·로그,
Machine 삭제 조건과 OpenStack 상태로 조사한다. 시간 초과 후 강제 drain, PDB
변경, 직접 Nova 삭제나 수동 scale로 자동 시험을 성공 처리하지 않는다.

### 소유권과 정리

새 시험은 `test.openstack-k8s.io/cluster`와 실행별 `.../run` label, 무작위 이름,
생성 UID를 남긴다. 능동 검사 성공 시 JSON/events/log를 저장한 뒤 해당 UID를
조건으로 삭제한다. 실패하면 자원과 증거를 남긴다. 기존 시험 잔존은 새 자동
시험을 차단한다. 명시적인 `cluster-autoscaler-test-cleanup` 또는 수동 증감의
준비 단계가 저장→정리하며, 기존 고정 이름 2종은 정확한 이름과 기존 part-of
label을 함께 검사한다. 소유 표시 없는 동명 자원을 삭제하지 않는다.

한 운영 클라이언트 내 자동 시험·수동 증감·명시 정리는 파일 잠금으로 중복 실행을
차단한다. 다른 클라이언트나 운영자와의 동시 변경은 금지한다. 분산 실행기,
자동 재개·강제 정리·보존 기한 정책은 이번 범위가 아니다. CA 원래 replica와
복원 결과를 artifact에 저장하고 정상 종료·실패·신호 종료 시 복원을 시도한다.
SIGKILL/클라이언트 소실 시에는 저장된 값을 근거로 별도 복원해야 한다.

## 검증과 한계

[실행 절차와 이번 결과](../worker-autoscaling-validation.md)를 따른다. 구현·로컬
회귀 테스트 통과와 실환경 수용을 구분한다. 본 범위는 인프라 자동 증감과 상태
검증이며 고객 HTTP 요청의 무중단 처리, 성능·비용 개선, worker 자동 복구를
입증하지 않는다.

## 고정 버전 공식 근거

- [CA 1.35.0 FAQ](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.35.0/cluster-autoscaler/FAQ.md): requests·배치 판단, 축소 지연/보호 설정, 이벤트 종류.
- [CA 1.35.0 Cluster API provider](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.35.0/cluster-autoscaler/cloudprovider/clusterapi/README.md): management/workload 접속 분리, node group min/max와 discovery.
- [CAPI 1.13.4 Machine controller](https://github.com/kubernetes-sigs/cluster-api/blob/v1.13.4/internal/controllers/machine/machine_controller.go): 삭제 hook, drain/eviction, volume detach, Node 삭제. 고정 태그 소스로 확인했다.
- [CAPO 0.14.6 OpenStackMachine controller](https://github.com/kubernetes-sigs/cluster-api-provider-openstack/blob/v0.14.6/controllers/openstackmachine_controller.go): OpenStackServer 삭제와 완료 대기 후 finalizer 해제. 따라서 객체 개수 감소만으로 Nova/port 삭제를 추정하지 않는다.
