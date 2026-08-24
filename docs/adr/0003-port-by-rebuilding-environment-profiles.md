# ADR-0003: 환경 이전은 프로필 기반 재구축으로 수행한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: `local-arm64`와 `cloud-gcp-amd64` OpenStack/CAPI/Autoscaler 완료,
  bare-metal 프로필 미구현

## 맥락

개발 순서는 Apple Silicon 로컬 VM, 중첩 가상화를 지원하는 cloud VM,
최종 물리 서버다. CPU architecture, NIC, routing, MTU, storage와 가상화 기능이
다르므로 실행 중인 OpenStack DB와 VM을 그대로 옮기는 접근은 적합하지 않다.

## 결정

환경 간 이동 대상은 실행 상태가 아니라 Git의 자동화와 선언적 설정이다.

```text
local-arm64
  → cloud-amd64
  → baremetal-amd64
```

다음은 공통으로 유지한다.

- controller/network와 compute 역할 모델
- Kolla-Ansible 배포 흐름
- 핵심 OpenStack service scope
- project, image, flavor, network bootstrap 의도
- 단계별 검증 게이트와 증거 수집 방식

다음은 환경 프로필로 분리한다.

- architecture와 이미지
- management cluster의 실행 위치와 lifecycle (`kind`는 `local-arm64`에만 적용)
- host IP, SSH와 provisioning 방식
- NIC 이름, CIDR, route, MTU와 external network 연결
- nested virtualization 설정
- CPU/RAM/disk sizing과 storage backend
- 로컬 호환성 보정

## 검토한 대안

- **VM image나 OpenStack 상태를 통째로 이동:** 환경 차이를 숨기고 재현성을
  입증하지 못한다.
- **모든 환경을 하나의 거대한 조건문으로 처리:** 공통 의도와 provider별
  구현 세부가 섞여 유지보수가 어려워진다.
- **로컬과 최종 환경을 완전히 별도 프로젝트로 구축:** 중복이 커지고 동일한
  검증 계약을 유지하기 어렵다.

## 결과

- `ENV=<profile>`을 Makefile의 공개 선택 인터페이스로 사용한다.
- 로컬 clean-room 성공은 로컬 기능 재현성만 증명하며 cloud/bare-metal
  이식성을 증명하지 않는다.
- ARM64 로컬 측정값은 AMD64 운영 성능 예상치로 사용하지 않는다.
- 현재 external CIDR처럼 호스트 네트워크와 충돌할 수 있는 값은 프로필
  입력으로 취급하고 사전 검사한다.

## 재검토 조건

- cloud 프로필 구현에서 공통 코드보다 provider별 코드가 더 커지는 경우
- 물리 장비의 NIC/VLAN/storage 제약이 현재 역할 모델을 바꾸는 경우
- 실제 상태 migration이 별도 요구사항으로 추가되는 경우
