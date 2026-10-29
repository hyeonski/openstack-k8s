# 문서 안내

정리 기준: 2026-10-29. 본평가(fresh F-repeated)와 S2 확장 실험이 끝난 상태다. 정리 직전 시점은 git tag `evaluation-final-20261029`에 보존했다. 삭제한 문서의 원문은 이 tag와 Git 이력에서 확인한다. 클라우드의 실시간 상태는 별도로 조회해야 한다.

## 평가 결과 (논문 기준)

| 문서 | 용도 |
|---|---|
| [평가 결과 통합 분석](graduation/evaluation-results-analysis-2026-10-29.md) | **먼저 읽을 문서.** R1~R7 질문별 판정, 시나리오별 case 표, 기술 통계, 논문 문장 가이드, 한계, 후속 실험 |
| [본평가 최종 결과](graduation/fresh-evaluation-final-results-2026-10-29.md) | main29·보충11의 strict 판정·지표, 무효 보존, 사후 측정완전성 감사, 종료 증거 |
| [S2 확장 실험(v13) 결과](graduation/s2-extension-v13-results-2026-10-29.md) | S2 분리만(S) ablation 4건의 실행·판정·종료 기록 |
| [평가 운영·수리 기록 통합본](graduation/archive/evaluation-operations-log-2026-10-27-29.md) | 본평가 중 운영 결정·수리·보충·중단·확장 준비, v12 측정 전 거부 기록을 시간순으로 합친 것 |

## 연구 설계와 평가 하네스

| 문서 | 용도 |
|---|---|
| [장애 시나리오 정의서](graduation/failure-scenarios.md) | S1~S4 설계 기준선 |
| [연구 평가 합의안](graduation/consensus-research-plan-2026-10-26.md) | 주장 등록부(R1~R7)·비교군·통제·계측·통계·한계 |
| [평가 실행 설정](graduation/fresh-execution-settings-2026-10-26.md) | 측정 계약 수치(SLO·H·부하·bin)와 운영 결정 |
| [평가 하네스 구현](graduation/fresh-evaluation-implementation.md) | fresh 하네스의 구조·증거 계약·독립 판정·검증 |
| [평가 체계 구축 상세안](graduation/fresh-evaluation-build-plan-2026-10-26.md) | 파일별 구축 작업·증거 계약·freeze 명세 |
| [평가 실행 상세안](graduation/fresh-evaluation-run-plan-2026-10-26.md) | run 목록·SOP·실패·재실행 규칙 |

### 사전 등록 계약 문서 (경로·내용 고정)

아래 문서는 평가 profile의 `preregistered_documents` 또는 하네스 소스 해시(`evaluation/fresh_campaign.py`, `fresh_calibration.py`, `fresh_identity.py`, `fresh_host_lifetime.py`)가 경로와 내용을 고정한다. 옮기거나 고치면 freeze·검증이 깨지므로 원문 그대로 둔다. 이 문서들이 링크하는 문서도 같은 이유로 제자리에 둔다.

- 실행 계약: [실행 프롬프트](graduation/fresh-evaluation-execution-prompt-2026-10-26.md), [구현 시작 프롬프트](graduation/fresh-evaluation-implementation-prompt-2026-10-26.md), [보정 후 재개](graduation/fresh-evaluation-resume-after-calibration-2026-10-26.md), [실행 검토](graduation/fresh-evaluation-review-2026-10-26.md)
- S1 기준선 보정: [보정 protocol](graduation/s1-baseline-calibration-protocol-2026-10-26.md), [재시도 protocol](graduation/s1-baseline-calibration-retry-protocol-2026-10-26.md), [보정 결과](graduation/s1-baseline-calibration-result-2026-10-26.md), [기준선 수정](graduation/s1-baseline-amendment-2026-10-26.md)
- 운영 수정 계약:
  - [controller 플랫폼](graduation/controller-platform-amendment-2026-10-26.md)
  - [수집 운영](graduation/collection-operations-amendment-2026-10-27.md)
  - [확장 실행](graduation/extended-execution-contract-2026-10-27.md)
  - [S1 image digest](graduation/s1-image-digest-amendment-2026-10-27.md)
  - [호스트 자동 정지 없는 일시정지](graduation/no-host-auto-stop-pause-contract-2026-10-27.md)
  - [계측 수정 후 재시작](graduation/measurement-repair-restart-2026-10-27.md)
- 합의 기록: [연구 평가 합의 토론](graduation/consensus-discussion-2026-10-26/README.md), [실행 설정 토론](graduation/fresh-execution-settings-discussion-2026-10-26/round-03-consensus.md)

## 구축·운영

| 문서 | 용도 |
|---|---|
| [프로젝트 README](../README.md) | 전체 구조, 코드 기준, 최초 구축·IaC 채택·운영 경계 |
| [worker와 시험 운영](operations.md) | auto/fixed 제어, 잠금·복원, 실행 취소·재개·정리·상한 |
| [관측 운영](../observability/README.md) | 수집 구조·책임, 배포·조회·증거 반출과 현재 제한 |
| [S1~S4 실험 운영](graduation/experiments.md) | 공통 준비, 기준선·재배치·QoS·DB 복구·VM 교체, 정리·재개 |
| [기반 작업 우선순위](product/infrastructure-priorities.md) | 실험 구현과 고객용 일반화의 진행 상태·후속 과제 |
| [제품 확장 기획](product/plan.md) | 향후 아이디어 기록. 현재 테스트베드의 필수 작업 아님 |

## 기술 결정

[ADR 인덱스](adr/README.md)에서 채택·대체 관계를 확인한다.

- [0013: GCP 단일 실행 환경](adr/0013-use-gcp-as-the-only-runtime.md)
- [0014: controller의 management kind·CAPI](adr/0014-run-management-capi-on-controller.md)
- [0015: 계층별 검증](adr/0015-require-layered-gcp-verification.md)
- [0016: 준비·관측 분리와 worker 자동 증감](adr/0016-separate-observation-and-enable-worker-scale-in.md)
- [0017: 복구 목적지 compute01 증설](adr/0017-increase-recovery-target-compute-capacity.md)

## 보고서 근거와 외부 코드 출처

- [최종보고서 개요](graduation/final-report-outline.md): 장별 구성, 그림·표 목록. 그림은 모두 새로 그린다
- [S4 동일 코드 재측정](graduation/interim-report/s4-rerun-2026-09-27.md): 중간보고서 표의 원본 근거
- [Cinder CSI 출처](../kubernetes/graduation-s3/csi/SOURCE.md)와 [라이선스](../kubernetes/graduation-s3/csi/LICENSE)

## 보관 (과거 이력)

현재 결과의 근거가 아닌 당시 기록이다. 기존 결과를 새 표본에 합치지 않는다.

| 위치 | 내용 |
|---|---|
| [docs/archive/](archive/) | 인프라 검증 기록: [초기 GCP 기준선](archive/gcp-validation-baseline.md)(08-24), [worker 자동 증감](archive/worker-autoscaling-validation.md)(09-11), [실행 수명주기](archive/run-lifecycle-validation-2026-09-24.md)(09-24), [기반작업 종합 검증](archive/foundation-priority1-final-validation-2026-09-24.md)(09-24) |
| [graduation/archive/first-evaluation-2026-10/](graduation/archive/first-evaluation-2026-10/) | 1차 평가(~10-24): [S1 검증](graduation/archive/first-evaluation-2026-10/s1-validation-2026-09-26.md), [S4 검증](graduation/archive/first-evaluation-2026-10/s4-validation-2026-09-26.md), [S1~S3 복구 검증](graduation/archive/first-evaluation-2026-10/recovery-validation-2026-10-02.md), [평가 계약](graduation/archive/first-evaluation-2026-10/final-evaluation.md), [1차 결과](graduation/archive/first-evaluation-2026-10/final-evaluation-results-2026-10-03.md), [중단·재개](graduation/archive/first-evaluation-2026-10/evaluation-resume-2026-10-03.md), [보완 재시험](graduation/archive/first-evaluation-2026-10/retest-2026-10-23.md) |
| [graduation/archive/superseded-plans/](graduation/archive/superseded-plans/) | 본평가 이전 설계안(10-24~27): 두 축 계획, 평가 설계, A단계 분석, B단계 계획, 완전 평가 원안, 잔여 계획, 실행 검증, DEV 결과, S1 보정 보고 |

검증 원본 `artifacts/`는 Git에서 제외된다. 해당 링크는 로컬 증거가 있는 환경에서만 열린다.
