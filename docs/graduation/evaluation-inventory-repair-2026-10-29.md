# Inventory 준비 실패 수정 및 재개 검증

2026-10-29 KST. 이 문서는 `3375f90` 이후의 운영 수정과 별도 재개 cohort를 설명한다. 기존 본 실험 first-attempt와 strict 무효 판정을 보존한다.

## 원인과 수정

`workload_state.snapshot()`의 inventory는 7개 종류의 목록, port별 상세, quota/limits를 한 SSH 세션에서 순차 수집한다. 공통 read wrapper가 이 묶음 전체에 개별 명령 상한 20초를 적용한 것이 준비 실패 원인이었다. 실패 당시 16개 호출 묶음의 48개 시도가 모두 timeout이었다. 수정 전 원본을 읽기 전용으로 단독 실행했을 때 45.86999초에 정상 종료됐다.

새 compound 경로는 수집 전체에 기존 작업 예산 90초를 적용하고, 원격 OpenStack CLI 각각에는 20초를 적용한다. 재시도·identity·backoff도 같은 90초에 포함한다. 각 child를 재시도하는 중첩 retry는 없으며, 완성된 JSON만 반환한다. 개별 조회·identity는 기존 20초 제한을 유지하고 baseline/H 및 전체 준비 단계의 원래 제한을 늘리지 않는다. 원격 수집 자체에도 deadline을 두어 연결이 끊겨도 무기한 남지 않는다.

`LiveBackend.cleanup`은 interrupted worker supervisor가 ownership lock을 해제할 때까지 최대 30초 기다린다. 이 시간은 기존 cleanup phase 예산 안에 포함된다. 여전히 다른 owner가 있으면 mutation을 실행하지 않고 실패한다. lock을 강제로 해제하거나 다른 owner의 작업을 취소하지 않는다.

## 검증과 증거 범위

[inventory-repair-v8](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/inventory-repair-v8/)에 테스트, 실제 준비 경로, 원본 보존, 비용, transition 검토를 보존한다. 테스트는 46초 정상 복합 조회, remote child별 20초 제한, shared retry/phase 예산, 실제 별도 프로세스 lock 해제 대기/거부, 재개 범위 및 과학적 소스 변경 거부를 포함한다. 전체 `test_fresh*.py` 197개가 통과했다. 첫 sandbox 실행에서 HTTP 테스트의 localhost bind가 거부된 기록은 별도 보존하고, 동일 테스트를 localhost bind가 가능한 환경에서 통과시켰다.

실제 준비 검증은 새 과학적 attempt를 생성하지 않고 동일 함수 `Campaign.verify_ready_environment`와 `Campaign.prepare_workers`로 auto/1 → fixed/2를 준비한 후 `LiveBackend.cleanup`으로 auto/1을 복원한다. 실제 서비스/VM fault, baseline 부하, H 측정은 실행하지 않는다. 그 상태에서 변경 없는 clock guard의 arm/release도 확인한다. 최종 재검증은 source253에서 준비 434.94초, 전체 691.75초에 통과했다. inventory 완전 수집 5회, worker 2대 준비·배치, 정상 clock release, cleanup, worker auto/1, 동일 identity를 확인했다. scale-down 도중 삭제된 port에 대한 한 snapshot은 NotFound로 거부됐고, 원래 readiness loop가 다음 완전한 snapshot으로 수렴했다. 부분 관측을 채우거나 deadline을 늘리지 않았다. 최종 증거와 소스 SHA는 `readiness.json`, `go-review.json`을 따른다.

첫 실제 준비 검증은 worker 준비를 통과했지만 operator 검증 스크립트가 clock-smoke 증거 폴더를 만들지 않아 arm 기록 저장에 실패했다. 이 스크립트 오류로 lease가 만료되어 owner가 정리 중 종료됐다. 기존 정리 자식이 scale-down을 마친 뒤 ownership을 확인해 `LiveBackend.cleanup`으로 auto/1 복원을 완료했다. 이 실패 자료는 `readiness/`와 `initial-readiness-failure.json`에 보존하고, 폴더 생성을 수정한 전체 검증을 `readiness-final/`에 별도로 수행한다. 실제 평가에서는 이미 생성된 Evidence 디렉터리를 전달하므로 이 오류는 operator 검증 스크립트에 한정된다.

기존 30분 clock qualification과 실제 reboot 증거는 그 당시 동결 소스의 증거로 유지한다. 현 소스가 새 30분 qualification을 실행했다고 주장하지 않는다. clock guard 소스는 동일하며, 새 inventory/cleanup 경로는 별도 현재 소스 검증으로 입증한다. 원래 10,234개 파일과 이번에 닫힌 무효 attempt 21개 파일의 불변도 확인한다.

## 사용자 지시와 남은 범위

사용자는 수정·검증 완료 후 기존 Sol 채팅에 재개를 전달하도록 승인했다. 이어 Astra가 30분마다 진행을 확인하고 운영 문제를 수정·검증·재개하여 평가를 완료하며, 이러한 무효 본 실험은 마지막에 다시 돌리도록 승인했다. 따라서 이전 4개 보충 한도는 현재 확인된 무효 본 실험 8개에 대한 별도 보충으로 확장된다. 유효하지만 미복구인 결과를 성공으로 바꾸려고 반복하지 않는다. 의도된 negative preparation의 무효는 이 보충 범위에 포함하지 않는다.

먼저 `s4-b03-off`, `s4-b03-on`의 원래 first-attempt를 실행한다. 그 뒤 다음 원본의 `-supplement01`을 순서대로 실행한다.

1. `s1-b02-a`
2. `s2-b03-p`
3. `s3-b02-m3600`
4. `s3-b03-m3600`
5. `s3-b03-p3600`
6. `s4-b01-off`
7. `s4-b02-on`
8. `s4-b02-off`

기존 본 실험 27건은 유효19·무효8이며 이전 attempt를 덮어쓰거나 primary에 대체 삽입하지 않는다. 재개는 새 `bed-inventory-v8` cohort와 hash-bound v5 authorization을 사용한다. 정책/H/SLO/load/판정/phase·비용 여유는 유지한다. 이후 운영상 무효는 원인 수정·검증과 새 별도 회차의 source/freeze를 거쳐 관리하며, 이 release가 동일 ID의 무제한 재시도를 자동 허용하지 않는다.

## 실행권과 정기 확인

실험 실행 담당은 Sol 채팅 `01a18317-e6fb-7ef0-8e7e-bb80dd3c5fa5`이며, Astra가 수정·검증을 수행하는 동안 대기한다. 재개 전달 전까지 기존 HOLD/REPAIR 및 active pointer를 유지한다. 인계 시 원문과 SHA를 보존한 뒤 새 authorization으로 해소한다. 단일 driver와 실행권을 유지하고 실행 중 소스를 편집하지 않는다.

기존 heartbeat `automation`을 Astra 채팅 `01a1829e-502e-7792-ab6c-ddbbd3f2fe91`의 30분 진행 점검·복구 일정으로 변경했다. 정상 진행의 반복 확인은 조용히 유지하고 의미 있는 진행·실패·수정·필요 조치·완료에 알린다. 전체 평가와 보충, 최종 분석·보고, 소유 자원 정리, VM 정지·원장 종료, 시각 원설정 복원을 확인한 뒤 일정을 종료한다.

비용은 최신 표시 잔액 136,983원에서 보고 이후 경과 및 앞으로 남은 작업을 추정한다. 과거 원장을 새 잔액에서 중복 차감하지 않는다. 정리 40,000원, 기타 20,000원 및 미확인 청구 지연 12시간의 보수적 가정을 유지한다. 확대된 10건의 초안 추정은 약9.21시간, 이 예비비를 제외한 여유는 점검 당시 약7,678원이며 실측 청구 잔액이 아니다. 매 재개와 정기 확인 시 다시 계산한다. 현금 초과·유료 전환·새 GCP 호스트 VM은 승인되지 않았다.
