# GCP AMD64 이전 기반 보고서 — 2026-08-20

## 판정

기존 GCP 호스트를 재생성하지 않고 OpenTofu 관리 경계로 가져왔으며,
`cloud-gcp-amd64` 프로필의 host discovery, 2-compute inventory, IAP 원격 실행과
controller-to-compute SSH가 통과했다. OpenStack은 아직 배포하지 않았다.

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
- controller에서 `10.20.0.21`, `10.20.0.22`로 batch SSH 성공

배포 입력은 controller의 `/opt/openstack-k8s`에 동기화했다. Docker와 Kolla
virtualenv는 아직 설치하지 않았으며 해당 작업은 OpenStack 배포 checkpoint에서
수행한다.

## 다음 checkpoint

1. GCP archive/IAP sync로 배포 입력을 controller에 배치한다.
2. AMD64 host prepare와 nested KVM boot gate를 실행한다.
3. Kolla bootstrap, precheck, pull, deploy, post-deploy를 독립적으로 기록한다.
4. controller external veth/NAT를 검증한 후에만
   `172.24.4.0/24 -> osk8s-controller` route를 활성화한다.
5. CirrOS/Ubuntu AMD64 guest, DHCP, outbound와 Floating IP data path를 검증한다.
6. 별도 builder와 management cluster checkpoint로 이동한다.

36,000초 자동 STOP은 변경하지 않는다. 각 checkpoint는 VM 재기동 후 readiness를
다시 확인하고 완료된 단계부터 idempotent하게 재개할 수 있어야 한다.
