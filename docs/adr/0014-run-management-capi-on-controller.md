# ADR-0014: Management kind와 CAPI/CAPO를 controller에서 실행한다

- 상태: 채택됨
- 결정일: 2026-08-24

## 배경

CAPI/CAPO와 Cluster Autoscaler에는 OpenStack API 및 workload API에 접근 가능한
management Kubernetes가 필요하다. 별도 management VM은 비용과 lifecycle을
추가하며, controller에는 검증된 가용 메모리와 Docker runtime이 있다.

## 결정

- `osk8s-controller`의 Docker daemon에서 단일 노드 kind를 실행한다.
- Kolla Docker daemon 설정은 변경하지 않는다.
- `br-kind-mgmt`와 `172.30.0.0/24` network, forwarding/MASQUERADE는 전용
  systemd unit으로 관리한다.
- management API는 controller 내부 IP의 TCP 16443에 bind하고 IAP에서만 허용한다.
- CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6, ORC v2.4.0과 Autoscaler v1.35.0을
  digest 또는 checksum이 고정된 입력으로 설치한다.

## 결과

management lifecycle이 OpenStack controller와 함께 복구되며 별도 GCE VM이
필요하지 않다. controller resource headroom, kind bridge/NAT와 Pod→OpenStack
경로는 모든 검증에서 확인해야 한다.

## 재검토 조건

- controller memory 또는 disk headroom이 지속적으로 기준을 밑도는 경우
- management control plane HA가 필요한 경우
- Kolla Docker lifecycle과 kind lifecycle이 충돌하는 경우
