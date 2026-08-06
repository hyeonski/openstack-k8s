# ADR-0006: 로컬에서는 단일 NIC와 논리 external network를 사용한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 및 검증 완료

## 맥락

Kolla quickstart 형태는 관리/API 트래픽용 인터페이스와 Neutron external
network용 비할당 인터페이스를 흔히 분리한다. 그러나 로컬 VM, cloud VM과
최종 물리 서버에서 항상 물리 NIC 두 개를 확보할 수 있다고 가정할 수 없다.
동시에 `br-ex`에 연결할 전용 인터페이스는 필요하다.

## 결정

- Lima VM은 `socket_vmnet` shared 관리 NIC 하나만 가진다.
- 관리, API와 tunnel 트래픽은 같은 `lima0` 인터페이스를 사용한다.
- controller 내부에 `veth-kolla-ex`와 `veth-kolla-gw` pair를 만든다.
- `veth-kolla-ex`는 주소 없이 OVS `br-ex`에 연결한다.
- `veth-kolla-gw`는 external subnet gateway를 갖고 IP forwarding/NAT를
  통해 controller uplink로 연결한다.
- macOS에는 Floating IP CIDR을 controller 관리 IP로 보내는 명시적 route를
  설치한다.
- external, tenant, management CIDR은 환경 변수이며 preflight에서 호스트
  network와 겹치지 않는지 검사한다.

## 검토한 대안

- **VM마다 NIC 두 개:** quickstart와 유사하지만 Lima/cloud/bare-metal 간
  공통 가정을 늘리고 실제 물리 NIC 수에 종속된다.
- **물리 NIC 두 개를 최종 필수 조건으로 지정:** 관리망 격리에는 유리하지만
  장비 선정 전부터 불필요한 제약을 만든다.
- **VLAN subinterface/bridge:** 물리 환경에서 좋은 선택일 수 있으나 로컬
  구현으로 고정하지 않는다.
- **external access 생략:** CAPO와 workload API 접근 경로를 검증할 수 없다.

## 결과

- local profile은 물리 NIC 한 개로도 provider/external network 의미를
  검증할 수 있다.
- traffic isolation과 throughput은 production 수준이 아니다.
- cloud/bare-metal 프로필에서는 veth/NAT를 그대로 복사하지 않고 실제 NIC,
  VLAN, bridge, alias IP 또는 cloud routing으로 교체한다.
- 현재 기본 `172.24.4.0/24`는 일부 Wi-Fi의 넓은 `172.16.0.0/12`와 충돌할
  수 있다. preflight 실패를 우회하지 말고 환경에 맞는 대역을 선택해야 한다.

## 재검토 조건

- 최종 장비에서 관리망과 provider망의 물리 분리가 필수일 때
- cloud provider가 nested VM의 MAC/IP forwarding을 제한할 때
- MTU 또는 overlay 중첩 문제가 workload network를 방해할 때
