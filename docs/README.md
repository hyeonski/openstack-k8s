# 문서 안내

정리 기준: 2026-10-23. 현재 코드·설정과 2026-10-04 마감된 최종 평가 기록을 기준으로
문서를 구분한다. 클라우드의 실시간 상태는 별도 조회가 필요하다.

## 현재 구축·운영·실험

| 문서 | 용도 |
|---|---|
| [프로젝트 README](../README.md) | 전체 구조, 코드 기준, 최초 구축·IaC 채택·운영 경계 |
| [worker와 시험 운영](operations.md) | auto/fixed 제어, 잠금·복원, 실행 취소·재개·정리·상한 |
| [관측 운영](../observability/README.md) | 수집 구조·책임, 배포·조회·증거 반출과 현재 제한 |
| [S1~S4 실험 운영](graduation/experiments.md) | 공통 준비, 기준선·재배치·QoS·DB 복구·VM 교체, 정리·재개 |
| [최종 평가 계약](graduation/final-evaluation.md) | 조건 고정·반복·비교·실패 시험과 독립 검증 |
| [최종 평가 결과](graduation/final-evaluation-results-2026-10-03.md) | 2026-10-04 마감된 34건의 시도·수용 여부·예외·남은 과제 |
| [테스트 보완·새 평가](graduation/retest-2026-10-23.md) | 2026-10-23 검증 보완과 별도 캠페인. 진행·완료 상태는 해당 문서 참조 |
| [평가 설계](graduation/evaluation-design-2026-10-25.md) | 주장·연구 질문(RQ1~RQ6)·지표·분석 방법과 두 축 계획의 대응 |
| [A단계 분석](graduation/analysis-2026-10-25.md) | 기존 원본의 오프라인 재집계. S2 분리만 구간·실효 업로드 처리량, S1·S3·S4 시간 분해, RQ1 계층별 신호, RQ4 결정 행렬·정확 통계, 정적 런북 복잡도, 신청서 대비 달성도 |

운영 가이드는 현재 지원하는 명령을 설명하고, 검증 기록은 해당 날짜의 코드·사양에서
확인한 범위를 설명한다. 기록의 “미검증”을 현재 구현 전체의 미완료로 읽거나,
실험 샘플의 통과를 범용 고객 지원 완료로 확대하지 않는다.

## 설계·제품 범위

| 문서 | 용도·상태 |
|---|---|
| [기반 작업 우선순위](product/infrastructure-priorities.md) | 실험 구현과 고객용 일반화의 진행 상태·운영 후속 과제 |
| [장애 시나리오 정의서](graduation/failure-scenarios.md) | S1~S4 설계 기준선. 실행 파라미터·결과는 별도 계약·검증 문서 참조 |
| [제품 확장 기획](product/plan.md) | 기획·요구사항을 합친 향후 아이디어 기록. 현재 테스트베드의 필수 작업 아님 |

제품 확장 기획은 한 문서에 보관하며, 테스트베드의 운영 과제와 구분한다.

## 기술 결정

[ADR 인덱스](adr/README.md)에서 채택·대체 관계를 확인한다.

- [0013: GCP 단일 실행 환경](adr/0013-use-gcp-as-the-only-runtime.md)
- [0014: controller의 management kind·CAPI](adr/0014-run-management-capi-on-controller.md)
- [0015: 계층별 검증](adr/0015-require-layered-gcp-verification.md)
- [0016: 준비·관측 분리와 worker 자동 증감](adr/0016-separate-observation-and-enable-worker-scale-in.md)
- [0017: 복구 목적지 compute01 증설](adr/0017-increase-recovery-target-compute-capacity.md)

이전 결정과 측정 조건은 새 결정으로 소급 변경하지 않는다.

## 과거 검증·실행 이력

| 기록 | 기준 시점·범위 |
|---|---|
| [초기 GCP 기준선](gcp-validation-baseline.md) | 2026-08-24, 초기 구축·증설 |
| [worker 자동 증감](worker-autoscaling-validation.md) | 2026-09-11, 당시 증감 검증·후속 항목 |
| [관측 최초 배포](../observability/live-validation-2026-09-24.md) | 2026-09-24, 최초 수집 배포 |
| [실행 수명주기 최초 검증](run-lifecycle-validation-2026-09-24.md) | 2026-09-24, 취소·재개·정리 |
| [기반작업 종합 검증](foundation-priority1-final-validation-2026-09-24.md) | 2026-09-24, 제어·관측·수명주기 보완 후 종합 수용 |
| [S1 기준선·경합 검증](graduation/s1-validation-2026-09-26.md) | 2026-09-26, 두 초기 기록 통합 |
| [S4 단계별 검증](graduation/s4-validation-2026-09-26.md) | 2026-09-26, 준비·첫 장애·자동화·통합의 네 기록 통합 |
| [S1~S3 통합 복구 검증](graduation/recovery-validation-2026-10-02.md) | 2026-10-02, 사전 실패와 최종 구성별 검증 |
| [최종 평가 중단·재개 이력](graduation/evaluation-resume-2026-10-03.md) | 2026-10-03 중단 지점과 10-04 마감. 재개 대기 없음 |

검증 원본 `artifacts/`는 Git에서 제외된다. 해당 링크는 로컬 증거가 있는 환경에서만
열리며, 실행 ID·수치·실패·정리 예외는 문서와 함께 보존한다.

## 보고서 실측·그림과 외부 코드 출처

- [S4 동일 코드 재측정](graduation/interim-report/s4-rerun-2026-09-27.md): 중간보고서 표에 사용하는 세 회차의 원본 근거.
- 그림: [시스템 구조](graduation/interim-report/system-architecture.svg), [실행 흐름](graduation/interim-report/execution-flow.svg), [S4 시간선](graduation/interim-report/s4-timeline.svg).
- [Cinder CSI 출처](../kubernetes/graduation-s3/csi/SOURCE.md)와 [라이선스](../kubernetes/graduation-s3/csi/LICENSE).

중간보고서 원고·착수 점검·관련연구 후보와 초기 집필 계획·목차·메모는 삭제했다.
실측 기록·그림·기술 결정은 보존하며, 삭제한 문서의 원문은 Git 이력에서 확인한다.
현재 실행 절차와 판정 기준은 현행 운영 가이드·평가 계약을 따른다.
