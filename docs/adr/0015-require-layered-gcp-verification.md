# ADR-0015: IaC부터 Autoscaler까지 계층별 GCP 검증을 요구한다

- 상태: 채택됨
- 결정일: 2026-08-24

## 배경

최종 worker 증설만 확인하면 IaC drift, IAP 접근, nested KVM, OpenStack runtime,
CAPI reconcile 또는 CNI 문제를 구분할 수 없다. 실패 시 자동 정리는 원인 증거를
지울 수 있다.

## 결정

검증은 다음 순서를 따른다.

1. OpenTofu/Terraform validate와 refresh plan `No changes`
2. GCE 인스턴스 이름, 내부 IP, 36,000초 자동 STOP과 IAP 접근
3. controller→compute SSH, `/dev/kvm`과 nested kernel boot
4. Keystone, Placement, nova-compute 두 개와 hypervisor 두 개
5. management node/System Pod와 Pod→OpenStack API
6. CAPI/CAPO/ORC availability와 application credential 인증
7. workload CP1+worker1, API/CNI/DNS와 provider identity
8. 수동 worker 1→2→1
9. Autoscaler Pending Pod 기반 1→2와 새 worker targeted probe

삭제 명령은 정확한 확인값과 소유 범위를 요구한다. 검증 실패 상태와 진단
artifact는 기본적으로 보존한다.

## 결과

실패 계층과 책임 경계를 빠르게 식별할 수 있고 destructive cleanup을 피한다.
전체 E2E는 시간이 들지만 실행 경로 또는 인프라 계약 변경 후에는 생략하지 않는다.

## 재검토 조건

- CI에서 동일 계층을 더 빠르게 격리할 수 있는 경우
- provider 버전 또는 네트워크 topology가 변경되는 경우
- scale-down, 장애 복구 또는 HA가 필수 범위에 포함되는 경우
