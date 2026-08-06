# ADR-0007: 자동화 도구의 책임과 실행 위치를 분리한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 완료

## 맥락

macOS host 설정, Lima VM lifecycle, Ubuntu OS 준비, OpenStack service 배포,
tenant resource 생성은 서로 다른 추상화 수준이다. 하나의 거대한 shell 또는
모든 것을 직접 작성한 Ansible role에 넣으면 provider 이식성과 문제 진단이
나빠진다.

## 결정

- **Makefile:** 사람이 사용하는 안정된 command interface와 단계 의존성
- **Shell/Python/Ruby:** macOS, Lima lifecycle, template, route와 glue logic
- **Ansible:** Ubuntu package, swap, host mapping, external network service,
  nested KVM gate
- **Kolla-Ansible:** OpenStack container와 service lifecycle
- **`openstack.cloud`/OpenStack CLI:** project, user, network, image, flavor,
  application credential와 verification VM
- **cloud-init:** OpenStack guest의 최소 bootstrap/probe

macOS working tree를 source of truth로 두고 배포 입력만 controller의
`/opt/openstack-k8s`에 동기화한다. Kolla-Ansible과 OpenStack CLI는 controller의
고정 virtual environment에서 실행한다.

## 검토한 대안

- **모든 작업을 shell로 구현:** idempotency와 상태 표현이 약하다.
- **모든 작업을 custom Ansible role로 구현:** Kolla와 OpenStack SDK가 이미
  제공하는 domain logic을 중복한다.
- **macOS에서 Kolla-Ansible 직접 실행:** ARM/macOS Python 환경과 target
  network 차이에 영향을 받고 controller-local 실행보다 이식성이 낮다.
- **controller를 source of truth로 사용:** 로컬 변경과 배포 상태가 갈라진다.

## 결과

- 각 실패가 host, OS, Kolla, OpenStack resource, guest/network 단계로
  구분된다.
- `ENV=<profile>`을 통해 같은 command contract를 다른 환경에 적용할 수 있다.
- 생성된 inventory, secret, artifact는 source와 분리된다.
- provider별 인프라 생성은 향후 cloud profile에서 Terraform/OpenTofu 등으로
  추가할 수 있지만 아직 결정되지 않았다.

## 재검토 조건

- cloud/bare-metal provisioning 도구가 추가될 때
- Make target 수가 늘어 workflow orchestrator가 필요해질 때
- CI에서 macOS 전용 privileged setup을 분리해야 할 때
