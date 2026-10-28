# S3 본시험 M 정리 중 API 터널 유실과 cleanup-only 복구

`s3-b02-m3600/attempt-01`은 source `f445b9e`에서 2026-10-28 18:07:56 KST에 원래 관측을 끝냈다. 요청 원자료는 예정 900개/관측 900개, 관측 공백 0초를 남겼다. 이는 무효 시도의 설명 자료이며 유효 주분석으로 승격하는 근거로 사용하지 않는다.

S3 소유 fault·namespace·volume·controller 설정을 정리한 뒤 worker를 2대에서 원래 1대로 되돌리는 운영 과정에서 실패했다. worker는 실제 1대로 수렴했지만, 18:13:40 KST의 후속 probe가 workload API `127.0.0.1:16444` 연결 거부로 실패했다. 같은 시각 SSH/IAP 로그에는 Broken pipe/255가 기록됐다. 기존 cleanup watcher가 18:13:49 KST에 터널 복구를 확인했다. 연결 유실의 최초 네트워크 원인은 확정하지 않는다. fault, worker 축소, probe 실행을 자동 재생하지 않았다. canonical PID97877은 실패 진단을 마치고 18:16:43 KST에 자연 종료했으며 다음 case는 시작하지 않았다.

실제 PID 종료·operator flock 해제 이후 단일 operator 잠금 아래 동일 cluster/MD/CA UID와 worker 1대 안정 상태, CA 0/fixed, `manual from=2 target=1 ca_before=0` journal을 확인했다. S3 원실험 상태는 이미 `cleaned`였고 현재 attempt의 environment run과 fresh_attempt 소유권이 일치했다. 기존 worker recovery는 이미 반영된 worker 축소를 재전송하지 않고 journal만 해소했다. 이어 원래 `resume-cleanup --case s3-b02-m3600`을 정확히 한 번 실행해 auto 모드를 복원하고 소유 정리 10항목을 모두 통과했다. 18:22:10 KST에 cleanup-only가 끝났다. 완료된 S3 정리 명령과 worker scale은 재실행하지 않았다.

정식 원판정은 기존 분석기와 cleanup-only 경로가 생성한 그대로 보존한다: `trial_valid=false`, `fault_realized=true`, `impact_realized=true`, `recovered=null`, `safety=true`, `execution=interrupted`, `cleanup=true`, `missing=[execution_interrupted]`. M의 관측창 내 무복구 원자료는 남지만 유효 비교 표본에는 포함하지 않는다. 추가 S3 retry·보충은 승인되지 않았으므로 새 시도를 만들지 않는다. S1 A/S2 P 보충 각1회만 원래 main29 뒤에 수행한다.

이번 복구는 실행 source/profile/정책/분석기 변경 없이 기존 소유 복구 경로를 사용했다. source234와 과학/calibration source6, 기존30봉인, frozen manifest를 검증한다. `next_action=investigate_before_next_case`에 따라 운영 조사·소유 복구·고정 읽기 검증을 마친 후 기존 freeze의 미실행 case부터 이어간다. source가 동일하므로 새 freeze나 준비8 재주입은 하지 않는다. worker ownership/중단 전환 회귀12건을 통과했다. 원래 오류·재연결·cleanup 실패·cleanup-only 이력과 원자료 hash는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s3-cleanup-transport-repair/`에 보존한다.

같은 공유 원장 세션을 유지하고 신규작업146234원·정리 reserve40000원·불확실성20000원 한도를 변경하지 않는다. 중단 중 forecasts는 null이며 재개 후 완료 case를 제외하고 미실행 main8+S1 A/S2 P 보충2+최종 정리만 포함해 다시 계산한다. 이는 실시간 Billing이 아닌 계획 추정이다.
