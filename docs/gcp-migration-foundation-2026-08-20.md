# GCP AMD64 이전 기반 보고서 — 2026-08-20

## 판정

기존 GCP 호스트를 재생성하지 않고 OpenTofu 관리 경계로 가져왔으며,
`cloud-gcp-amd64` 프로필의 host discovery, 2-compute inventory, IAP 원격 실행과
controller-to-compute SSH가 통과했다. 이후 controller의 Kolla 실행 환경 설치와
세 호스트의 host prepare를 마쳤고, OpenStack 2025.2 핵심 서비스를 실제로
배포했다. 배포 후 Kolla 설정 검증, 컨테이너 health와 내부 VIP Keystone API까지
통과했다.

## 채택한 기존 리소스

- project/region/zone: `openstack-k8s`, `asia-northeast3`,
  `asia-northeast3-a`
- VPC/subnet: `osk8s-mgmt`, `osk8s-seoul` (`10.20.0.0/24`)
- internal addresses: controller `.10`, compute `.21`/`.22`, Kolla VIP `.250`
- controller: `e2-standard-4`, 80 GiB
- compute01/02: `n2-standard-4`, 각 120 GiB, nested virtualization 활성화
- 모든 host: `canIpForward=true`, 36,000초 뒤 `STOP`
- controller disk: 일일 snapshot, 14일 보존

OpenTofu v1.12.6과 Google provider v7.45.0으로 import한 뒤 refresh plan은 다음과
같았다.

```text
No changes. Your infrastructure matches the configuration.
```

apply는 실행하지 않았다. network, subnetwork, internal address와 instance에는
`prevent_destroy`를 둔다. OpenStack Floating IP route는 다음 gate 전까지
`enable_openstack_floating_ip_route=false`다.

## 프로필과 실행 경로

- `config/environments/cloud-gcp-amd64.env`
- 실제 NIC `ens4`, architecture `x86_64`
- `compute01`과 `compute02` 모두 Ansible/Kolla inventory에 포함
- host provider가 `lima`이면 기존 `limactl`, `gcp`이면 `gcloud compute ssh/scp`
  + IAP를 사용
- controller에는 환경 전용 ED25519 private key를 두고 두 compute에는 public
  key만 설치
- Kolla AMD64 template은 로컬 ARM64 nova-libvirt/AAVMF workaround를 상속하지
  않음

## 실제 검증 결과

세 호스트에서 다음 gate가 통과했다.

- Ubuntu 24.04 x86_64
- chrony active
- IPv4 forwarding과 bridge netfilter 활성화
- project swap 2 GiB
- reboot 불필요
- compute01/02 `/dev/kvm`, nested KVM 사용 가능
- compute01/02에서 현재 GCP 커널의 nested KVM 직접 부팅 성공
- controller에서 `10.20.0.21`, `10.20.0.22`로 batch SSH 성공
- controller `openstack-external-network.service`, 외부 veth와
  `172.24.4.1/24` 게이트웨이 활성화
- controller와 compute01/02 Docker daemon 활성화

배포 입력은 controller의 `/opt/openstack-k8s`에 동기화했다. controller의
`/opt/kolla-venv`에는 Kolla-Ansible 21.2.0과 고정된 Kolla collection 및
OpenStack CLI/SDK가 설치됐다. Kolla `bootstrap-servers`가 세 호스트에 Docker와
containerd를 설치했으며 전체 precheck도 통과했다.

Kolla pull은 약 8분 44초 만에 완료됐다. controller에는 24개, 각 compute에는
8개의 `quay.io/openstack.kolla` 이미지가 배치됐으며 모든 이미지가
`2025.2-ubuntu-noble`, `amd64`임을 확인했다. pull 후 가용 디스크는 controller
67 GiB, compute별 105 GiB다.

Kolla `validate-config`는 실행 중인 HAProxy 등 서비스 컨테이너 내부의 설정을
검사하므로 pull 직후가 아니라 deploy 이후에 실행한다. 배포 전 설정 gate는
이미 통과한 `prechecks`다.

Kolla deploy는 약 15분 24초 만에 완료됐다. Ansible recap은 controller
`failed=0`, compute01/02 `failed=0`이었고 Nova가 두 compute 서비스를 셀에
등록했다. 배포된 컨테이너는 controller 27개, 각 compute 8개이며 모두 `Up`
상태다. healthcheck가 정의된 컨테이너는 모두 `healthy`이고, healthcheck가 없는
cron, kolla-toolbox와 neutron-metadata-agent도 실행 중이다.

배포 후 `validate-config`는 약 3분 1초 만에 완료됐으며 세 호스트 모두
`failed=0`이었다. HAProxy, Keystone, Glance, Placement, Nova, Neutron의 활성
서비스 설정이 실제 컨테이너에서 검증됐다. controller에서 내부 VIP
`http://10.20.0.250:5000/v3`을 조회해 Keystone `v3.14` 응답도 확인했다.

2026-08-21에는 세 인스턴스가 모두 `TERMINATED`인 상태에서 다시 기동해 복구
경로를 확인했다. controller와 compute 2대 모두 기존 내부 IP와 36,000초 자동
STOP 설정을 유지했고, chrony, Docker, 외부 veth 및 compute nested KVM 검증이
통과했다. 재기동 후 `validate-config`도 세 호스트 모두 `failed=0`으로 완료됐다.

Kolla post-deploy는 약 8초 만에 완료됐다. 생성된 `clouds.yaml`과
`passwords.yml`은 로컬 `.state/cloud-gcp-amd64/secrets`에 수집했으며 디렉터리는
`0700`, 파일은 `0600` 권한이다. 관리자 인증으로 다음 상태를 확인했다.

- service catalog: Keystone, Glance, Placement, Nova, Neutron
- `nova-compute`: compute01/02 모두 `enabled`, `up`
- hypervisor: compute01/02 모두 `up`
- Neutron agent: controller 4개와 compute별 OVS agent, 총 6개 모두 `Alive`, `UP`

OpenStack bootstrap도 완료했다. 생성 후 재실행까지 성공했으며 기존 project,
network, subnet, router, flavor와 security group을 중복 생성하지 않고 재사용했다.
현재 영속 리소스는 다음과 같다.

- project/user: `capi-test`, member role
- external network/subnet: `public`, `172.24.4.0/24`
- tenant network/subnet/router: `private`, `10.10.0.0/24`, `test-router`
- flavor: `m1.gcp` 1 vCPU/1 GiB/10 GiB, control plane과 worker 각각
  2 vCPU/2 GiB/20 GiB
- security group: ICMP, TCP 22와 TCP 6443 허용
- image: `cirros-0.6.3-x86_64`, `ubuntu-24.04-amd64` 모두 `active`

이미지 준비와 업로드 경로는 환경 아키텍처를 따르도록 수정했다. 캐시 파일명에서
ARM64 표기를 제거하고 `ARCHITECTURE`를 bootstrap playbook에 전달한다. GCP에
업로드된 두 이미지 모두 `hw_architecture=x86_64`, `hw_firmware_type=bios`임을
Glance에서 확인했다. 이 수정 전에는 AMD64 이미지 바이트에 ARM64/UEFI
메타데이터가 붙어 Nova 스케줄링이나 부팅을 방해할 수 있었다.

`capi-test` project에는 restricted application credential과 workload SSH
keypair를 생성했다. application credential로 Keystone token 발급과 keypair
조회가 성공했고, 로컬 `capi-clouds.yaml`은 Git ignore 및 `0600` 권한을
확인했다. 최신 OpenStack CLI가 keypair의 `public_key` 출력 열을 제공하지 않는
문제는 로컬 public key와 Nova keypair의 MD5 fingerprint를 비교하도록 수정해
재실행도 통과했다.

controller external veth/NAT와 bootstrap gate가 통과한 뒤 OpenTofu로 GCP custom
route를 활성화했다. 적용 계획은
`google_compute_route.openstack_floating_ips[0]` 1개 생성, 변경 0개, 삭제 0개였고
적용 후 전체 plan은 다시 `No changes`다. `openstack.auto.tfvars`가
`172.24.4.0/24 -> osk8s-controller` 상태를 유지한다. 세 GCP 인스턴스의
36,000초 자동 STOP 설정은 바뀌지 않았다.

실제 AMD64 게스트와 네트워크 검증도 통과했다.

- CirrOS: Nova 부팅, tenant DHCP, Floating IP SSH와 `1.1.1.1` outbound ping
- Ubuntu 24.04: cloud-init 완료, `capo-api-probe.service` 활성화와 TCP 6443 응답
- compute01/02: 각 호스트에서 Keystone VIP `10.20.0.250:5000`과 Ubuntu
  Floating IP `:6443` 접근
- cleanup: 검증용 CirrOS/Ubuntu server와 Floating IP 삭제

Kolla compute의 Docker daemon은 서비스 네트워크 충돌을 피하기 위해
`bridge=none`, `iptables=false`로 구성돼 있다. 따라서 Lima에서 사용한 Docker
bridge probe를 compute 호스트에 그대로 적용하지 않고, 두 compute를 독립적인
GCP VPC 소비자로 검증했다. management cluster의 실제 container-to-OpenStack 및
container-to-workload API 경로는 cloud management cluster 배치가 정해지는 다음
checkpoint에서 검증한다.

GCP가 `10.20.0.250` alias VIP를 controller NIC에 귀속하고 라우팅하므로 이
환경에서는 HAProxy만 활성화하고 keepalived는 비활성화한다. keepalived가 이미
사용 중인 alias VIP의 소유권을 다시 관리하지 않도록 하는 public-cloud 경계다.

GCP Ubuntu 이미지에는 UFW 실행 파일이 없으므로 UFW가 설치된 호스트에서만
비활성화하도록 host prepare를 수정했다. 또한 GCP 커널은 대응하는
`/boot/initrd.img-*`가 없을 수 있으므로, 이 경우 initrd 없이 커널을 직접
부팅해 KVM 가속 경로를 검증한다.

## AMD64 Kubernetes 이미지 빌드

GCP 전용 일회성 `osk8s-image-builder`를 OpenTofu 선언에 추가했다. 빌더는
`n2-standard-4`, 80 GiB balanced persistent disk, nested KVM 구성이고 기존
호스트와 같은 36,000초 뒤 `STOP` 비용 제어를 사용한다. 생성 plan은 이 VM 한
대 추가, 변경 0개, 삭제 0개임을 전용 validator로 확인한 뒤 적용했다.

Kubernetes Image Builder v0.1.55의 commit
`7ffb9b7f1f26cd66891874463cc9411e3633325f`과 Ubuntu 22.04.5 ISO checksum을
고정해 Kubernetes v1.35.7, containerd 2.3.2, pause 3.10.2 AMD64/BIOS QCOW2를
빌드했다. Packer 빌드는 31분 52초가 걸렸고 Image Builder Goss 검사는
65개 모두 성공했다. 압축 후 `qemu-img check`와 로컬 회수 후 SHA-256 대조도
통과했다.

```text
artifact: ubuntu-2204-kube-v1.35.7-amd64.qcow2
virtual size: 20 GiB
actual size: 2,251,358,208 bytes
sha256: 298cacee5a803be9f496745e390dfa96b2be3fa7d33555d4dee97c7552a95946
dirty: false
corrupt: false
```

Glance에는 private 이미지 `ubuntu-2204-kube-v1.35.7-amd64`로 등록했다.
이미지 ID는 `8094033c-c7e4-48c7-8cbd-e751caae6cbb`이고 상태 `active`,
`hw_architecture=x86_64`, `hw_firmware_type=bios`와 로컬 SHA-256 속성이
일치한다.

이 이미지로 실제 Nova VM을 만들고 Floating IP `172.24.4.135`를 통해 다음
검증을 통과했다.

- Nova ACTIVE와 SSH, cloud-init 완료
- x86_64 guest와 Kubernetes v1.35.7 패키지 버전
- containerd CRI, overlay/br_netfilter, IPv4 forwarding, swap 비활성화
- `registry.k8s.io/pause:3.10.2` pull
- 재부팅 후 SSH, cloud-init과 containerd readiness

성공 후 검증 server, Floating IP와 전용 keypair를 삭제했다. 일회성 GCP
builder 삭제 plan은 추가 0개, 변경 0개, 해당 VM 삭제 1개였고 전용 validator
통과 후 적용했다. 삭제 뒤 전체 OpenTofu refresh plan은 다시 `No changes`다.
GCP 인스턴스는 controller와 compute 2대만 남았으며 세 인스턴스 모두
36,000초 자동 STOP을 유지한다. 따라서 GCP AMD64 Kubernetes 이미지
checkpoint는 완료됐다.

## 다음 checkpoint

1. cloud management cluster의 실행 위치와 lifecycle을 확정한다.
2. management cluster 내부에서 OpenStack API와 workload Floating IP 경로를
   검증한 뒤 CAPI/CAPO provider checkpoint로 이동한다.

GCP custom route와 36,000초 자동 STOP을 모두 유지한다. 각 checkpoint는 VM
재기동 후 readiness를 다시 확인하고 완료된 단계부터 idempotent하게 재개할 수
있어야 한다.
