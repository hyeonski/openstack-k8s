# ADR-0001: scale-up 기준선을 중심으로 프로젝트를 단계화한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: M0 및 M1 완료

## 맥락

최종 목표는 OpenStack VM으로 구성된 Kubernetes cluster에서 worker node를
필요에 따라 추가하고, 여유가 생기면 반환할 수 있는 node-level autoscaling을
검증하는 것이다. 단순 도구 설치만으로 끝나면 졸업 프로젝트의 독자적인
기여가 약할 수 있으므로, 기준 시스템을 먼저 완성한 뒤 실제 병목이나 실패를
측정해 연구 주제를 정해야 한다.

OpenStack, Kubernetes lifecycle, autoscaling을 한 번에 구축하면 장애가 어느
계층에서 발생했는지 구분하기 어렵다.

## 결정

프로젝트를 다음 게이트로 나눈다.

1. **M0 OpenStack 기반:** controller/compute 구축, Nova/Neutron 게스트 검증,
   CAPO에 필요한 API 네트워크 경로 검증
2. **M1 Kubernetes 기반:** Kubernetes용 Glance 이미지와 별도 management
   cluster 준비
3. **M2 선언적 machine lifecycle:** CAPO workload cluster 생성과
   `MachineDeployment` 수동 1→2 증설
4. **M3 자동 scale-up:** Unschedulable Pending Pod를 Cluster Autoscaler가
   감지하고 worker VM을 추가
5. **M4 선택 확장:** scale-down 또는 장애·지연·flavor 정책 연구
6. **M5 이식성:** 클라우드 AMD64와 물리 AMD64 프로필 구축

각 마일스톤은 바로 다음 자동화 계층을 붙이기 전에 독립적으로 검증한다.
M3의 첫 실험에는 HPA를 포함하지 않는다.

## 검토한 대안

- **전체 스택을 한 번에 구축:** 빠르게 최종 모양을 볼 수 있지만 실패 지점과
  성능 병목을 분리하기 어렵다.
- **autoscaler 전체를 직접 개발:** 연구량은 많지만 Cluster Autoscaler와
  Cluster API의 예외 처리를 다시 구현해야 하므로 기준선 구축에 부적합하다.
- **설치 자동화만 최종 목표로 설정:** 실무형 결과는 되지만 연구 질문과 비교
  실험이 부족할 수 있다.

## 결과

- M0는 clean-room 재구축, 실제 게스트, 정지 후 재기동까지 통과했다.
- M1의 ARM64 Kubernetes 이미지 빌드, Glance 업로드, Nova 부팅·재부팅
  게이트와 별도 로컬 kind management cluster 생성·OpenStack API 경로 검증을
  통과했다.
- scale-down은 M3 성공 전까지 필수 범위가 아니다.
- 후속 연구 주제는 실제 M3 계측 결과를 보고 선택한다.
- 로컬 환경의 시간 측정은 성능 결론으로 사용하지 않는다.

## 재검토 조건

- CAPO가 로컬 ARM64 OpenStack에서 workload cluster를 만들지 못하는 경우
- M3 기준선만으로도 충분한 프로젝트 기여가 된다고 평가되는 경우
- 일정상 M4를 수행할 수 없는 경우
