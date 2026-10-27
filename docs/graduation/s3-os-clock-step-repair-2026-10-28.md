# S3 실제 OS 시계 보정과 명시적 retry

계측 수정 cohort의 S3 P `attempt-01`은 H 내 요청 900건을 모두 수집했고 안전·소유 정리를 통과했지만 `clock_step_between_requests`, `wall_monotonic_duration_disagreement`로 무효 판정됐다. 해당 원판정과 증거 해시를 보존하고 다음 주입을 차단했다. `fresh_failure_policy.next_action`은 `pause_for_measurement_repair`로 분류해 호스트를 일괄 종료하지 않았다.

원자료 index893의 요청은 2026-10-28 01:55:34.546205 KST에 시작해 01:55:37.166613에 완료됐다. wall duration은 2.620408초, monotonic duration은 0.609614초로 차이는 2.010794초였다. 다음 요청의 wall-minus-monotonic offset은 2.010851383초 전진했다.

동일 시각 macOS `timed` 로그는 NTP 응답과 `settimeofday`, `adjust,2.010851145,success,1`을 기록했다. 원자료 변화와 1μs보다 작은 차이로 일치하므로 실제 OS NTP 시계 보정이 직접 원인이다. 이전 조기 요청 대기 오류와 다르며, 도착 대기 코드를 수정한다고 없앨 수 있는 현상이 아니다. OS가 시계를 바로잡은 것이 로그로 확인됐으며, 시스템 시간 설정을 바꾸거나 UTC를 합성하거나 분석 임계값을 완화하지 않았다.

OS 보정 후 읽기 전용 NTP 질의에서 유효 응답 offset -0.001004 ±0.002160초를 확인했다. 다른 endpoint의 timeout은 질의 실패로 보존했다. 고정 120.167초 동안 wall/monotonic을 읽은 결과 offset range는 0.008650초, 인접 최대 변화는 0.000139초였다. 이 점검은 미래 NTP 보정이 없다는 보장이 아니며 원래 시계 유효성 검사는 계속 적용한다.

등록된 `max_attempts=2`와 사용자의 계측 오류 조사·복구·허용 retry 승인에 따라 동일 source/profile의 `attempt-02`를 명시적으로 실행한다. 원 attempt의 실제 장애와 무효 결과는 그대로 보존하고 소급 통과시키지 않는다. 성공할 때까지 반복하는 자동 재생은 없다. 두 번째 attempt도 무효면 추가 자동 retry를 하지 않고 원인과 남은 범위를 다시 조사한다. main의 첫 attempt만 주 분석에 포함하는 원칙은 유지한다.

증거: 새 root의 `s3-clock-step-audit.json`, `s3-system-time-log.txt`, `s3-post-ntp-clock-stability.json`, `s3-readonly-ntp-offset.txt`, `s3-clock-retry-authorization.json`. 실제 단일 실행자는 `resume-s3-clock-retry.py`가 기록한 PID와 flock으로 확인하고, 유효 종료 후 canonical driver를 exec해 나머지 preparation/main을 이어간다. 실험 source 및 profile·H·SLO·안정창·표본 수는 변경하지 않았다.
