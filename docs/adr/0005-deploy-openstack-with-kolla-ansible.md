# ADR-0005: OpenStack 2025.2를 Kolla-Ansible로 배포한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 및 검증 완료

## 맥락

OpenStack은 Nova, Neutron, Keystone, Glance, Placement와 database/message
queue 등 여러 서비스를 일관되게 설치해야 한다. 프로젝트의 연구 대상은
OpenStack 설치기 자체가 아니므로 서비스별 패키지 설치와 설정을 직접
재구현할 이유가 없다.

## 결정

- OpenStack release를 2025.2로 고정한다.
- Ubuntu 24.04 ARM64 host 위에 Kolla의 Debian Bookworm ARM64 container를
  배포한다.
- Kolla-Ansible은 controller의 고정 virtual environment에서 실행한다.
- controller 한 대가 control/network 역할을 맡고 compute 한 대가
  `nova-compute`와 KVM을 맡는다.
- Neutron은 ML2/Open vSwitch를 사용한다.
- Keystone, Glance, Nova, Placement, Neutron과 Horizon만 활성화한다.
- storage는 Nova local ephemeral과 Glance file backend로 제한한다.
- Cinder, Ceph, Heat, Magnum, Octavia와 telemetry는 첫 범위에서 제외한다.

## 검토한 대안

- **서비스별 package 설치를 직접 Ansible로 작성:** 학습 효과는 있지만
  설치기 유지보수에 프로젝트 시간을 소비한다.
- **DevStack:** 개발·단기 실험에는 적합하지만 반복 가능한 multinode 기반과
  cloud/bare-metal 이전 기준으로 채택하지 않았다.
- **OpenStack-Ansible 등 다른 배포 도구:** 가능하지만 기존 Ansible 지식,
  containerized lifecycle과 필요한 ARM64 이미지 가용성을 기준으로 Kolla를
  선택했다.
- **Magnum 포함:** standalone CAPO를 선택했으므로 불필요하다.
- **처음부터 HA/Ceph/Octavia 포함:** 첫 scale-up 경로와 무관한 장애 지점과
  resource 요구량을 늘린다.

## 결과

- `bootstrap-servers`, `prechecks`, `pull`, `deploy`, `validate-config`,
  `post-deploy`를 독립 Make target으로 노출한다.
- image pull 문제와 config/service 시작 문제를 분리해서 진단할 수 있다.
- 단일 controller는 의도된 SPOF이며 production HA 설계가 아니다.
- 향후 workload API endpoint나 persistent volume 요구가 생기면 Octavia와
  Cinder를 별도 결정으로 추가해야 한다.

## 재검토 조건

- cloud/bare-metal 프로필에서 다른 Neutron backend가 필요할 때
- Kubernetes HA control plane에 Octavia가 필요할 때
- stateful workload 실험에 Cinder/CSI가 필요할 때
- OpenStack release를 upgrade할 때
