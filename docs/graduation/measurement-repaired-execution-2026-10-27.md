# 계측 수정 cohort 운영 기록

2026-10-27 20:56 KST 새 preparation 준비를 시작했다. 사용자 재개 승인과 profile 해시는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/restart-authorization.json`에 기록한다. 이전 V7의 7 attempt와 HOLD를 보존하고 새 완료 건수에 포함하지 않는다.

단일 실행자는 `evaluation/fresh_release_driver.py`이며 flock으로 중복 실행을 차단한다. 기존 동일 3대만 ensure하고 공유 원장을 사용한다. 150초 read-only cadence 점검은 `evaluation/fresh_cadence.py`가 실험과 동일한 snapshot 메서드로 수행한다. 정리 후 없는 MHC/deployment의 NotFound만 예상 결측으로 분리한다. 나머지 조회 오류나 15초 초과 간격은 주입 전 조사한다. 이 점검은 준비 실험을 대체하지 않는다.

preparation은 S4 on/off, S1 P/V1, S2 P/M, S3 P3600/M3600 순서로 수행한다. main은 모든 preparation go/no-go 충족 후 기존 등록 순서로만 진행한다. 계측 오류는 원판정 보존과 다음 주입 차단 후 조사 상태로 남기고 `fresh_failure_policy.next_action`으로 안전·정리·비용 오류를 구분한다. 시간 목표는 advisory이며 고정된 종료 시각으로 범위를 축소하지 않는다.

기존 정상 보정3+2는 profile에 등록된 원자료 해시와 고정 S1 workload·SLO·baseline 판정 계약을 재사용한다. 이번 계측 변경은 S3/S4 OpenLoopProbe 도착 대기와 S4 snapshot 수집에 해당하며 기존 S1 정상 보정 workload와 원판정에는 영향을 주지 않는다. A DEV는 원 freeze, 증거 해시 및 동일 S1 앱·부하·baseline·분석 코드 해시를 재검증하여 재사용하며 주 분석 표본 수는 0이다. 새 preparation과 main은 동일한 새 source freeze를 요구한다.

초기 추정은 준비 착수 후 첫 main 6~7시간, 전체 28~30시간이다. 전체 37 case와 단일 lifecycle의 보수 계획 추정은 28.82시간, 누적 비용 약139,347원이다. 이는 Billing 실측이 아니며 신규작업 한도146,234원 및 정리reserve40,000원을 유지한다. 기존 불확실성reserve20,000원은 공유 원장에서 단1회만 계산한다.

회귀 6개 통과 및 driver/cadence Python 구문 검증 완료. 실제 cadence 증거와 첫 주입 시각·건수·최종 분석은 새 root에 추가한다.
