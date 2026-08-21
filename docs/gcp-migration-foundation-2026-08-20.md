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

GCP가 `10.20.0.250` alias VIP를 controller NIC에 귀속하고 라우팅하므로 이
환경에서는 HAProxy만 활성화하고 keepalived는 비활성화한다. keepalived가 이미
사용 중인 alias VIP의 소유권을 다시 관리하지 않도록 하는 public-cloud 경계다.

GCP Ubuntu 이미지에는 UFW 실행 파일이 없으므로 UFW가 설치된 호스트에서만
비활성화하도록 host prepare를 수정했다. 또한 GCP 커널은 대응하는
`/boot/initrd.img-*`가 없을 수 있으므로, 이 경우 initrd 없이 커널을 직접
부팅해 KVM 가속 경로를 검증한다.

## 다음 checkpoint

1. Kolla post-deploy를 실행하고 생성된 admin clouds 파일을 로컬로 수집한다.
2. admin 인증으로 서비스 catalog, compute service와 network agent 상태를
   확인한다.
3. OpenStack API와 controller external veth/NAT를 함께 검증한 후에만
   `172.24.4.0/24 -> osk8s-controller` route를 활성화한다.
4. CirrOS/Ubuntu AMD64 guest, DHCP, outbound와 Floating IP data path를 검증한다.
5. 별도 builder와 management cluster checkpoint로 이동한다.

36,000초 자동 STOP은 변경하지 않는다. 각 checkpoint는 VM 재기동 후 readiness를
다시 확인하고 완료된 단계부터 idempotent하게 재개할 수 있어야 한다.
