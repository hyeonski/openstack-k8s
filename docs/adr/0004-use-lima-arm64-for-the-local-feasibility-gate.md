# ADR-0004: 로컬 기능 게이트는 Lima 기반 ARM64 2노드 환경으로 구성한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 및 clean-room 검증 완료

## 맥락

AWS/GCP 비용을 사용하기 전에 macOS Apple Silicon 한 대에서 controller와
compute 분리, Kolla multinode 배포, 중첩 게스트 부팅을 검증해야 했다.
호스트는 16 GiB RAM으로 제한돼 있고 최종 환경은 AMD64일 가능성이 높다.

## 결정

- Lima를 로컬 VM lifecycle 도구로 사용한다.
- Apple Virtualization Framework(`vz`)와 Ubuntu 24.04 ARM64 guest를 사용한다.
- `socket_vmnet` shared named network로 두 VM을 동일 관리망에 연결한다.
- controller는 control/network 역할, compute는 compute 역할만 담당한다.
- compute에는 nested virtualization을 켜고 `/dev/kvm`과 실제 kernel boot를
  필수 gate로 검사한다.
- QEMU/TCG fallback은 제공하지 않는다.
- resource는 controller 4 vCPU/8 GiB/80 GiB, compute 4 vCPU/5 GiB/80 GiB,
  각 guest swap 2 GiB로 제한한다.

## 검토한 대안

- **UTM:** 대화형 GUI와 수동 운영에는 편하지만 이 프로젝트의 선언적 CLI
  lifecycle과 재생성 흐름에는 Lima가 더 직접적이다.
- **Tart:** Apple Silicon image/CI workflow에 강점이 있지만 일반 Linux VM
  정의와 네트워크 자동화는 Lima가 현재 요구에 더 잘 맞았다.
- **VirtualBox:** 널리 알려져 있지만 Apple Silicon과 필요한 중첩 가상화
  경로를 기준으로 선택하지 않았다.
- **all-in-one OpenStack:** 자원은 절약하지만 controller/compute 분리와
  이후 이식성 검증이 약해진다.
- **QEMU TCG:** 기능상 fallback이 가능해도 속도와 동작 차이가 커서
  autoscaling 기반 검증에 잘못된 신호를 줄 수 있다.

## 결과

- 로컬 환경은 기능 feasibility gate이며 성능 실험 환경이 아니다.
- macOS memory pressure나 swap 영향이 크면 지연시간 데이터는 폐기한다.
- `local-create`, `local-up`, `local-down`, `local-destroy`가 정확한 두 VM만
  관리한다.
- 정지 후 `local-up`은 양방향 관리망과 배포된 OpenStack readiness까지
  확인한다.

## 재검토 조건

- Lima/VZ가 Kubernetes workload VM에 필요한 nested KVM 기능을 제공하지 못할 때
- 로컬 메모리가 M1~M3 실행에 부족할 때
- cloud AMD64 환경이 더 빠르고 저렴한 반복 검증 경로가 될 때
