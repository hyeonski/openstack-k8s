# 환경 준비 분리와 worker 1~3 자동 증감 검증

- 작성일: 2026-09-11
- 설계: [ADR-0016](adr/0016-separate-observation-and-enable-worker-scale-in.md)
- 과거 실환경 결과: [2026-08-24 기준선](gcp-validation-baseline.md). 당시 자동 시험은 **1→2 증설만** 통과했다.
- 1차 실환경 결과: 자동 전이·최종 시험 정리·API/CNI/DNS **통과**(2026-09-11 19:32:39 KST). 호출 셸의 종료 오류를 구분해 아래에 기록했다.
- 최종 코드 실환경 결과: 수동·자동 전체 경로와 시험 자원 제거 후 API/CNI/DNS **통과**(2026-09-11 20:56:53 KST). 호출 프로세스도 exit 0으로 종료했고 코드 해시 5개가 모두 일치했다.
- 종료 확인: 2026-09-11 21:00:20 KST, 이번에 기동한 GCP 세 호스트 모두 **TERMINATED**로 복귀했다.

## 이번 로컬 검증

- `make lint`: 셸 구문, ShellCheck, GCP-only 회귀 검사, Python 컴파일·단위 테스트 통과.
- 총 55개 테스트, 새 상태/증감/소유권 회귀 테스트 25개 포함.
- 준비 중·조회 불가·설정 drift, Nova identity/상태, Calico 전체 Node coverage, 제한 시간 종료를 검사했다.
- 자동 1→2→3→2→1→2→1 경로가 시험 Deployment만 변경하는지 mock으로 검사했다.
- CPU requests 선택 실패, 실제 Pod requests·terminating Pod, 과거 CA 이벤트 배제, PDB 차단 상태에서 제한 시간 종료를 검사했다.
- worker 삭제 후 고아 포트, 공유 SG 삭제, CP 교체를 거부하는지 검사했다.
- UID 조건부 삭제와 증거 저장 실패 시 정리 금지, 수동 증감 성공/실패 시 CA replica 복원을 검사했다.
- live 시험 대기 중 원래 CA=0/1 × 성공/실패 네 경우로 복원 회귀 검사를 확대했다. 실패 시 EXIT trap에서 지역 artifact 경로가 사라져 복원 증거 저장이 누락되는 문제를 발견해 경로 수명을 수정했다. 수정 후 55개 테스트·ShellCheck를 다시 통과했다. 셸 진입점에도 비공개 기본 권한을 적용하고 복원 파일 0600을 회귀 검사했다. 최종 코드의 실환경 수동 성공 경로도 1→2→3→2→1 전체를 재실행해 통과했다. 의도적인 실패 경로는 로컬 회귀 검사로 검증했다.
- `make gcp-iac-validate`: 통과. 샌드박스 내 provider handshake 실패 후 같은 읽기 전용 validate를 샌드박스 밖에서 실행해 성공했다. 로컬 구현 단계에서는 refresh plan을 실행하지 않았으며, 아래 live 단계에서 기존 배포 프로필로 `No changes`를 확인했다.
- `git diff --check`, 신규 Make target의 실행 경로 확인: 통과.
- mock은 실제 스케줄러·CA·CAPI·CAPO 동작, 실제 drain 및 실시간 API 접근을 검증하지 않는다.

## 이번 GCP 상태 조회

2026-09-11 이름을 지정한 GCP 읽기 전용 조회에서 다음을 확인했다. 이 최초 조회 단계에서는 기동·정지·배포를
실행하지 않았다. 세 호스트 모두 `maxRunDuration=36000`, 종료 동작 `STOP`이다.

| 호스트 | 상태 | machine type |
|---|---|---|
| osk8s-controller | TERMINATED | e2-standard-4 |
| osk8s-compute01 | TERMINATED | n2-standard-4 |
| osk8s-compute02 | TERMINATED | n2-standard-4 |

기존 `make gcp-status`의 `labels.env` 필터는 결과를 반환하지 않았다. 호스트 부재로
판정하지 않고 이름으로 재조회했다. 프로필 선택 확인 사항을
[범위 밖 기록](product/infrastructure-follow-ups.md)에 남겼으며 기본값 선택 방식은 수정하지 않았다.
이후 사용자의 기동 승인을 받아 실환경 검증에 착수했다. 실제 배포 프로필은
기존 `config/environments/local.env`의 `cloud-gcp-amd64-greenfield`였다.
기본 프로필의 채택 state로는 SSH key metadata와 provider label에 7개 차이가
표시됐지만 적용하지 않았다. 세 호스트의 공개키가 기존 greenfield 키와 일치함을
확인하고 그 프로필/state로 refresh plan을 다시 실행해 `No changes`를 확인했다.
따라서 앞선 status 빈 결과는 GCP 호스트 부재나 필터 코드 결함의 증거가 아니라
프로필 선택 불일치였다. 이번 live artifact는
`artifacts/cloud-gcp-amd64-greenfield-20260911T084859Z-40405/`에 저장한다.

## 2026-09-11 실환경 실행 기록

아래 결과는 앞선 로컬 mock 검증과 별개다. GCP 세 호스트는 08:50 UTC경 시작했고,
기존 Nova VM 두 대는 host 재기동 후 SHUTOFF를 확인하여 09:00 UTC에 UUID를 대조한
뒤 명시적으로 시작했다. 이 기준선 준비를 CA 증설 결과로 세지 않는다. OpenStack
서비스는 초기 503/starting 관측을 보존한 뒤 읽기 전용으로 기다려 정상화를 확인했다.
자동 복구·서비스 재시작이나 IaC apply는 실행하지 않았다.

| 계층 | 이번 결과 |
|---|---|
| IaC | validate 통과, 올바른 greenfield state로 실행 전·증감 검증 후 refresh plan 모두 No changes |
| GCP/host | 세 호스트 IAP/시간/컨테이너/네트워크, controller→compute SSH, 두 compute nested kernel boot 통과 |
| OpenStack | Keystone/Placement, nova-compute 2·hypervisor 2, Kolla validate-config, CirrOS/Ubuntu guest·Floating IP·CAPO 네트워크 검사 통과 |
| management/provider | kind Ready, Pod→OpenStack, CAPI 1.13.4·CAPO 0.14.6·ORC 2.4.0 Available, application credential 인증 통과 |
| 고정 노드 이미지 | v1.35.7/amd64, containerd/CRI·kernel·registry pull·실제 재부팅 후 SSH 통과. 실행 소유 guest/keypair/FIP 정리 완료 |
| workload 기준선 | CP1+worker1 Ready, Machine/OSM/Node/Nova identity, API·전체 Node CNI/DNS 통과 |
| 책임 분리 | prepare 전후 Calico spec/generation 동일(이미 의도 설정), read-only verify 후 동일; 조회 전후 workload Pod 11개 유지. 능동 probe는 별도 실행·증거 저장 후 삭제 |
| CA 설정 | 고정 v1.35.0 image digest, min/max=1/3, scale-down=true·대기 정책·RBAC 통과 |
| 수동 증감 | 1→2→3→2→1 통과. 네 번 모두 CA 1→0 중지 후 1 복원, 단계별 API/CNI/DNS 통과. 저장한 축소 전후 snapshot으로 VM/port 삭제와 CP·공유 자원 유지도 대조 통과 |
| 자동 증감·최종 정리 | 1→2→3→2→1→2→1 통과, 시험 Deployment/Pod 삭제, CP1+worker1 최종 안정화·API/CNI/DNS 통과 |


| 1차 자동 전이 | 상태·삭제 검사 수렴 시각(KST) | 소요 시간 | 결과 |
|---|---|---|---|
| 1→2 | 18:33:29 | 5분 24초 | 통과 |
| 2→3 | 18:38:54 | 4분 47초 | 통과 |
| 3→2 | 18:53:52 | 14분 14초 | 통과 |
| 2→1 | 19:08:43 | 14분 27초 | 통과 |
| 1→2 | 19:14:29 | 5분 27초 | 통과 |
| 2→1 | 19:29:30 | 14분 23초 | 통과 |

소요 시간은 replica 변경부터 안정화·식별자/삭제 검사 통과까지이며, 뒤이은
능동 probe 시간은 포함하지 않는다. 여섯 전이 뒤의 API/CNI/DNS probe와 신규 worker
IPAM 잔존 검사도 모두 통과했다. 마지막 시험 자원 정리 후 안정화·능동 검사도 19:32:39 KST에 통과했다. 호스트 정지는 별도 기록한다.
전체 UID·Nova UUID·삭제 port·CA event UID는 master artifact의
`automatic-transitions.json` 및 자동 시험의 단계별 `passed.json`에 보존했다.

기본 기준선 검사에서 API 터널이 종료된 호출의 다음 조회는 connection refused로
실패했다. 조회 함수는 터널을 자동 생성하지 않았으며, 다음 준비 호출에서 명시적으로
터널을 열고 재검사했다. 장시간 시험은 같은 접속 세션에서 transport 준비 후 수행한다.

수동 worker3 시점 Nova 배치는 compute01에 CP+worker, compute02에 worker2였다.
Hypervisor 합계는 vcpus=8, vcpus_used=8, running_vms=4, memory_mb_used=9216,
local_gb_used=80이었다. 두 flavor 모두 2 vCPU·2048 MiB·20 GB로 확인했다.
이 수치는 설정·할당 상태이며 CPU 실사용률이나 성능 여유 측정값이 아니다.
수동 3→2 중에는 Neutron port list 이후 port show 전에 대상이 삭제되어 첫
snapshot이 `unavailable`이었다. 오류를 저장하고 재조회했으며 이후 Calico
coverage/rollout은 `preparing`으로 분류했다. 이 과정에서 자동 복구나 기준 변경은 없었다.

## 최종 코드의 별도 실환경 재검증

1차 실행 뒤 수정한 코드의 수용 결과를 분리하기 위해, 검증 스크립트 5개의
SHA-256을 저장하고 수동·자동 경로를 새 프로세스에서 실행했다. 이 재검증 중
실행 코드는 수정하지 않았다. 최종 수동 1→2→3→2→1은 네 호출 모두 통과했고,
CA 원래 replica=1 복원 및 복원 증거 파일 0600도 확인했다.

| 최종 코드 자동 전이 | 상태·삭제 검사 수렴 시각(KST) | 소요 시간 | 뒤이은 API/CNI/DNS |
|---|---|---|---|
| 1→2 | 19:57:09 | 5분 21초 | 통과 |
| 2→3 | 20:03:24 | 5분 36초 | 통과 |
| 3→2 | 20:18:16 | 14분 8초 | 통과 |
| 2→1 | 20:32:56 | 14분 17초 | 통과 |
| 재증설 1→2 | 20:38:38 | 5분 24초 | 통과 |
| 마지막 2→1 | 20:53:42 | 14분 26초 | 통과 |

여섯 전이에서 실제 변경 주체는 CA였으며 시험은 Pod requests 1050m을 유지하고
replica만 변경했다. 마지막 축소에서 Nova VM
`93360442-539b-4b5b-b709-3d55c8a5de0b`와 port
`6e65b90f-3a18-4ded-b88d-254a6c628d41`의 삭제를 확인했다.

시험 Deployment/Pod 정리 후 CP1+worker1의 최종 안정화는 20:56:34 KST,
최종 API/CNI/DNS는 20:56:53 KST에 통과했다. CP Nova UUID
`1a7694df-3fca-4120-b693-fc17c82c44a2`와 Machine/Node UID는 최초 기준선부터
동일하다. 마지막 worker Nova UUID는 `ef17826e-131b-4f6d-a7f3-d24c73b56708`이다.
공유 network/subnet/router/security group과 CP endpoint FIP는 유지됐다.
최종 호출 프로세스는 exit 0이며, 1차 실행에서 발생한 셸 EOF 오류가 없었다.
`final-code-unchanged.txt`의 검증 스크립트 5개 해시도 모두 일치했다.

이번 재검증은
`artifacts/cloud-gcp-amd64-greenfield/autoscaler-cycle-20260911T104858Z-ee0c0611/`에
보존한다. master artifact의 `manual-sequence-final-code.json`,
`automatic-transitions-final-code.json`, `logs/automatic-cycle-final-code.log`는
1차 실행의 결과와 별개다.

### 검증 후 호스트 정지 결과

최종 검사와 증거 반출 뒤 20:58:01 KST에 승인된 세 호스트만 정지 요청했고,
21:00:20 KST에 아래 상태를 확인했다. image builder는 기동하지 않았다.

| 호스트 | 최초 상태 | 검증 후 상태 |
|---|---|---|
| osk8s-controller | TERMINATED | TERMINATED |
| osk8s-compute01 | TERMINATED | TERMINATED |
| osk8s-compute02 | TERMINATED | TERMINATED |

CP1+worker1 정상 판정은 **호스트 정지 직전**의 결과다. 정지 후에도 Kubernetes가
접속 가능하다는 뜻이 아니다. GCP 호스트·persistent disk·OpenStack foundation·공유
자격 증명은 삭제하지 않았다. 호스트 사양, workload flavor, quota·초과 할당 정책도
변경하지 않았다. 다음 실행은 호스트 기동 승인과 Nova VM의 실제 상태 확인이 필요하다.

master artifact의 `final-summary.json`, `gcp-before-stop.json`,
`gcp-after-stop.json`, `logs/gcp-stop.log`와 UTC 시각 파일에 종료 근거를 보존했다.
이번 필수 인프라 수용 경로의 미실행 단계는 없으며, 아래 의도적 실패·차단 사례와
고객 HTTP 연속성·성능 여유는 이 결과로 입증하지 않는다.

## 접속 준비와 명령

조회는 터널을 자동 생성하거나 kubeconfig를 수정하지 않는다. 실행 중인 환경에서
기존 연결이 없을 때만 다음 transport 명령을 먼저 실행한다. 정지된 호스트는
이 명령으로 기동하지 않으며, 기동은 별도 승인이 필요하다.

```bash
# 현재 배포와 label/키/state가 일치하는 기존 로컬 프로필
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
scripts/gcp-management-cluster.sh tunnel
scripts/gcp-workload-api-tunnel.sh ensure

# 구성 적용이 필요한 구축/업데이트 단계에서만
make workload-cluster-prepare

# 한번 관측 / 수렴 대기 (둘 다 구성과 시험 리소스를 변경하지 않음)
make workload-cluster-status WORKERS=1
make workload-cluster-verify WORKERS=1

# 명시적 능동 검사: API TCP + readyz, 모든 Node의 CNI/DNS
make workload-cluster-probe
```

`create`는 Calico 설치→prepare→verify→probe를 호출한다. 수동 scale은 verify와
probe를 호출하고 Calico patch나 OpenStack recovery를 호출하지 않는다. 자동
시험도 recovery를 호출하지 않는다. 기반이 불안정하면 먼저 원인과 필요한 별도
복구를 기록한다.

status: ready=0, preparing=10, mismatch=20, unavailable=30. verify의 수렴 제한은
기본 3,600초이며 timeout=40과 마지막 관측을 저장한다. `make`의 종료 코드는
이 상세 숫자를 그대로 보존하지 않으므로 `result.json`을 확인한다. snapshot의
각 조회 실패를 `errors`에 보존하며 조회 실패를 빈 목록으로 취급하지 않는다.

## ADR-0015에 따른 실환경 실행 순서

선행 계층 실패 시 중단하며 아직 통과하지 않은 계층은 미검증으로 표시한다.
기동 허용 후에도 호스트 사양·quota·flavor·초과 할당 정책은 변경하지 않는다.

1. `make gcp-iac-validate`, `make gcp-iac-plan`, `make gcp-iac-show-plan`: refresh plan `No changes` 확인. plan을 임의 apply하지 않는다.
2. `make gcp-status`(위 label 문제로 비어 있으면 정확한 이름으로 조회), `make gcp-host-verify`: 3대의 이름/IP, 자동 STOP 36,000초, IAP를 확인한다. controller→compute SSH와 두 compute의 `/usr/local/sbin/verify-nested-kvm` 실제 부팅 검사는 별도로 실행한다.
3. OpenStack 계층 검증: `make openstack-verify`, `make openstack-validate`. Keystone/Placement/nova-compute 2개/hypervisor 2개와 guest lifecycle 근거를 보존한다. 필요시 recovery는 별도 구성·복구 단계로 기록한다.
4. `make management-cluster-verify`, `make capi-providers-verify`, `make capi-credentials-verify`: controller 여유·kind bridge/NAT와 Pod→OpenStack 경로, 고정 provider 버전/인증. 노드 이미지가 기존 고정 이미지인지 image guest 검사로 확인한다. 이번 실행은 `make kubernetes-image-verify`의 전체 sync와 고정 keypair 사전 삭제를 피하고, 같은 guest 검사에 실행별 이름과 기존 자원 존재 시 중단 조건을 적용한 artifact 스크립트를 사용했다. stdin 전달 도중 SSH가 남은 스크립트를 소비한 첫 시도는 완료로 인정하지 않았고, 생성된 VM UUID를 확인한 후 파일로 전달해 검사를 완료했다.
5. 위 transport 준비, `make workload-cluster-prepare`(구성 변경 단계), CP1+worker1의 verify/probe. 기존 상태가 2/3대이면 먼저 해당 대수를 관측하고 **수동 기준선 준비**로 1대에 복귀한다. 이 수동 변경은 자동 시험 결과에 포함하지 않는다.
6. `make cluster-autoscaler-install`, `make cluster-autoscaler-verify`: 고정 image/digest, discovery·min/max·축소 정책, 이중 RBAC/eviction/PDB 권한 확인.
7. 수동 `WORKERS=2`, `3`, `2`, `1`을 순서대로 `make workload-cluster-scale`로 실행. 각 호출의 CA 원래 replica/복원 결과와 API/CNI/DNS 검사 기록 확인.
8. `make cluster-autoscaler-test`: CA 연속 실행 상태의 **1→2→3→2→1→2→1**. 각 단계 뒤 조회와 능동 검사, 신규 worker의 calico-ipam 잔존 검사. Pod requests는 한 번 선택 후 고정하며 실제 Pod에 반영된 값을 매 단계 확인한다.
9. 시험 성공 후 Deployment/Pod 삭제와 CP1+worker1, 동일 CP UID/providerID, 공유 Neutron 자원 유지 및 최종 API/CNI/DNS 확인. 실패 시 상태·증거를 보존하고 원인을 기록한다.

기능 수용 대상 VM은 CP1+worker1~3=2~4대다. compute 각각 4 vCPU·16 GiB에
Nova VM 각각 2 vCPU·2 GiB·20 GB를 사용한다. 세 worker가 GCP compute 세 대에
분산된다는 뜻이 아니며, 기존 compute 두 대의 실제 배치·가용량을 확인해야 한다.

이번 자동 시험은 allocatable 2000m, 기존 requests 250m에서 시험 Pod당 1050m을
선택했다. worker당 두 시험 Pod가 들어가지 않으며, 부하 Pod가 남은 worker의
총 requests는 65%였다. 첫 축소 후보는 12.5%로 기록됐고, CA의 제거 시뮬레이션과
기존 Calico PDB(disruptionsAllowed=1)를 확인했다. 실사용 CPU 감소를 측정한 값이 아니다.

## 자동 단계별 판정

| 단계 | 시험 replica | 변경 주체 | 필수 증거 |
|---|---:|---|---|
| 기준선 1 | 0 | 없음 | CP1+worker1, 시험 잔존 없음, 설정 일치 |
| 1→2 | 2 | CA | 새 Pod UID의 Insufficient cpu 및 TriggeredScaleUp, 신규 Machine/OSM/Node/Nova |
| 2→3 | 3 | CA | 이번에 추가된 Pod UID의 Pending과 CA 이벤트, 3 worker가 실제 Ready |
| 3→2 | 2 | CA | 종료 Pod가 사라짐, 삭제 Node UID의 ScaleDown, 소유 VM/port 삭제 |
| 2→1 | 1 | CA | 동일 검사, CP와 공유 네트워크 자원 유지 |
| 재증설 1→2 | 2 | CA | 첫 확장의 과거 이벤트로 대체하지 않고 신규 Pod/Node 증거 요구 |
| 기준선 복귀 2→1 | 1→정리 후 0 | CA/시험 자원만 정리 | 자동 축소, 마지막 Deployment/Pod 삭제, 최종 조회·능동 검사 |

한 단계 수렴 제한 3,600초, 목표 상태 연속 60초가 기본이다. 증설 후 10분·불필요
노드 10분이라는 정책은 단순 합산한 완료 보장이 아니다. PDB, affinity, 시스템
Pod requests, local storage, CA backoff, Nova quota·배치 부족, CAPI drain이 추가로
영향을 준다. 대기 중의 Pod/PDB/이벤트와 Machine condition을 확인한다.

`CLUSTER_AUTOSCALER_STAGE_TIMEOUT_SECONDS`와 `CLUSTER_AUTOSCALER_STABLE_SECONDS`는
환경 override로 시험 시간을 제한할 수 있다. 축소 지연 정책은 고정 manifest에
있고 설치/검증이 같은 값을 사용한다. 실패한 실환경 시험을 통과시키려고 시간·
readiness·utilization·PDB 기준을 느슨하게 변경하지 않는다.

## 증거 위치와 정리 범위

새 artifact는 `artifacts/<ENVIRONMENT_NAME>/<종류>-<UTC>-<실행ID>/`에 저장한다.
1차 자동 시험은 `artifacts/cloud-gcp-amd64-greenfield/autoscaler-cycle-20260911T092514Z-9caf3b3c/`,
최종 코드 시험은 `artifacts/cloud-gcp-amd64-greenfield/autoscaler-cycle-20260911T104858Z-ee0c0611/`에 저장했다.
기존 `current-run` 기반 guest/compute 진단은 그대로 보존하며 새 결과의
`diagnostics.log`에서 그 위치를 연결한다. 파일 0600, 실행 디렉터리 0700,
기존 credential redaction 규칙을 적용한다. 결과는 시도마다 새 디렉터리로 남긴다.

- 자동 시험: 단계별 `started.json`, 번호별 snapshot/result, CA log/status/events, PDB, `passed.json` 또는 `timeout.json`, 전체 `result.json`.
- snapshot: Cluster/KCP/MD/MS/Machine/OSM/OSC, Node/Pod/Calico와 Nova server/port/network/subnet/router/SG/FIP. quota·limits 조회 오류도 기록한다.
- identity: 이름뿐 아니라 Machine/OSM/Node UID와 providerID/Nova ID, 삭제 포트 device ID 및 시간. Nova server 이름 prefix는 잔존 후보 탐지용이며 삭제에 쓰지 않는다.
- 능동 검사: management namespace의 API probe, default namespace의 Node별 DNS probe. 각각 실행 label/UID, 생성 상태·종료 JSON·events·log를 보존한다. 성공한 probe만 UID 조건으로 삭제한다. 실패 Pod는 남긴다.
- 보존: controller/compute, CP, OpenStack persistent foundation, 공유 network/subnet/router/SG, CP endpoint FIP와 자격 증명.
- 삭제 확인: CA/CAPI/CAPO가 축소 대상으로 선택한 worker의 Machine/OSM/Node/Nova와 그 VM에 속했던 port/FIP. 스크립트가 이를 직접 삭제하지 않는다.

이전 시험이 남았으면 자동 시험은 새 부하를 만들기 전에 실패한다. 기존 결과를
확인하고 다음 명령으로 저장 후 정리한다. 새 실행 label이 있는 시험 Pod와
Deployment, 그리고 정확한 기존 `m3-cpu-scale-up`/`m3-new-worker-cni-dns` 이름에
`part-of=openstack-k8s-m3`가 붙은 자원만 대상이다. 이름만 같은 자원은 거부한다.
수동 증감은 CA 중지 후 같은 정리를 수행한다. 증거를 읽거나 저장하지 못하면
삭제하지 않는다.

```bash
make cluster-autoscaler-diagnostics
make cluster-autoscaler-test-cleanup
```

자동 시험·수동 증감·명시 정리는 **같은 운영 클라이언트에서** 파일 잠금을 공유한다.
여러 클라이언트 또는 외부 kubectl을 이용한 동시 증감/정리는 금지한다. 능동 probe도
진행 중인 시험과 따로 동시에 실행하지 않는다. 이 잠금은 분산 실행 관리 시스템이
아니다. 실패 후 `test-cleanup`이 CA나 MD를 변경하지는 않지만 requests 제거로
CA의 자연 축소가 뒤따를 수 있다.

수동 작업의 `autoscaler-original-replicas.txt`와 `autoscaler-restored.txt`로 복원을
대조한다. SIGKILL/운영 클라이언트 소실 뒤 원래 replica가 복원되지 않았다면 그
값으로 CA만 복원하는 별도 운영 작업이 필요하다. 단순히 재설치해 항상 1로
만드는 것은 원래 0으로 중지했던 상태를 복원하는 것과 다르다.

## 실환경 기동 승인 후 종료 계획

기동 대상은 `asia-northeast3-a`의 `osk8s-controller`, `osk8s-compute01`,
`osk8s-compute02` 중 정지된 호스트만이다. image builder는 기동하지 않는다.
전체 경로는 중첩 VM 부팅과 축소 대기를 포함해 수 시간이 걸릴 수 있으며, 자동
STOP까지 남은 시간 안에 계층 검증·증거 반출·종료 여유를 확보한 경우만 시작한다.

성공 시 실행 소유 시험 자원을 정리하고 worker1을 확인한 뒤 증거를 로컬에
보존한다. 이번 검증을 위해 기동한 호스트만 정지 전 상태로 돌려놓고 종료 상태를
기록한다. 기존에 실행 중이던 호스트는 정지하지 않는다. 실패 시 증거 반출 후
자동 파괴 없이 VM/Pod 상태를 남기고, 이번 기동 호스트를 정지해 비용을 제한한다.
정지는 persistent disk와 OpenStack foundation을 삭제하는 작업이 아니다.
다음 GCP 재기동 때 기존 Nova VM이 자동 시작된다고 가정하지 않는다. 이번에는
SHUTOFF가 확인되어 Machine providerID와 Nova UUID를 대조한 후 별도 시작했다.
상태 조회는 이 시작·복구 작업을 대신하지 않는다.

## 검증 실행 중 발견·보완 사항

- 수동 실패 시 EXIT trap의 지역 경로 수명이 끝나 복원 증거 파일이 누락되는 문제를 로컬 회귀 검사로 발견했다. 경로를 유지하도록 수정하고 원래 CA 0/1 × 성공/실패 및 파일 0600을 검사해 55개 테스트·정적 검사 통과를 재확인했다.
- 1차 자동 시험의 Python 실행기는 여섯 전이와 최종 정리·probe 후 `result.json: passed`를 저장했다. 다만 장시간 실행 중 셸 진입점의 기본 파일 권한을 수정하여, 호출 셸 종료 로그에 `unexpected EOF while looking for matching quote`가 남았다. 이 메시지는 삭제하지 않았다. 해당 1차 셸 호출을 오류 로그가 없는 실행으로 표현하지 않는다. 이어서 최종 코드 해시를 고정하고 수동·자동 경로 전체를 새 프로세스로 재실행해 통과했다. 최종 실행은 exit 0, EOF 오류 없음, 실행 전후 해시 일치까지 확인했다. 두 실행의 로그와 artifact는 분리해 보존한다. 실행 중 파일 수정으로 전체 재검증 시간이 추가된 운영 실수도 이 기록에 남긴다.

## 실환경에 주입하지 않은 실패·차단 사례

의도적 Calico drift, PDB 차단, affinity/local storage 차단, 자원 부족,
강제 시간 초과, 수동 작업 실패·신호 중단은 이번 실환경에 주입하지 않았다.
관련 분류·소유권·종료·복원 로직은 로컬 회귀 검사 결과와 구분한다.
실환경에서 자연 발생한 port 조회/삭제 경합은 오류를 보존하고 재조회로 수렴했다.

## 별도 후속 작업

고객 HTTP 요청의 무중단 처리·SIGTERM/drain 영향, 실제 CPU/HTTP 성능 시험,
상시 모니터링, HPA, 고객 앱/장애 시나리오, worker 자동 복구, 실행기 재시작/분산
잠금/보존 기한을 포함한 전체 수명주기 관리는 이번 범위 밖이다. 별도
[범위 기록](product/infrastructure-follow-ups.md)을 따른다.
