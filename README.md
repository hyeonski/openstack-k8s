# OpenStack → Kubernetes 노드 오토스케일링 테스트베드

이 저장소는 `Cluster API + CAPO + Cluster Autoscaler` 실험을 위한
OpenStack 기반 환경을 구축한다. OpenStack 기반 마일스톤과 Kubernetes용
ARM64 노드 이미지, management cluster와 CAPI/CAPO workload lifecycle
게이트를 구현했다. 동일한 4-vCPU compute에서 Cluster Autoscaler가 CPU request
기반 Pending Pod를 감지해 worker를 1→2로 자동 증설하는 M3까지 통과했다.

프로젝트의 기술 결정, 검토한 대안과 재검토 조건은
[`docs/adr/`](docs/adr/README.md)에 기록한다.

환경 간 이전 대상은 실행 중인 VM이 아니라 자동화 코드와 설정이다.

```text
로컬 ARM64 Lima VM
  → 중첩 KVM을 지원하는 클라우드 AMD64 VM
  → 물리 AMD64 controller/compute 호스트
```

환경별 주소, 인터페이스, CPU 아키텍처, 외부 인프라는 별도 프로필로
분리한다. OpenStack 역할 구성, Kolla 작업 흐름, 기본 리소스 생성,
검증 게이트는 공통으로 유지한다.

## 현재 상태

M0~M3 기능 마일스톤은 구현됐다. 2026-08-15 clean-room 첫 worker 1→2에서
일시적인 Pod sandbox failure와 orphan CNI가 한 번 발생했지만, 자원과 timeout을
바꾸지 않은 2→1→2 재시도는 개입 없이 통과했다. 새 worker를 명시적으로 지정한
CNI/DNS probe도 즉시 성공해 지속적인 CPU 부족은 재현되지 않았다. 이어 같은
CPU와 timeout에서 M3 자동 1→2 증설, 새 worker targeted probe, workload clock,
strict CAPI readiness와 orphan `calico-ipam` 부재를 확인했다.

| 범위 | 상태 | 의미 |
|---|---|---|
| 로컬 Lima controller/compute 호스트 | 통과 | 지정된 ARM64 VM 두 대가 공유 관리 네트워크에서 실행됨 |
| 중첩 KVM | 통과 | compute 호스트가 KVM으로 ARM64 Linux 커널을 부팅할 수 있음 |
| Kolla-Ansible OpenStack 배포 | 통과 | OpenStack 2025.2 핵심 서비스와 Horizon이 실행됨 |
| Nova 게스트 생명주기 | 통과 | CirrOS 및 Ubuntu ARM64 인스턴스가 정상 부팅됨 |
| Neutron 게스트 네트워크 | 통과 | DHCP, Floating IP, 외부에서의 접근, 인터넷 outbound가 동작함 |
| Kubernetes 없는 CAPO 네트워크 게이트 | 통과 | macOS와 Docker bridge 컨테이너에서 OpenStack API 및 TCP 6443의 가상 workload API에 접근할 수 있음 |
| Kubernetes ARM64 노드 이미지 | 통과 | Ubuntu 22.04, Kubernetes v1.35.7, containerd 2.3.2 이미지를 빌드하고 Glance 업로드·Nova 부팅·재부팅까지 검증함 |
| 로컬 management Kubernetes | 통과 | Docker Desktop 위의 단일 노드 kind v0.31.0/Kubernetes v1.35.0이 Ready이며 Pod 내부에서 OpenStack API에 접근 가능함 |
| CAPI/CAPO provider | 통과 | CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6와 ORC v2.4.0이 management cluster에서 Available임 |
| OpenStack credential 연결 | 통과 | 기존 application credential를 namespace Secret으로 연결하고 kind Pod에서 실제 token 발급에 성공함 |
| workload Kubernetes 기준선 | 통과 | CAPO가 OpenStack VM 기반 v1.35.7 control plane 1대와 worker 1대를 만들고 Calico, CoreDNS, API/CNI/DNS probe가 통과함 |
| 수동 worker 증설 | 통과 | 첫 clean-room CNI 이상을 복구한 뒤 동일 4 vCPU에서 2→1→2와 새 worker targeted CNI/DNS probe가 개입 없이 통과함 |
| 정지 후 재기동 readiness | 통과 | 양방향 관리망, Keystone, nova-compute, hypervisor가 준비된 뒤에만 `local-up`이 성공함 |
| clean-room 재구축 | 통과 | Lima VM 두 대를 삭제하고 OpenStack 재배포·게스트 검증·Docker 콜드 스타트·kind 재생성까지 통과함 |
| GCP AMD64 호스트/IaC 프로필 | 통과 | 기존 VPC·주소·VM·snapshot 정책 import 후 OpenTofu `No changes`, IAP host gate와 controller→compute 2대 SSH 통과 |
| GCP OpenStack/CAPI/Autoscaler 이전 | 통과 | AMD64 control plane 1대·worker 1대 기준선, 수동 1→2 증설과 CPU Pending Pod 기반 자동 1→2 증설이 모두 통과함 |
| 물리 서버 프로필 | 미구현 | NIC/VLAN/bridge 및 스토리지 구성을 코드화하고 검증해야 함 |
| 노드 오토스케일링 | 통과 | management cluster의 CA v1.35.0이 `Insufficient cpu` Pending Pod를 감지해 worker를 1→2로 늘리고 새 node targeted CNI/DNS와 전체 readiness를 통과함 |

최신 결과는 workload Cluster, management kind cluster와 Lima VM 두 대를 정확한
확인값으로 삭제한 뒤 최종 자동화만으로 호스트 준비, Kolla 배포, 리소스
bootstrap, 실제 게스트 검증, management/provider 설치와 workload 증설까지
성공했음을 입증한다. secret, application credential, Kubernetes QCOW2, download
cache와 기존 artifact는 삭제하지 않았다. bootstrap 중 application credential
cloud 설정의 shell scope가 keypair 명령까지 이어지지 않는 문제를 발견했고,
원인을 확인한 뒤 수정해 idempotent 재실행을 통과했다. 따라서 로컬 ARM64
프로필의 M2 기능적 재현성과 재시작 복구는 검증됐다. 클라우드 및 물리 서버
프로필의 이식성 검증은 별도 마일스톤이다.

이후 별도 6 GiB Lima builder에서 Kubernetes Image Builder v0.1.55의 정확한
commit으로 Ubuntu 22.04 ARM64 QCOW2를 만들었다. Image Builder Goss 64개
검사와 호스트 checksum 검증을 통과했고, Glance의
`ubuntu-2204-kube-v1.35.7-arm64` 이미지로 등록한 뒤 실제 Nova 게스트에서
Kubernetes 구성과 재부팅 readiness를 확인했다.

M2에서는 kind management cluster에 고정된 CAPI/CABPK/KCP v1.13.4,
CAPO v0.14.6와 ORC v2.4.0을 설치했다. CAPO가 config drive로 같은 이미지를
부트스트랩해 control plane 1대와 worker 1대를 만들었고, Calico v3.32.1과
DNS/CNI/API probe가 통과했다. 이어 `MachineDeployment`를 1대에서 2대로
늘려 세 번째 Nova VM과 Kubernetes Node가 추가되는 것을 확인했다.

M3에서는 digest로 고정한 Cluster Autoscaler v1.35.0을 management cluster에서
실행한다. management in-cluster 권한으로 CAPI/CAPO를 보고 workload 전용
ServiceAccount kubeconfig로 Pod와 Node를 관찰한다. 실행 시 worker allocatable
2,000m와 기존 request 250m를 확인한 뒤 Pod당 1,050m를 선택했다. 첫 Pod만 기존
worker에서 실행되고 두 번째 Pod가 `Unschedulable`/`Insufficient cpu`가 된 뒤
MachineDeployment가 1→2로 바뀌었다. 새 worker `osk8s-workload-md-0-ppx4r-cv577`은
Nova ACTIVE, Node/Calico Ready가 됐고 Pending Pod와 node 지정 CNI/DNS probe를
실행했다. 자세한 결과는 [`docs/m3-autoscaling-report-2026-08-15.md`](docs/m3-autoscaling-report-2026-08-15.md)에 기록한다.

GCP 이전의 첫 checkpoint에서는 `cloud-gcp-amd64` 프로필을 추가하고 기존
`openstack-k8s` 프로젝트의 custom VPC, subnet, firewall, 내부 주소 네 개,
controller/compute VM 세 대와 snapshot 정책을 OpenTofu state로 가져왔다. 실제
refresh plan은 `No changes`였고, 10시간 뒤 `STOP`하는 비용 제어 설정도 선언에
포함한다. IAP를 통한 세 호스트 readiness와 controller의 프로젝트 전용 키로 두
compute 내부 IP에 접속하는 경로도 통과했다. 자세한 범위와 다음 gate는
[`docs/gcp-migration-foundation-2026-08-20.md`](docs/gcp-migration-foundation-2026-08-20.md)에 기록한다.

## GCP 이전 checkpoint

기존 리소스를 새로 만들지 않고 먼저 import한다.

```bash
make preflight ENV=cloud-gcp-amd64
make gcp-iac-init ENV=cloud-gcp-amd64
make gcp-iac-import ENV=cloud-gcp-amd64
make gcp-iac-plan ENV=cloud-gcp-amd64
make gcp-iac-show-plan ENV=cloud-gcp-amd64
```

`gcp-iac-plan`은 기존 리소스와 선언이 일치할 때만 `No changes`여야 한다.
instance나 disk 교체가 표시되면 apply하지 않는다. local state와 saved plan은
`.state` 및 Terraform ignore 규칙으로 Git에서 제외한다.

호스트 운영과 검증은 다음 checkpoint로 분리한다.

```bash
make gcp-status ENV=cloud-gcp-amd64
make gcp-start ENV=cloud-gcp-amd64
make gcp-host-verify ENV=cloud-gcp-amd64
make inventory ENV=cloud-gcp-amd64
make gcp-deployment-key-setup ENV=cloud-gcp-amd64
make gcp-sync-inputs ENV=cloud-gcp-amd64
```

세 VM의 `max_run_duration` 36,000초와 `STOP` 동작은 비용 제어 계약이므로
제거하지 않는다. OpenStack Floating IP route는 controller external veth/NAT가
배포되고 검증되기 전까지 OpenTofu 기본값에서 비활성화한다.

GCP management Kubernetes는 Kolla controller의 Docker daemon에서 실행한다.
Kolla의 `bridge=none`, `ip-forward=false`, `iptables=false` 설정은 변경하지 않고
kind 전용 bridge와 NAT 규칙을 별도 systemd unit으로 관리한다.

```bash
make gcp-controller-management-prepare ENV=cloud-gcp-amd64
make management-cluster-create ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
make capi-providers-install ENV=cloud-gcp-amd64
make capi-providers-verify ENV=cloud-gcp-amd64
make capi-credentials-verify ENV=cloud-gcp-amd64
```

Docker의 표준 `kind` network를 미리 `172.30.0.0/24`와 `br-kind-mgmt`로 만들고
명시적인 forwarding/MASQUERADE 규칙만 추가한다. kind API는 controller 내부 IP
`10.20.0.10:16443`에 bind하며, IAP 대역에서 controller 전용 network tag로만
접근할 수 있다. 로컬 kubeconfig는 IAP tunnel의 `127.0.0.1:16443`을 사용한다.
public Kubernetes API 방화벽은 만들지 않는다.
각 provider/workload/autoscaler 명령은 자체 실행 수명 안에서 IAP tunnel을
재확립하므로 이전 `make` 프로세스의 background tunnel에 의존하지 않는다.
workload kubeconfig는 TLS 검증 대상을 OpenStack Floating IP로 유지하면서
controller IAP SSH forwarding의 `127.0.0.1:16444`를 사용한다. public workload
API 방화벽이나 로컬 macOS route는 추가하지 않는다.

GCP VM 재기동 뒤에는 다음 runtime gate가 Keystone, Placement, Nova compute와
hypervisor를 검증한다. 데이터베이스보다 먼저 시작해 WSGI application load에
실패한 Placement만 데이터베이스 준비 후 재시작하고 Nova scheduler를 갱신한다.

```bash
make gcp-openstack-recover ENV=cloud-gcp-amd64
make workload-cluster-create ENV=cloud-gcp-amd64
make workload-cluster-verify ENV=cloud-gcp-amd64 WORKERS=1
make workload-cluster-scale ENV=cloud-gcp-amd64 WORKERS=2
make workload-cluster-scale ENV=cloud-gcp-amd64 WORKERS=1
make cluster-autoscaler-install ENV=cloud-gcp-amd64
make cluster-autoscaler-verify ENV=cloud-gcp-amd64
make cluster-autoscaler-test ENV=cloud-gcp-amd64
```

Autoscaler Pod가 사용하는 workload kubeconfig에는 로컬 IAP 종단이 아니라 실제
control plane Floating IP를 기록한다. management cluster 안에서는 이 주소로
직접 접근하고, macOS의 운영·검증 명령만 IAP SSH tunnel을 사용한다.

검증용 OpenStack VM을 보존해 kind Pod에서 workload Floating IP까지 확인할
때는 다음 순서를 사용한다.

```bash
KEEP_TEST_RESOURCES=YES make openstack-verify ENV=cloud-gcp-amd64
make management-cluster-verify ENV=cloud-gcp-amd64
make openstack-verification-cleanup ENV=cloud-gcp-amd64
```

`management-cluster-destroy CONFIRM=cloud-gcp-amd64`는 kind cluster와 로컬
kubeconfig 및 전용 bridge/NAT만 삭제하고 controller와 OpenStack 리소스는
보존한다.

로컬 프로필은 기능 검증에만 적합하다.

- AAVMF mount, controller 내부 veth/NAT, macOS route, ARM64 이미지 선택은
  로컬 환경의 구현 세부 사항이다.
- 클라우드 및 물리 서버 프로필은 이를 그대로 복사하지 않고 해당 환경에
  맞는 설정으로 교체해야 한다.
- 메모리 압박과 swap의 영향을 받으므로 이 환경의 결과를 성능 또는
  프로비저닝 지연시간 결론에 사용하면 안 된다.
- ShellCheck가 설치되지 않은 경우 `make lint`는 Bash 문법 검사로
  대체한다. 배포 품질 검증 단계에서는 ShellCheck도 설치해 실행해야 한다.

## 로컬 아키텍처

```text
macOS 호스트(16 GiB, 기능 검증 전용)
├─ Docker Desktop
│  └─ osk8s-management: 단일 노드 kind management cluster
│     ├─ 프로젝트 전용 kubeconfig 사용
│     ├─ CAPI/CABPK/KCP v1.13.4
│     ├─ CAPO v0.14.6 + ORC v2.4.0
│     └─ Cluster Autoscaler v1.35.0, scale-down disabled
├─ Lima/socket_vmnet 공유 관리 네트워크
│  ├─ osk8s-controller: 4 vCPU, 8 GiB, 80 GiB, 게스트 swap 2 GiB
│  └─ osk8s-compute:    4 vCPU, 10 GiB, 80 GiB, 게스트 swap 2 GiB
│     ├─ 중첩 KVM 필수
│     └─ workload v1.35.7: control plane 2 GiB 1대 + worker 2 GiB 2대
├─ osk8s-image-builder:  4 vCPU, 6 GiB, 50 GiB, 중첩 KVM
│                       └─ controller/compute와 동시에 실행하지 않음
│
├─ controller 내부 external-network 인터페이스 쌍
│  ├─ veth-kolla-ex → OVS br-ex
│  └─ veth-kolla-gw → 172.24.4.1/24 + NAT
│
└─ 임시 macOS route
   └─ 172.24.4.0/24 → controller 관리 IP → workload API Floating IP
```

단일 Lima NIC를 관리/API/tunnel 트래픽에 함께 사용한다. 내부 veth 쌍은
향후 물리 NIC를 두 개 사용하지 않더라도 Neutron에 전용 비할당 external
interface를 제공한다. 클라우드 또는 물리 서버 프로필에서는 OpenStack
서비스 토폴로지를 바꾸지 않고 이 부분만 실제 NIC, VLAN subinterface,
또는 bridge로 교체할 수 있다.

Kolla-Ansible로 배포하는 OpenStack 2025.2 구성은 다음과 같다.

- Keystone, Glance, Nova, Placement, Neutron ML2/OVS, Horizon
- controller/network 역할을 함께 수행하는 노드 한 대와 compute 노드 한 대
- 로컬 ephemeral storage 및 Glance file storage
- Cinder, Ceph, Heat, Magnum, Octavia, telemetry 제외
- 로컬 프로필에서는 ARM64 Kolla 이미지와 KVM 사용

이 구성은 자원이 제한된 기능 검증용 환경이다. macOS에서 swap 사용이
지속되거나 메모리 압박이 발생하면 실험을 중단해야 한다. 이 프로필에서
측정한 값은 프로비저닝 지연시간 평가에 사용하지 않는다.

로컬 ARM64 프로필에는 다음 네 가지 호환성 설정이 명시적으로 포함된다.

- Kolla 2025.2 ARM64 이미지의 Debian Bookworm AAVMF가 Lima/VZ 중첩 KVM
  환경에서 현재 ARM64 EFI 게스트 로더를 실행할 때 예외를 일으키므로,
  compute 호스트의 Ubuntu 24.04 AAVMF 펌웨어를 `nova-libvirt`에
  read-only로 mount한다.
- metadata 네트워크 경로가 구성되기 전에 네트워크 설정, SSH key,
  user data를 사용할 수 있도록 검증 VM에 Nova config drive를 사용한다.
- 사용자 Docker 설정을 변경하거나 credential helper에 의존하지 않도록
  저장소의 익명 Docker 설정으로 공개 검증 이미지를 내려받는다.
- macOS sleep 뒤 Lima/VZ guest와 그 안의 CAPO workload VM clock이 정지한 채
  남을 수 있으므로 첫 APT 실행 전에 VZ RTC로 시간을 bootstrap한다. 이후
  `local-up`과 controller 동기화 경계에서 outer guest를 chrony로 복구하고,
  `resume-recover`가 nested workload VM도 호스트 대비 5초 이내인지 검사·복구한다.

위 설정은 로컬 가상화 계층을 위한 설정이며 GCP/AWS 또는 물리 서버
프로필에 그대로 복사하면 안 된다.

## 안전 및 상태 관리

- 프로젝트 secret은 `.state/<environment>/secrets` 아래에 저장하며
  디렉터리는 `0700`, 파일은 `0600` 권한을 사용하고 Git에서 제외한다.
- 배포 또는 검증이 실패하면 원인 분석을 위해 실패 상태와 테스트
  리소스를 보존한다.
- `local-down`은 임시 Floating IP route만 제거하고 지정된 프로젝트
  VM 두 대만 정지한다.
- `local-destroy`는 `CONFIRM=local-arm64` 확인값을 요구하며
  `osk8s-controller`와 `osk8s-compute`만 삭제한다.
- `kubernetes-image-builder-destroy`도 동일한 확인값을 요구하고
  `osk8s-image-builder`만 삭제한다. 빌드된 QCOW2와 checksum은 보존한다.
- `management-cluster-destroy`는 `CONFIRM=local-arm64` 확인값을 요구하며
  정확히 `osk8s-management` kind cluster와 프로젝트 전용 kubeconfig만 삭제한다.
- `workload-cluster-destroy`는 환경과 cluster 이름의 두 확인값을 요구하며
  정확히 `osk8s-workload` Cluster만 삭제한다. CAPO가 소유한 VM, network,
  router, security group과 Floating IP는 finalizer로 정리하지만 namespace와
  application credential Secret은 명시적으로 삭제하지 않는다.
- socket_vmnet, credential, artifact, UTM/Tart VM, Docker 데이터,
  다른 Lima 인스턴스는 삭제하지 않는다.

## 마일스톤 작업 흐름

### 0. 읽기 전용 사전 점검

```bash
make preflight
make lint
```

Preflight는 Apple Silicon 호스트, RAM, 여유 디스크, CIDR 중복, 필수 도구
설치 여부를 확인한다. 아무것도 설치하거나 수정하지 않는다.

### 1. 승인된 호스트 설정

```bash
CONFIRM_HOST_SETUP=YES make host-setup
make preflight
```

Homebrew를 통해 Lima를 설치하고, 고정한 버전의 socket_vmnet을
`/opt/socket_vmnet`에 설치한 뒤 Lima가 검증한 제한적 sudoers 파일을
설치한다. 로컬 준비 단계에서 호스트에 지속적으로 남는 변경은 이것뿐이다.

### 2. OpenStack 호스트 두 대 생성 및 준비

```bash
make local-create
make local-up
make host-prepare
```

`host-prepare`는 다음 작업을 수행한다.

- 각 게스트에 2 GiB swap 구성
- 격리된 테스트 게스트에서 UFW 비활성화
- controller veth/NAT 서비스 구성
- compute에서 `/dev/kvm` 필수 확인
- 배포를 허용하기 전에 KVM으로 중첩 ARM64 커널 부팅

QEMU/TCG fallback은 의도적으로 제공하지 않는다. 중첩 KVM 검증이
실패하면 로컬 hypervisor 선택을 다시 검토하거나 클라우드 프로필로
이동한다.

### 3. OpenStack 배포

```bash
make openstack-precheck
make openstack-pull
make openstack-build-overrides
make openstack-deploy
make openstack-validate
make openstack-post-deploy
```

Kolla-Ansible은 controller VM 내부의 버전을 고정한 virtual environment에서
실행한다. macOS 작업 트리가 source of truth이며 배포 전에
`/opt/openstack-k8s`로 동기화한다.

명시적인 pull 단계는 registry/CDN 문제를 구성 및 서비스 시작 문제와
분리한다. Docker가 완료된 layer를 재사용하므로 안전하게 재시도할 수 있다.

로컬 ARM64 프로필은 `nova-libvirt`용으로 범위를 좁힌 파생 이미지 하나를
빌드한다. Kolla Debian Bookworm ARM64 이미지는 권장 패키지인
`dnsmasq-base`를 포함하지 않지만 libvirt가 시작될 때 이 실행 파일이
필요하다. override 이미지는 고정된 공식 이미지를 기반으로 해당 패키지만
설치하며 배포 전에 이를 검증한다. `openstack-deploy`가 이 빌드 target에
의존하므로 deploy target을 직접 호출해도 보정 과정을 빠뜨릴 수 없다.

`validate-config`는 실행 중인 서비스 컨테이너 안에 render된 설정을
검증하므로 배포 이후에 실행한다.

### 4. OpenStack 기본 리소스 생성 및 검증

```bash
make openstack-bootstrap
make openstack-verify
```

Bootstrap은 전용 `capi-test` project와 user, 권한을 제한한 application
credential, flat external network, private network/router, flavor,
security group, checksum을 검증한 ARM64 이미지 두 개를 생성한다.

검증은 다음처럼 계층적으로 진행한다.

1. 제한된 application credential로 OpenStack token 및 tenant 리소스를
   조회한다.
2. CirrOS ARM64를 중첩 KVM으로 부팅하고 DHCP/Floating IP를 얻은 뒤,
   SSH 접속과 인터넷 연결을 확인하고 성공 시 삭제한다.
3. Ubuntu 24.04 ARM64를 순차적으로 부팅하고 TCP 6443에 dummy API를
   노출한다.
4. macOS에 Floating IP CIDR을 향한 임시 route를 설치한다.
5. macOS에서 Keystone API VIP와 Ubuntu Floating IP의 6443 포트에
   접근한다.
6. 격리된 Docker bridge 컨테이너에서 두 endpoint에 모두 접근한다.
7. 모든 probe가 성공하면 Ubuntu server와 Floating IP를 정리한다.
   실패하면 원인 분석을 위해 보존한다.

마지막 검사는 Kubernetes 없이 수행하는 엄격한 CAPO 네트워크 게이트다.
미래의 management cluster에 필요한 두 경로, 즉 OpenStack API 접근과
Floating IP를 통한 workload cluster API 접근을 증명한다. CAPI, CAPO,
CNI 또는 Kubernetes bootstrap 자체가 동작한다는 의미는 아니다.

성공한 Ubuntu probe를 임시로 보존하려면 다음과 같이 실행한다.

```bash
KEEP_TEST_RESOURCES=YES make openstack-verify
```

### 5. Kubernetes ARM64 노드 이미지 빌드 및 검증

로컬 16 GiB 호스트에서는 OpenStack VM 두 대와 6 GiB image builder를
동시에 실행하지 않는다. 먼저 OpenStack을 정지하고 격리된 builder에서
이미지를 만든다.

```bash
make local-down
make kubernetes-image-builder-create
make kubernetes-image-build
make kubernetes-image-builder-destroy CONFIRM=local-arm64
```

빌드 결과는
`.state/local-arm64/images/ubuntu-2204-kube-v1.35.7-arm64.qcow2`에 저장된다.
builder를 삭제해도 결과는 남으며 같은 고정 입력으로 다시 만들 수 있다.

현재 이미지 입력은 다음과 같다.

- Ubuntu 22.04 ARM64, UEFI, QCOW2
- Kubernetes v1.35.7, containerd 2.3.2, pause 3.10.2
- Kubernetes Image Builder v0.1.55,
  commit `7ffb9b7f1f26cd66891874463cc9411e3633325f`

OpenStack을 다시 시작한 뒤 기존 빌드 결과를 업로드하고 검증한다.

```bash
make local-up
make kubernetes-image-upload
make kubernetes-image-verify
```

두 마지막 명령은 `make kubernetes-image`로 함께 실행할 수도 있다. 업로드는
로컬 SHA-256을 먼저 확인하고 Glance에 ARM64/UEFI, OS, Kubernetes,
Image Builder 버전과 checksum 속성을 기록한다. 검증은 전용 control-plane
flavor로 Nova VM을 만들고 SSH, cloud-init, containerd CRI,
`kubeadm`/`kubelet`/`kubectl`, 커널 모듈과 sysctl, swap 비활성화, pause image
pull을 확인한다. 그 뒤 VM을 재부팅해 같은 readiness를 다시 확인하고 성공한
테스트 리소스만 정리한다.

GCP AMD64 프로필은 OpenStack 호스트를 정지하지 않고 전용 일회성 빌더를
추가한다. 생성·삭제 plan은 각각 해당 빌더 한 대만 대상으로 하는지 검사하며,
빌더에도 기존 호스트와 같은 36,000초 자동 STOP을 적용한다.

```bash
make kubernetes-image-builder-create ENV=cloud-gcp-amd64
make kubernetes-image-build ENV=cloud-gcp-amd64
make kubernetes-image-upload ENV=cloud-gcp-amd64
make kubernetes-image-verify ENV=cloud-gcp-amd64
make kubernetes-image-builder-destroy \
  ENV=cloud-gcp-amd64 CONFIRM=cloud-gcp-amd64
make gcp-iac-plan ENV=cloud-gcp-amd64
```

GCP 산출물은 Ubuntu 22.04 AMD64/BIOS QCOW2이며 Kubernetes v1.35.7,
containerd 2.3.2와 같은 고정 입력을 사용한다. 빌더를 삭제해도 QCOW2,
SHA-256과 빌드 메타데이터는 `.state/cloud-gcp-amd64/images`에 남는다.

### 6. 로컬 management cluster

Docker Desktop daemon을 시작한 뒤 고정된 kind 바이너리와 node image로
단일 노드 management cluster를 만든다.

```bash
make management-cluster-create
make management-cluster-verify
```

kind v0.31.0 바이너리는 공식 SHA-256을 확인한 뒤
`.state/local-arm64/bin/kind`에 저장한다. Kubernetes v1.35.0 node image도
digest로 고정한다. kubeconfig는 사용자 전역 설정을 변경하지 않고
`.state/local-arm64/kubeconfigs/management.yaml`에만 저장한다.

검증은 node와 kube-system Pod의 `Ready`, ARM64 아키텍처, Kubernetes 버전,
kind Pod 내부에서 OpenStack Keystone VIP로 향하는 HTTP 경로를 확인한다.

### 7. CAPI/CAPO provider와 workload cluster

repository 전용 `clusterctl` 설정과 management kubeconfig를 사용해 provider를
설치하고 기존 application credential를 검증한다.

```bash
make capi-providers-install
make capi-providers-verify
make capi-credentials-verify
```

고정한 M2 조합은 다음과 같다.

- CAPI core, kubeadm bootstrap/control-plane provider, `clusterctl`: v1.13.4
- CAPO: v0.14.6
- OpenStack Resource Controller: v2.4.0
- workload Kubernetes: v1.35.7
- Calico: v3.32.1

`clusterctl`과 ORC/Calico manifest는 SHA-256까지 확인한다. credential는
`.state/local-arm64/secrets/capi-clouds.yaml`에서 읽어
`osk8s-workload/osk8s-workload-cloud-config` Secret으로 전달하며 값은 출력하거나
artifact에 복사하지 않는다. 별도 인증 Pod가 OpenStack token 발급에 성공해야
다음 단계로 진행한다.

workload cluster를 만들고 worker 한 대 기준선을 검증한다.

```bash
make workload-cluster-create
make workload-cluster-verify WORKERS=1
```

CAPO가 `10.6.0.0/24` network/subnet/router와 security group을 관리하고 단일
control plane에 Floating IP endpoint를 연결한다. Pod/Service CIDR은 각각
`192.168.0.0/16`, `10.96.0.0/12`다. Calico IP-in-IP/BGP에 필요한 protocol 4와
TCP 179를 control-plane/worker managed security group 사이에 허용한다.
실패 진단용 TCP 22는 workload CIDR 내부에서만 허용하며 Nova에는 controller의
프로젝트 전용 SSH 공개키만 등록한다. private key는 controller 밖으로 복사하지
않는다.

control plane과 worker 모두 `configDrive: true`를 사용한다. providerID는
cloud-init이 `openstack:///INSTANCE_UUID`로 직접 설정하므로 M2에서는 OCCM과
`cloud-provider=external`을 사용하지 않는다. 따라서 OpenStack LoadBalancer,
volume과 cloud route integration은 이 단계의 검증 범위가 아니다.

첫 worker가 Ready인 상태에서 정확히 한 번 수동 증설하고 최종 상태를 확인한다.

```bash
make workload-cluster-scale
make workload-cluster-verify WORKERS=2
```

검증은 CAPI Machine/MachineDeployment 수, Nova server 수, Node 수를 서로
대조한다. 모든 Node의 Ready, v1.35.7, ARM64와 OpenStack providerID, Calico
DaemonSet/controller, management cluster에서 workload TCP 6443 접근, workload
Pod의 `kubernetes.default.svc.cluster.local` 조회가 모두 성공해야 한다.

2026-08-09 실행에서는 worker Nova VM과 OpenStackMachine이 ACTIVE/Ready였지만
Kubernetes Node로 등록되지 않아 Machine Available 대기가 30분 뒤 실패했다.
그 실행에는 macOS sleep이나 OpenStack/관리망 장애가 없었고 compute 메모리
압박은 관측됐지만 worker 내부 bootstrap 로그가 없어 원인을 확정하지 못했다.

2026-08-11 clean-room 재검증은 compute를 10 GiB, worker를 2 GiB로 조정한 뒤
CP1+worker1과 CP1+worker2를 모두 통과했다. 수동 scale 명령부터 최종 CNI/DNS/API
검증까지 약 2분이 걸렸다. 최종 3-node 상태에서 compute는 9.7 GiB 중 7.2 GiB를
사용하고 2.5 GiB가 available이었으며 swap 사용 0 B, memory pressure 0,
kernel OOM 기록 없음이었다. CPU pressure는 남아 있으므로 이 값은 성능 자료가
아니며, 두 메모리 변경 중 어느 하나를 과거 실패의 단일 원인으로 단정하지 않는다.

timeout 또는 수동 조사 시 다음 명령으로 같은 진단을 수집할 수 있다.

```bash
make workload-cluster-diagnostics
```

worker Available, Node 수/Ready와 Calico timeout에서는 이 수집이 자동 실행된다.
CAPI 객체·event/controller log, Nova server/console, compute memory·pressure·OOM과
controller qrouter를 경유한 각 VM의 cloud-init, kubeadm, kubelet, containerd
로그를 한 디렉터리에 저장한다. 2026-08-11 성공 상태에서도 세 VM의 bootstrap
수집과 cloud-init 완료를 확인했다.

### 8. Cluster Autoscaler 자동 scale-up

macOS sleep 뒤에는 먼저 복구하고 별도 터미널의 `caffeinate -dimsu`를 전체
실험 동안 유지한다. CP1+worker2 기준선을 확인한 뒤 worker 한 대를 정상
정리하고 Autoscaler를 설치한다.

```bash
make resume-recover
make workload-cluster-verify WORKERS=2
make workload-cluster-scale WORKERS=1
make cluster-autoscaler-install
make cluster-autoscaler-verify
make cluster-autoscaler-test
```

Autoscaler image는 v1.35.0 tag와 multi-architecture manifest digest를 함께
고정한다. management API에는 in-cluster ServiceAccount, workload API에는 별도
ServiceAccount kubeconfig Secret을 사용한다. `MachineDeployment`의 min/max는
각각 1/2이며 `--scale-down-enabled=false`이므로 M3는 자동 증설만 수행한다.
HPA와 scale-to-zero는 포함하지 않는다.

`cluster-autoscaler-test`는 현재 worker allocatable과 이미 배치된 Pod request를
먼저 계산한다. 선택한 CPU request 하나는 기존 worker에 들어가지만 두 개는
동시에 들어가지 않아야 한다. MachineDeployment가 아직 1일 때 Pending Pod의
`PodScheduled=False`, `reason=Unschedulable`, message의 `Insufficient cpu`를
artifact로 고정한 뒤에만 1→2 증설을 인정한다. control plane의 기본 NoSchedule
taint는 scheduler message에 함께 나타날 수 있지만 image/PVC/affinity 오류는
증설 근거로 인정하지 않는다.

성공 후에도 CPU test Deployment와 완료된 targeted probe를 증거로 보존한다.
실패도 같은 원칙으로 상태를 삭제하지 않는다. 재실험 전에는 기존 리소스를
직접 확인하고 명시적으로 정리해야 한다. M3 진단은 다음 target으로 수집한다.

```bash
make cluster-autoscaler-diagnostics
```

Autoscaler log/event와 status ConfigMap, Pending Pod, CAPI/CAPO, Nova, Calico,
guest bootstrap/kubelet/containerd, `RunPodSandbox`/CNI retry, `calico-ipam` process,
Kubernetes API service path와 worker/compute pressure가 기존 redaction 정책으로
보존된다. credential와 kubeconfig 내용은 artifact에 기록하지 않는다.

## 생명주기 명령

```bash
make status
make local-health
make local-down
make local-up
make resume-recover
make workload-clock-check
make management-cluster-verify
make capi-providers-verify
make cluster-autoscaler-verify
make workload-cluster-verify WORKERS=2
make workload-cluster-destroy CONFIRM=local-arm64 CONFIRM_CLUSTER=osk8s-workload
make management-cluster-destroy CONFIRM=local-arm64
make local-destroy CONFIRM=local-arm64
```

`local-down`은 일상적인 정지 작업이며 복구 가능하다. `local-destroy`는
외부 Lima VM 두 대를 제거하므로 그 안의 OpenStack 배포와 모든 Nova VM도
함께 제거한다. 저장소 상태, secret, 실행 artifact는 보존한다.

`workload-cluster-destroy`는 destructive 명령이며 두 확인값이 모두 일치해야
한다. workload cluster만 지울 때 사용하며 management provider와 credential는
보존한다. provider 제거 자동화는 의도적으로 제공하지 않는다.

`local-up`은 두 guest clock을 먼저 복구한 뒤 양방향 관리망 통신을 확인하며,
OpenStack이 이미 배포된 환경에서는 Keystone API, `nova-compute`, hypervisor가
준비될 때까지 대기한다. 따라서 Lima VM이나 컨테이너가 단순히 실행 중이라는
이유만으로 성공을 보고하지 않는다. `make local-health`는 시간을 변경하지 않고
clock skew를 포함한 동일 readiness gate를 다시 실행한다.

로컬 clean-room 검증 한 사이클 동안에는 macOS sleep을 허용하지 않는다. 별도
터미널에서 `caffeinate -dimsu`를 실행한 상태로 검증하고, 끝나면 `Ctrl-C`로
종료한다. 예상하지 못한 sleep 뒤에는 다음 명령 하나로 stopped Lima guest 기동,
outer guest clock/OpenStack readiness, macOS Floating IP route, nested workload
VM clock과 CAPI control-plane readiness를 순서대로 복구한다.

```bash
make resume-recover
```

복구는 호스트보다 뒤처진 system clock만 chrony 또는 정상 RTC를 기준으로 앞으로
맞춘다. 호스트보다 앞선 clock은 인증서 유효성에 영향을 줄 수 있으므로 자동으로
뒤로 돌리지 않고 실패한다. 시간을 변경하지 않는 독립 게이트가 필요하면
`make workload-clock-check`를 사용한다. workload cluster가 아직 없는 단계에서는
`make local-up`만 사용한다.

## 검증 자료

각 실행은 `artifacts/` 아래에 timestamp가 포함된 디렉터리를 생성한다.
Kolla 로그, preflight 출력, 게스트 console 출력, CAPO network gate 결과와
M2의 CAPI/OpenStack/Node/Pod 상태를 그곳에 저장한다. secret과 kubeconfig는
artifact에 복사하지 않는다. Kolla 출력과 workload 진단은 bootstrap token,
certificate key, application credential 및 알려진 basic-auth 형태를 저장 전에
마스킹하며 진단 완료 시 모든 text artifact에 같은 redaction을 다시 적용한다.

## 다음 마일스톤

현재 다음 순서로 진행한다.

1. Glance용 Kubernetes ARM64 이미지 빌드·업로드·Nova 검증 — **완료**
2. 별도의 로컬 management Kubernetes cluster 생성 — **완료**
3. CAPI/CABPK/KCP와 CAPO/ORC 설치 — **완료**
4. CAPO를 통해 workload control plane과 worker 한 대 생성 — **완료**
5. `MachineDeployment`를 한 대에서 두 대로 수동 증설 — **완료**
6. Cluster Autoscaler를 설치하고 Pending Pod 기반 scale-up 검증 — **완료**
7. GCP AMD64 프로필에서 같은 OpenStack/CAPI/Autoscaler 경로 검증 — **완료**
8. 물리 AMD64 프로필의 NIC/VLAN/storage 입력 구현 — **다음 단계**
