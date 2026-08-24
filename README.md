# GCP OpenStack Kubernetes Autoscaling Testbed

이 저장소는 GCP의 중첩 가상화 VM 위에 OpenStack 2025.2를 배포하고,
`Cluster API + CAPO + Cluster Autoscaler`로 Kubernetes worker 자동 증설을
검증하는 GCP 전용 테스트베드다. 실행 환경은 `cloud-gcp-amd64` 하나이며 모든
`make` 명령은 이 구성을 자동으로 사용한다.

기술 결정은 [`docs/adr/`](docs/adr/README.md), 실제 검증 기준선은
[`docs/gcp-validation-baseline.md`](docs/gcp-validation-baseline.md)에 기록한다.

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
| Cluster Autoscaler | v1.35.0, digest 고정, worker `1:2` |
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
controller→compute SSH를 확인하고, compute에서는 `/dev/kvm`과 실제 nested KVM
kernel boot를 검증한다. VM 재기동 뒤에는 Keystone, Placement, nova-compute와
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
make workload-cluster-create
make workload-cluster-verify WORKERS=1
make workload-cluster-scale WORKERS=2
make workload-cluster-scale WORKERS=1

make cluster-autoscaler-install
make cluster-autoscaler-verify
make cluster-autoscaler-test
```

workload 기준선은 control plane 1대와 worker 1대다. 수동 증설은
`MachineDeployment`를 1→2로 변경하고 새 worker의 Nova ACTIVE, Node/Calico Ready,
CNI/DNS probe를 검증한다. Autoscaler 검증은 CPU request로 Pod 하나를
`Insufficient cpu` Pending 상태로 만들고 worker 1→2, 새 worker targeted probe와
고아 `calico-ipam` 부재를 확인한다.

실패 시 자동 정리하지 않고 진단 상태를 보존한다.

```bash
make workload-cluster-diagnostics
make cluster-autoscaler-diagnostics
```

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
