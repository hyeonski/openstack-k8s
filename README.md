# GCP OpenStack Kubernetes Autoscaling Testbed

이 저장소는 GCP의 중첩 가상화 VM 위에 OpenStack 2025.2를 배포하고,
`Cluster API + CAPO + Cluster Autoscaler`로 Kubernetes worker 자동 증감을
검증하는 GCP 전용 테스트베드다. 실행 환경은 `cloud-gcp-amd64` 하나이며 모든
`make` 명령은 이 구성을 자동으로 사용한다.

기술 결정은 [`docs/adr/`](docs/adr/README.md), 실제 검증 기준선은
[`docs/gcp-validation-baseline.md`](docs/gcp-validation-baseline.md)에 기록한다.

제품 실험을 위한 기반 작업의 우선순위와 진행 상태는
[`docs/product/infrastructure-priorities.md`](docs/product/infrastructure-priorities.md)에서 관리한다.
worker 수동·자동 제어 모드와 중단 후 복원 절차는
[`docs/worker-control.md`](docs/worker-control.md)에 정리했다.
실행 취소·재개·정리 및 시간 상한은 [`docs/run-lifecycle.md`](docs/run-lifecycle.md)를 따른다.
1순위 기반 작업의 수정과 종합 수용 시험은
[`docs/foundation-priority1-final-validation-2026-09-24.md`](docs/foundation-priority1-final-validation-2026-09-24.md)에 기록한다.

## 아키텍처

```text
GCP project: openstack-k8s / asia-northeast3-a
│
├─ custom VPC osk8s-mgmt (10.20.0.0/24)
│  ├─ osk8s-controller  10.20.0.10
│  │  ├─ Kolla controller/network services
│  │  ├─ HAProxy alias VIP 10.20.0.250
│  │  ├─ kind management cluster
│  │  └─ IAP API endpoints 16443/16444
│  ├─ osk8s-compute01  10.20.0.21, nested KVM
│  └─ osk8s-compute02  10.20.0.22, nested KVM
│
├─ GCP route 172.24.4.0/24 → osk8s-controller
│  └─ Neutron public network and workload API Floating IP
│
└─ optional osk8s-image-builder
   └─ pinned AMD64 Kubernetes QCOW2 build, then deletion
```

공개 Kubernetes API 방화벽은 만들지 않는다. 운영 클라이언트는 IAP SSH
forwarding을 통해 management API `127.0.0.1:16443`과 workload API
`127.0.0.1:16444`에 접근한다. management cluster 내부의 Autoscaler는 workload
control-plane Floating IP를 직접 사용한다.

## 고정 기준선

| 구성 | 버전/계약 |
|---|---|
| GCP zone | `asia-northeast3-a` |
| OpenStack | Kolla-Ansible 2025.2 |
| 호스트 | Ubuntu 24.04, x86_64, compute 2대 |
| Kubernetes 이미지 | Ubuntu 22.04, Kubernetes v1.35.7, AMD64/BIOS |
| management cluster | kind v0.31.0, Kubernetes v1.35.0 |
| CAPI/CABPK/KCP | v1.13.4 |
| CAPO | v0.14.6 |
| ORC | v2.4.0 |
| Calico | v3.32.1 |
| Cluster Autoscaler | v1.35.0, digest 고정, worker `1:3`, 자동 축소 활성화 |
| 비용 제어 | GCE 인스턴스 36,000초 후 `STOP` |

OpenStack은 Keystone, Glance, Placement, Nova, Neutron ML2/OVS와 Horizon만
활성화한다. Cinder, Ceph, Heat, Magnum, Octavia와 telemetry는 범위 밖이다.

## 필수 도구와 상태

운영 클라이언트에는 다음 도구가 필요하다.

- `gcloud`와 활성 GCP 계정
- OpenTofu 또는 Terraform
- `kubectl`, `curl`, `rsync`, `tar`, `ssh-keygen`
- 개발 검증용 Python 3, ShellCheck, ripgrep

비밀과 생성 상태는 `.state/cloud-gcp-amd64`에 저장한다. secret 디렉터리는
`0700`, 파일은 `0600`이어야 하며 Git에서 제외된다. Terraform state와 saved
plan도 Git에 커밋하지 않는다.

```bash
make preflight
make secrets-check
make lint
```

## GCP 인프라 계약

### 빈 프로젝트에서 시작

Google 계정 인증과 Billing이 연결된 빈 project 하나를 준비한 뒤 환경 override를
지정한다. project 생성과 Billing 연결은 조직마다 권한과 정책이 달라 자동화의
수동 경계로 둔다.

```bash
cp config/environments/local.env.example /tmp/openstack-k8s.env
# /tmp/openstack-k8s.env의 project와 사용자 값을 수정
export ENV_OVERRIDE_FILE=/tmp/openstack-k8s.env

make bootstrap-preflight
make gcp-bootstrap CONFIRM=cloud-gcp-amd64-greenfield
make gcp-iac-init
make gcp-iac-validate
make gcp-foundation-plan
make gcp-foundation-show-plan
make gcp-foundation-apply CONFIRM=cloud-gcp-amd64-greenfield
```

foundation plan validator는 지속 GCP foundation 리소스의 create만 허용하고 update,
replace, delete와 image builder/Floating IP route 변경은 거부한다. 새 환경은
`.state/<environment>/tofu/terraform.tfstate`를 사용하며 기존 채택 환경의 state와
분리된다.

호스트 외부 네트워크와 OpenStack bootstrap을 통과한 뒤에만 route를 적용한다.

```bash
make gcp-floating-ip-route-plan
make gcp-floating-ip-route-show-plan
make gcp-floating-ip-route-apply CONFIRM=cloud-gcp-amd64-greenfield
```

전체 greenfield 경로는 동일한 확인값을 요구한다.

```bash
make lab-up CONFIRM=cloud-gcp-amd64-greenfield
```

`lab-up`은 성공한 선언형 단계를 안전하게 재실행하며, 비용이 큰 Kubernetes QCOW2는
checksum이 일치하는 기존 산출물을 재사용한다. 실패 시 자동 삭제하지 않고 상태와
로그를 보존한다.

### 기존 리소스 채택

기존 리소스를 처음 state에 채택할 때만 import를 사용한다.

```bash
make gcp-iac-init
make gcp-iac-import
make gcp-iac-plan
make gcp-iac-show-plan
```

평상시에는 `gcp-iac-plan`이 `No changes`여야 한다. instance 또는 disk 교체,
예상하지 않은 삭제가 표시되면 apply하지 않는다. network, subnet, 내부 주소와
OpenStack 호스트에는 `prevent_destroy`가 적용된다.

Ansible inventory의 관리 IP는 환경 파일이나 별도 `gcloud` 조회가 아니라
OpenTofu의 `host_internal_ips` output에서 생성한다.

## 호스트 운영과 OpenStack

```bash
make gcp-status
make gcp-start
make gcp-host-verify
make inventory
make gcp-deployment-key-setup
make gcp-sync-inputs

make host-prepare
make openstack-precheck
make openstack-pull
make openstack-deploy
make openstack-validate
make openstack-post-deploy
make openstack-bootstrap
make openstack-verify
```

`gcp-host-verify`는 세 호스트의 OS, 시간 동기화, Docker, forwarding과
compute의 `/dev/kvm`과 nested KVM 활성 상태를 확인한다. ADR-0015의
controller→compute SSH와 실제 nested kernel boot는 별도로 수행해야 한다.
이번 실환경 검증에서는 controller의 기존 배포 키로 두 compute에 접속하고,
각 compute의 `/usr/local/sbin/verify-nested-kvm`을 실행해 통과했다. VM 재기동 뒤에는 Keystone, Placement, nova-compute와
hypervisor가 준비될 때까지 `gcp-openstack-recover`가 대기한다.

```bash
make gcp-openstack-recover
```

## Kubernetes 노드 이미지

이미지 빌더는 OpenTofu plan validator가 정확히 빌더 한 대만 추가 또는 삭제하는지
확인한 뒤 적용한다.

```bash
make kubernetes-image-builder-create
make kubernetes-image-build
make kubernetes-image-upload
make kubernetes-image-verify
make kubernetes-image-builder-destroy CONFIRM=cloud-gcp-amd64
```

빌더 삭제 후에도 `.state/cloud-gcp-amd64/images`의 QCOW2, checksum과 build
metadata는 보존된다. Glance 이미지는 `hw_architecture=x86_64`,
`hw_firmware_type=bios`와 checksum 속성이 일치해야 한다.

## Management cluster와 providers

kind는 controller의 Kolla Docker daemon에서 실행된다. 전용 `kind` bridge와
forwarding/MASQUERADE 규칙은 systemd unit이 관리하며 Kolla Docker daemon의
`bridge=none`, `iptables=false` 설정은 변경하지 않는다.

```bash
make gcp-controller-management-prepare
make management-cluster-create
make management-cluster-verify
make capi-providers-install
make capi-providers-verify
make capi-credentials-verify
```

검증은 management node와 system Pod readiness, Kubernetes/architecture, Pod에서
Keystone API 접근, CAPI/CAPO/ORC deployment availability와 application credential
인증을 포함한다.

## Workload cluster와 Autoscaler

```bash
make workload-cluster-create           # 설치 → 구성 준비 → 조회 → 능동 검사
make workload-cluster-prepare          # 기존 환경의 Calico 의도 설정 적용
make workload-cluster-status WORKERS=1 # 한번 조회: 관리 구성/시험 자원 변경 없음
make workload-cluster-verify WORKERS=1 # 동일한 조회로 제한 시간 내 수렴 대기
make workload-cluster-probe            # 실행 소유 Pod로 API/CNI/DNS 능동 검사

make cluster-autoscaler-install
make cluster-autoscaler-verify
make workload-cluster-scale WORKERS=2  # 수동 증감 범위: 1~3
make workload-cluster-scale WORKERS=3
make workload-cluster-scale WORKERS=2
make workload-cluster-scale WORKERS=1
make cluster-autoscaler-test           # 자동 1→2→3→2→1→2→1
```

GCP controller 1대·compute 2대와 workload control plane Nova VM 1대는 고정이다.
worker Nova VM만 최소 1~최대 3대로 증감하므로 workload VM 총합은 2~4대다.
compute별 4 vCPU·16 GiB, CP/worker별 2 vCPU·2 GiB·20 GB를 유지한다.
worker 3대는 기능 검증용 상한이며 성능 여유가 검증된 값은 아니다.

조회는 기존 kubeconfig/터널을 사용하고 자동 준비·복구를 수행하지 않는다.
준비 중, 설정 불일치, 조회 불가, 시간 초과를 구분해 로컬 결과를 남긴다.
능동 검사는 management→workload API 및 각 Node의 CNI/DNS를 확인하고,
성공한 임시 Pod만 증거 저장 후 UID 조건으로 삭제한다. 실패 자원은 보존한다.

자동 시험은 CPU requests를 한 번 선택해 고정하고 replica를 2,3,2,1,2,1로
변경한다. CA 판단·실제 Pod 배치·worker 삭제 및 공유 자원 유지, 다음 증설까지
검사하며 MachineDeployment를 수동 scale해 성공 처리하지 않는다.
CA는 증설 후 10분, 불필요 노드 10분의 축소 정책을 사용한다. 실제 CPU 사용량
감소나 고객 HTTP 성능 시험과는 다르다. **고객 HTTP 요청의 무중단 처리는
검증하지 않는다.**

실환경에서는 [계층별 실행 절차와 검증 상태](docs/worker-autoscaling-validation.md)를
따른다. 2026-09-11 최종 코드로 수동 1→2→3→2→1과 자동
1→2→3→2→1→2→1, 삭제 자원·공유 자원 대조 및 최종 API/CNI/DNS를 통과했다.
로컬 55개 테스트·정적 검사도 통과했다. 과거 2026-08-24의 자동 1→2 결과와
이번 결과 및 실환경에 주입하지 않은 실패 사례는 검증 문서에서 구분한다.
검증 후 기동했던 GCP 세 호스트는 모두 TERMINATED로 복귀했다.
정지된 GCP 인스턴스는 실환경 검증 승인을 받은 뒤 기동한다.

```bash
make workload-cluster-diagnostics
make cluster-autoscaler-diagnostics
# 이전 실행 증거 확인 후 소유 표시가 있는 시험 자원만 저장·정리
make cluster-autoscaler-test-cleanup
```

이전 시험 자원이 남으면 자동 시험은 중단한다. 수동 증감은 CA를 중지하고
증거 저장·시험 자원 정리 후 수행하며 원래 CA replica 수를 복원한다.
동일 클라이언트의 증감·정리·모드 전환과 클러스터 생성·삭제·probe는 파일 잠금으로
보호한다. 다른 클라이언트나 운영자의 동시 변경은 금지한다.

## 제한적 삭제

삭제 명령은 정확한 확인값을 요구하며 범위 밖 리소스를 삭제하지 않는다.

```bash
make management-cluster-destroy CONFIRM=cloud-gcp-amd64
make workload-cluster-destroy \
  CONFIRM=cloud-gcp-amd64 \
  CONFIRM_CLUSTER=osk8s-workload
make kubernetes-image-builder-destroy CONFIRM=cloud-gcp-amd64
```

- management 삭제는 controller의 kind, 전용 bridge/NAT와 클라이언트 kubeconfig만
  대상으로 한다.
- workload 삭제는 지정한 CAPI Cluster와 CAPO 소유 리소스만 대상으로 한다.
- image-builder 삭제는 일회성 GCE builder만 대상으로 한다.
- controller, compute, OpenStack persistent state와 project secret은 보존한다.

## 개발 검증

```bash
make lint
```

lint는 모든 셸 스크립트의 구문과 ShellCheck, Python 단위 테스트를 실행하고 제거된
VM 자동화가 다시 유입되지 않았는지 검사한다.
