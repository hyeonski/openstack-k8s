# GCP AMD64 이전 기반 보고서 — 2026-08-20

## 판정

기존 GCP 호스트를 재생성하지 않고 OpenTofu 관리 경계로 가져왔으며,
`cloud-gcp-amd64` 프로필의 host discovery, 2-compute inventory, IAP 원격 실행과
controller-to-compute SSH가 통과했다. OpenStack은 아직 배포하지 않았다.
이후 controller의 Kolla 실행 환경 설치와 세 호스트의 host prepare도 완료했다.

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

GCP가 `10.20.0.250` alias VIP를 controller NIC에 귀속하고 라우팅하므로 이
환경에서는 HAProxy만 활성화하고 keepalived는 비활성화한다. keepalived가 이미
사용 중인 alias VIP의 소유권을 다시 관리하지 않도록 하는 public-cloud 경계다.

GCP Ubuntu 이미지에는 UFW 실행 파일이 없으므로 UFW가 설치된 호스트에서만
비활성화하도록 host prepare를 수정했다. 또한 GCP 커널은 대응하는
`/boot/initrd.img-*`가 없을 수 있으므로, 이 경우 initrd 없이 커널을 직접
부팅해 KVM 가속 경로를 검증한다.

## 다음 checkpoint

1. 공식 AMD64 컨테이너 이미지를 pull한다.
2. Kolla deploy와 post-deploy를 독립적으로 기록한다.
3. OpenStack API와 controller external veth/NAT를 함께 검증한 후에만
   `172.24.4.0/24 -> osk8s-controller` route를 활성화한다.
4. CirrOS/Ubuntu AMD64 guest, DHCP, outbound와 Floating IP data path를 검증한다.
5. 별도 builder와 management cluster checkpoint로 이동한다.

36,000초 자동 STOP은 변경하지 않는다. 각 checkpoint는 VM 재기동 후 readiness를
다시 확인하고 완료된 단계부터 idempotent하게 재개할 수 있어야 한다.
