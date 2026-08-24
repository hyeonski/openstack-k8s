# GCP validation baseline

기준일은 2026-08-24이며 대상은 `openstack-k8s` project의
`asia-northeast3-a` 환경이다. 이 문서는 현재 자동화가 보존해야 할 검증 계약과
최근 결과를 요약한다.

## 인프라

- VPC/subnet: `osk8s-mgmt`, `osk8s-seoul` (`10.20.0.0/24`)
- controller: `osk8s-controller`, `10.20.0.10`
- compute: `osk8s-compute01/02`, `10.20.0.21/22`
- Kolla alias VIP: `10.20.0.250`
- custom route: `172.24.4.0/24 → osk8s-controller`
- persistent hosts: `canIpForward=true`, 36,000초 뒤 `STOP`
- refresh plan: `No changes`

## OpenStack

- Kolla-Ansible 2025.2, Ubuntu Noble AMD64 images
- Keystone, Glance, Placement, Nova, Neutron ML2/OVS, Horizon
- nova-compute와 hypervisor 각각 정확히 2개 `up`
- Neutron public `172.24.4.0/24`, tenant `10.10.0.0/24`
- CirrOS 및 Ubuntu guest lifecycle, Floating IP, outbound와 TCP 6443 통과
- VM 재기동 후 runtime recovery gate 통과

## Kubernetes image

- Image Builder v0.1.55 commit `7ffb9b7f1f26cd66891874463cc9411e3633325f`
- Ubuntu 22.04, Kubernetes v1.35.7, containerd 2.3.2
- image `ubuntu-2204-kube-v1.35.7-amd64`, AMD64/BIOS
- Packer/Goss, qemu-img, checksum, Nova boot/reboot 검증 통과

## Management와 workload

- controller kind v0.31.0 / Kubernetes v1.35.0 AMD64
- CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6, ORC v2.4.0 Available
- kind Pod에서 Keystone 인증 및 API 접근 통과
- workload Kubernetes v1.35.7 CP1+worker1, Calico/CoreDNS Ready
- management→workload API와 workload CNI/DNS probe 통과

## 증설

- MachineDeployment 수동 2→1→2→1 통과
- 수동 스케일 전 Cluster Autoscaler 중지와 이전 테스트 부하 정리
- Cluster Autoscaler v1.35.0, node group min/max `1:2`
- CPU request 기반 `Insufficient cpu` Pending Pod 생성
- MachineDeployment와 worker Node 1→2
- 새 worker Nova ACTIVE, Node/Calico Ready, targeted CNI/DNS 통과
- 테스트 Pod가 새 worker에서 Running, 고아 `calico-ipam` 없음

## 현재 리팩터링 재검증

2026-08-24 GCP-only 전환 후 다음 검증을 다시 통과했다.

- OpenTofu configuration validate 통과, refresh plan `No changes`
- controller와 compute 2대 `RUNNING`, host readiness 통과
- controller 입력 동기화 후 배포 트리에 로컬 VM/ARM64 잔재 없음
- Keystone와 Placement ready, nova-compute와 hypervisor 각각 2개
- kind management cluster, CAPI/CAPO/ORC, OpenStack credential 통과
- workload 수동 2→1→2→1, 각 단계의 CAPI/Nova/노드/CNI/DNS 통과
- Autoscaler image/arguments/RBAC/min-max 검증과 Pending Pod 기반 1→2 통과

재검증 도중 이전 Autoscaler 테스트 부하가 남아 있으면 수동 2→1 축소 직후
Autoscaler가 다시 2대로 올리는 상태 충돌을 확인했다. 수동 스케일 진입점이
Autoscaler deployment를 0으로 내리고 이전 test deployment와 targeted probe를
정리하도록 보완했으며, 이후 전체 수명주기를 재검증했다. Autoscaler 설치
단계는 선언된 manifest를 다시 적용해 replica를 1로 복원한다.
