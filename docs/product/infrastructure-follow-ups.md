# 인프라 자동 증감 작업의 경계와 후속 항목

현재 작업 순서와 진행 상태는 [인프라 작업 우선순위](infrastructure-priorities.md)에서 관리한다. 아래 내용은 1·2번 구현 당시의 범위 기록으로 유지한다.

- 기록일: 2026-09-11
- 이번 범위: 준비·조회·능동 검사 분리, workload worker Nova VM 1~3 자동 증감, 최소 진단/소유 자원 정리, 로컬 회귀 및 실환경 수동·자동 증감 검증.
- 실환경 수용: [검증 문서](../worker-autoscaling-validation.md)에 미실행 항목을 별도 표시한다.
- 기존 미추적 `test-infra-readiness-review.md`는 변경하지 않았다. 그 문서의 코드 상태는 작성일 2026-09-10 기준이며 이번 구현 후 상태와 구분한다.

| 후속 항목 | 이번에 구현하지 않은 내용 |
|---|---|
| 고객 HTTP 연속성 | 실제 서비스 요청, 오류/timeout 측정, SIGTERM 처리, PDB/replica 설계에 따른 서비스 품질 |
| 성능·비용 | HTTP 부하/실제 CPU 사용량 측정, compute 포화, 고객 비용 추정. worker 3대의 성능 여유는 미검증 |
| HPA·상시 관측 | Metrics Server/HPA, Prometheus 등 상시 수집·대시보드 |
| 장애·복구 | 고객 앱/Ingress/DB 장애 시나리오, worker 자동 복구 또는 MHC |
| 전체 실행 관리 | 분산 lock, 재시작 후 자동 재개, 중복 작업 조정, TTL/보존 정책, 외부 고객 격리 |
| GCP status label 계약 | 첫 기본 프로필 조회가 비었으나 실제 배포는 기존 local.env greenfield 프로필임을 실환경 착수 시 확인. 올바른 override/state에서는 No changes. 기본 프로필 오선택 방지 UX는 별도 작업이며 필터 코드 결함으로 확정하지 않음 |
| host verify gate 통합 | `gcp-host-verify`는 KVM 장치/활성 상태를 검사한다. ADR-0015의 실제 nested kernel boot와 controller→compute SSH는 이번에 별도 실행했다. 이를 단일 host gate로 통합하는 코드는 별도 작업 |
| 기존 이미지 검사 keypair 소유권 | 기존 image guest 검사는 고정 keypair를 사전 삭제한다. 이번 live 실행은 별도 artifact 스크립트에서 고유 이름·기존 자원 존재 시 중단·생성한 자원만 정리하도록 제한했다. 공통 guest 검사의 소유권 개선은 별도 작업 |
| 과거 고정 이름 probe | 소유 label 없는 과거 workload API/CNI probe는 자동 삭제하지 않는다. 소유권을 별도 확인해 운영자가 처리 |

기존 PRD의 R-06/R-07 및 고객 보고 기능이 완료됐다는 의미가 아니다. 인프라
requests 기반 증감 수용과 고객 HTTP 요청의 무중단 처리는 별도의 완료 조건이다.
GCP 호스트 자동 증감, flavor/quota/초과 할당 변경은 이번 작업에 포함하지 않는다.
