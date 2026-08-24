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
GCP 인스턴스는 이 시점에 controller와 compute 2대만 남았으며 세 인스턴스
모두 36,000초 자동 STOP을 유지했다. 따라서 GCP AMD64 Kubernetes 이미지
checkpoint는 완료됐다.

## GCP management Kubernetes

Kolla controller의 `/etc/docker/daemon.json`은 서비스 네트워크 충돌을 막기
위해 `bridge=none`, `ip-forward=false`, `iptables=false`를 사용한다. 최초에는
별도 `e2-standard-2` management VM에서 kind를 검증했지만 실제 사용량을 측정한
뒤 controller 통합으로 변경했다. 통합 전 controller는 15.6 GiB 중 7.7 GiB
available, 루트 디스크 61 GiB 여유였고 별도 kind는 약 628 MiB를 사용했다.

통합은 Kolla Docker daemon 설정이나 서비스를 변경하지 않는다.

- runtime host: `osk8s-controller`, 4 vCPU/16 GiB
- runtime: kind v0.31.0, Kubernetes v1.35.0 AMD64
- Docker network: 표준 `kind`, `172.30.0.0/24`, `br-kind-mgmt`
- network lifecycle: 전용 systemd oneshot과 명시적 FORWARD/MASQUERADE 규칙
- API: controller 내부 IP `10.20.0.10:16443`
- local access: IAP tunnel `127.0.0.1:16443`

OpenTofu는 기존 IAP firewall의 target을 `osk8s-controller-management` tag로,
포트를 TCP 16443으로 바꾸고 controller tag만 in-place 갱신했다. 전용 validator가
`0 add / 2 change / 0 destroy` 외의 계획을 거부하며 public API 방화벽은 없다.

kind 바이너리 SHA-256과 node image digest를 고정했다. API 인증서에는 내부 IP와
로컬 IAP 종단 `127.0.0.1`을 SAN으로 포함하며, 자동화는 기존 cluster의 port
binding과 SAN이 선언과 다르면 kind만 재생성한다. repository 전용 kubeconfig는
`.state/cloud-gcp-amd64/kubeconfigs/management.yaml`에 저장한다.

최종 표준 `kind` network 구성의 실제 검증 결과는 다음과 같다.

- management node와 kube-system Pod 모두 Ready
- node architecture `amd64`, Kubernetes `v1.35.0`
- kind Pod에서 Keystone VIP `10.20.0.250:5000` 접근 성공
- 보존한 Ubuntu 검증 VM의 Floating IP `172.24.4.159:6443` 접근 성공
- 검증 후 Ubuntu server와 Floating IP를 전용 cleanup target으로 삭제
- Kolla `validate-config`: controller `failed=0`, compute01/02 `failed=0`
- 통합 후 controller: kind 523 MiB, memory 7.1 GiB available, disk 58 GiB 여유,
  swap 사실상 미사용
- controller 정상 stop/start 후 동일 kind cluster와 전용 bridge/NAT가 자동 복구됐고
  Pod→Keystone, Nova compute/hypervisor `up`을 재확인했다. 재기동 후 controller는
  memory 8.4 GiB available, swap 0이었다.
- controller와 compute01/02 세 VM 모두 36,000초 자동 STOP 유지

구 `osk8s-management` kind를 먼저 삭제한 뒤 OpenTofu 전용 validator로 VM과
예약 내부 주소만 삭제했다. 삭제 계획은 `0 add / 0 change / 2 destroy`였으며
controller, compute, OpenStack과 IAP firewall은 대상이 아니었다.
`management-cluster-destroy CONFIRM=cloud-gcp-amd64`는 controller의 kind,
로컬 kubeconfig와 전용 bridge/NAT만 삭제하고 controller와 OpenStack은 보존한다.

2026-08-24에는 management API IAP tunnel을 각 명령의 수명 안에서 재확립하도록
접근 게이트를 보완하고 고정된 provider 조합을 설치했다.

- CAPI/CABPK/KCP 및 `clusterctl`: v1.13.4
- CAPO: v0.14.6
- ORC: v2.4.0
- cert-manager: v1.20.3 (`clusterctl`이 provider 계약에 따라 설치)
- 모든 provider deployment `Available`
- 기존 application credential를 `osk8s-workload` namespace Secret으로 연결
- kind 인증 Pod에서 Keystone token 발급 성공 후 probe Pod 삭제
- provider 설치 후 controller: kind 1.608 GiB, memory 7.5 GiB available,
  disk 58 GiB 여유, swap 0

로컬 ARM64 검증에 직접 고정돼 있던 `limactl`, macOS route와 Kubernetes
architecture 검사는 host provider 및 환경별 runtime architecture 계약으로
분리했다. GCP custom route는 destination과 controller next hop을 조회해
검증하며 workload/Autoscaler 단계도 같은 management API 접근 게이트를 쓴다.

## GCP CAPO workload 기준선

2026-08-24에 CAPO로 control plane 1대와 worker 1대를 생성했다. workload API는
public 방화벽이나 macOS route를 추가하지 않고 controller를 경유하는 IAP SSH
forwarding `127.0.0.1:16444`로 접근한다. repository kubeconfig는 server를 로컬
종단으로 바꾸되 TLS server-name은 실제 Floating IP `172.24.4.117`로 유지한다.
각 workload/Autoscaler 명령은 management tunnel과 workload tunnel을 자기 실행
수명 안에서 다시 만든다.

첫 생성에서는 장시간 정지 후 controller가 부팅될 때 Placement WSGI가 database
준비보다 먼저 초기화돼 `placement_api`가 unhealthy 상태로 남았다. Nova fault는
`The placement service ... does not have any supported versions`였으며 CAPO 자체
오류가 아니었다. database와 Keystone 준비 뒤 Placement를 재시작하고 실패한
하위 OpenStackServer/port만 정리해 동일 Cluster reconcile을 재개했다.

이 재기동 순서 문제를 반복하지 않도록 `gcp-host-verify`와 workload 생성/증설은
runtime recovery gate를 사용한다. 이 gate는 Keystone과 Placement API, 정확히
두 개의 `nova-compute` 및 hypervisor를 확인하고, Placement가 unhealthy일 때만
재시작한 뒤 Nova scheduler를 갱신한다.

최종 검증 결과는 다음과 같다.

- Cluster와 KubeadmControlPlane `Available`
- control plane `10.6.0.30`, worker `10.6.0.152`, 모두 Ready
- Kubernetes v1.35.7, Ubuntu 22.04.5, containerd 2.3.2, architecture amd64
- control plane은 compute02, worker는 compute01에 ACTIVE 상태로 분산
- Calico node/controller Ready
- management Pod에서 workload TCP 6443 접근 성공
- workload Pod의 `kubernetes.default.svc.cluster.local` DNS 조회 성공
- controller 6.6 GiB available, compute01/02 각각 약 12 GiB available, swap 0
- 새 프로세스의 독립 `workload-cluster-verify WORKERS=1` 재검증 성공

## GCP 수동 및 자동 증설 checkpoint

2026-08-24에 다음 경로를 순서대로 통과했다.

1. MachineDeployment를 worker 1대에서 2대로 수동 증설하고 새 node의 CNI/DNS와
   전체 workload readiness를 검증했다.
2. worker를 다시 1대로 축소하고 Cluster Autoscaler v1.35.0을 controller의
   management kind cluster에 설치했다.
3. Autoscaler 이미지 digest, CAPI 인자, 양쪽 cluster RBAC와 node group min/max
   `1:2`를 검증했다.
4. worker allocatable 2,000m와 기존 request 250m에서 Pod당 1,050m를 선택했다.
   두 Pod 중 하나가 `Insufficient cpu`로 Pending 된 뒤 MachineDeployment가
   자동으로 1대에서 2대로 변경됐다.
5. 새 worker `osk8s-workload-md-0-jm9vc-g8kvf`가 `10.6.0.15`로 합류했고 Nova
   ACTIVE, Node/Calico Ready, targeted CNI/DNS와 전체 API/CNI/DNS 검증을 통과했다.
   Pending Pod가 새 worker에서 Running이 됐고 고아 `calico-ipam` 프로세스도
   없었다. 테스트 workload 생성부터 최종 증거 보존까지 155초가 걸렸다.

macOS의 workload kubeconfig는 IAP SSH tunnel `127.0.0.1:16444`를 사용하지만,
management cluster의 Autoscaler Secret에는 Pod 내부에서도 접근 가능한 실제
Floating IP endpoint `172.24.4.117:6443`을 넣는다. public Kubernetes API
방화벽은 추가하지 않았다.

이 checkpoint로 `cloud-gcp-amd64`의 OpenStack, CAPI/CAPO와 자동 증설 기능 이전은
완료됐다. 다음 환경 이전 대상은 물리 AMD64 호스트 프로필이다.

GCP custom route와 36,000초 자동 STOP을 모두 유지한다. 각 checkpoint는 VM
재기동 후 readiness를 다시 확인하고 완료된 단계부터 idempotent하게 재개할 수
있어야 한다.
