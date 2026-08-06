# ADR-0002: Kubernetes lifecycle은 standalone CAPI/CAPO로 관리한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 미구현, OpenStack API 네트워크 게이트만 검증됨

## 맥락

OpenStack VM으로 Kubernetes control plane과 worker를 만들고, worker group을
Cluster Autoscaler가 증설할 수 있어야 한다. 이후 VM 생성 지연, bootstrap
실패, orphan resource, worker 장애를 관찰하거나 별도 controller를 붙일
가능성도 있다.

검토한 주요 경로는 Magnum+Heat, Magnum+CAPI, standalone CAPI+CAPO였다.

## 결정

- OpenStack에는 Magnum을 추가하지 않고 **standalone CAPI+CAPO**를 사용한다.
- 첫 PoC에서는 macOS의 별도 `kind` cluster를 management cluster로 사용한다.
- CAPI core, kubeadm bootstrap/control-plane provider와 CAPO controller는
  management cluster에서 실행한다.
- Kubernetes control plane과 worker는 모두 OpenStack VM으로 만든다.
- worker group은 `MachineDeployment`로 표현한다.
- 첫 Cluster Autoscaler는 workload cluster에서 실행하고, workload API와
  management cluster의 CAPI API 양쪽에 접근하게 한다.
- 첫 autoscaling trigger는 resource request 때문에 발생한 Unschedulable
  Pending Pod로 제한한다.

## 검토한 대안

- **Magnum+Heat:** OpenStack 사용자 경험은 단순하지만 신규 연구 기반으로는
  lifecycle 상태가 덜 직접적으로 드러나고 Heat 경로에 종속된다.
- **Magnum+CAPI:** KaaS나 다중 tenant 서비스에는 유용하지만 이 프로젝트에는
  Magnum API 계층이 추가 복잡성이 된다.
- **Nova API와 kubeadm을 직접 호출하는 자체 autoscaler:** 중복 생성,
  bootstrap 실패, token 만료, drain, orphan 정리 등 이미 해결된 문제를 다시
  구현해야 한다.
- **OpenStack host에 Kubernetes 설치:** infrastructure provider와 workload의
  장애 영역이 섞이며 CAPO가 관리할 `Machine`이 생기지 않는다.
- **workload cluster가 자기 자신을 관리:** pivot은 가능하지만 첫 PoC에서
  순환 의존성과 복구 난도가 커진다.

## 결과

- management Kubernetes cluster가 하나 더 필요하다.
- VM 생성 과정은 `Cluster`, `MachineDeployment`, `Machine`,
  `OpenStackMachine` 상태로 관찰할 수 있다.
- OpenStack API와 workload API endpoint가 management cluster에서 모두
  접근 가능해야 한다.
- worker를 0대로 줄이려면 Cluster Autoscaler 실행 위치를 다시 검토해야 한다.
- 정확한 버전, CNI, CCM, API endpoint 방식은 구현 전에 별도로 확정한다.

## 재검토 조건

- 목표가 단일 연구 cluster가 아니라 다중 tenant KaaS 제공으로 바뀌는 경우
- Magnum+CAPI가 운영 요구사항을 크게 단순화하는 경우
- scale-to-zero 때문에 autoscaler를 management cluster로 옮겨야 하는 경우
