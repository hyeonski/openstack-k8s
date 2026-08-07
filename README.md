# OpenStack → Kubernetes 노드 오토스케일링 테스트베드

이 저장소는 `Cluster API + CAPO + Cluster Autoscaler` 실험을 위한
OpenStack 기반 환경을 구축한다. OpenStack 기반 마일스톤과 Kubernetes용
ARM64 노드 이미지 게이트는 완료됐으며, 다음 단계는 별도의 로컬
management Kubernetes cluster에 CAPI/CAPO provider를 설치하는 것이다.

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

2026-08-06에 실행한 최신 로컬 검증을 기준으로 첫 번째 기능 마일스톤은
통과했다.

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
| 정지 후 재기동 readiness | 통과 | 양방향 관리망, Keystone, nova-compute, hypervisor가 준비된 뒤에만 `local-up`이 성공함 |
| clean-room 재구축 | 통과 | Lima VM 두 대를 삭제하고 OpenStack 재배포·게스트 검증·Docker 콜드 스타트·kind 재생성까지 통과함 |
| 클라우드 VM 프로필 | 미구현 | GCP/AWS의 중첩 가상화 및 네트워크 차이를 코드화하고 검증해야 함 |
| 물리 서버 프로필 | 미구현 | NIC/VLAN/bridge 및 스토리지 구성을 코드화하고 검증해야 함 |
| CAPI/CAPO와 workload Kubernetes | 미착수 | management cluster와 노드 이미지는 준비됐지만 provider controller 및 workload cluster는 아직 없음 |
| 노드 오토스케일링 | 미착수 | `MachineDeployment` 증설과 Cluster Autoscaler가 다음 마일스톤임 |

최신 결과는 기존 Lima VM 두 대를 삭제한 뒤 최종 자동화만으로 호스트 준비,
Kolla 배포, 리소스 bootstrap, 실제 게스트 검증, 완전 정지 후 재기동까지
성공했음을 입증한다. clean-room 중 CAPO 테스트 비밀번호가 Ansible 자식 환경으로
export되지 않아 인증이 실패하는 문제를 발견해 수정했으며, bootstrap 재실행과
application credential 검증도 통과했다. 따라서 로컬 ARM64 프로필의 기능적
재현성과 재시작 복구는 검증됐다. 클라우드 및 물리 서버 프로필의 이식성 검증은
별도 마일스톤이다.

이후 별도 6 GiB Lima builder에서 Kubernetes Image Builder v0.1.55의 정확한
commit으로 Ubuntu 22.04 ARM64 QCOW2를 만들었다. Image Builder Goss 64개
검사와 호스트 checksum 검증을 통과했고, Glance의
`ubuntu-2204-kube-v1.35.7-arm64` 이미지로 등록한 뒤 실제 Nova 게스트에서
Kubernetes 구성과 재부팅 readiness를 확인했다. management 또는 workload
Kubernetes cluster를 생성했다는 의미는 아니다.

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
│                       └─ 프로젝트 전용 kubeconfig 사용
├─ Lima/socket_vmnet 공유 관리 네트워크
│  ├─ osk8s-controller: 4 vCPU, 8 GiB, 80 GiB, 게스트 swap 2 GiB
│  └─ osk8s-compute:    4 vCPU, 5 GiB, 80 GiB, 게스트 swap 2 GiB
│                       └─ 중첩 KVM 필수
├─ osk8s-image-builder:  4 vCPU, 6 GiB, 50 GiB, 중첩 KVM
│                       └─ controller/compute와 동시에 실행하지 않음
│
├─ controller 내부 external-network 인터페이스 쌍
│  ├─ veth-kolla-ex → OVS br-ex
│  └─ veth-kolla-gw → 172.24.4.1/24 + NAT
│
└─ 임시 macOS route
   └─ 172.24.4.0/24 → controller 관리 IP
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
- macOS sleep 뒤 Lima/VZ guest clock이 정지한 채 남을 수 있으므로 첫 APT
  실행 전에 VZ RTC로 시간을 bootstrap한다. 이후 `local-up`과 controller
  동기화 경계에서 chrony로 복구하고, `local-health`는 호스트 대비 5초 이내의
  controller/compute clock skew를 단언한다.

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
CAPI/CAPO provider는 이 단계에서 아직 설치하지 않는다.

## 생명주기 명령

```bash
make status
make local-health
make local-down
make local-up
make management-cluster-verify
make management-cluster-destroy CONFIRM=local-arm64
make local-destroy CONFIRM=local-arm64
```

`local-down`은 일상적인 정지 작업이며 복구 가능하다. `local-destroy`는
외부 Lima VM 두 대를 제거하므로 그 안의 OpenStack 배포와 모든 Nova VM도
함께 제거한다. 저장소 상태, secret, 실행 artifact는 보존한다.

`local-up`은 두 guest clock을 먼저 복구한 뒤 양방향 관리망 통신을 확인하며,
OpenStack이 이미 배포된 환경에서는 Keystone API, `nova-compute`, hypervisor가
준비될 때까지 대기한다. 따라서 Lima VM이나 컨테이너가 단순히 실행 중이라는
이유만으로 성공을 보고하지 않는다. `make local-health`는 시간을 변경하지 않고
clock skew를 포함한 동일 readiness gate를 다시 실행한다.

## 검증 자료

각 실행은 `artifacts/` 아래에 timestamp가 포함된 디렉터리를 생성한다.
Kolla 로그, preflight 출력, 게스트 console 출력, CAPO network gate 결과를
그곳에 저장한다. secret은 artifact에 복사하지 않는다.

## 다음 마일스톤

현재 다음 순서로 진행한다.

1. Glance용 Kubernetes ARM64 이미지 빌드·업로드·Nova 검증 — **완료**
2. 별도의 로컬 management Kubernetes cluster 생성 — **완료**
3. CAPI와 CAPO 설치 — **다음 단계**
4. CAPO를 통해 workload control plane과 worker 한 대 생성
5. `MachineDeployment`를 한 대에서 두 대로 수동 증설
6. Cluster Autoscaler를 설치하고 Pending Pod 기반 scale-up 검증
