# S1 main API 터널 연결 유실과 소유 정리

계측 수정 cohort의 `s1-b02-a/attempt-01`은 2026-10-28 07:37:19 KST에 loadgen Job 완료를 읽는 과정에서 실패했다. `kubectl wait`는 로컬 `127.0.0.1:16444` 연결 거부와 앞선 연결 reset을 보고했다. 원래 터널 로그에는 `Failed to send all data from [stdin]`, 원격 연결 종료, `Broken pipe`, SSH 종료 코드 255가 남아 있다. SSH/IAP 연결이 끊긴 직접 증거이며, 연결을 끊은 최초 네트워크 원인까지 확정한 것은 아니다.

이 시도는 이미 등록된 A 조치와 관측을 수행한 뒤였다. 실패한 Job 대기 명령, A 조치, 장애 주입을 다시 실행하지 않았다. 즉시 정리에서도 같은 터널 연결 거부로 Job 제거가 실패했고, runner는 `CLEANUP_FAILED`로 다음 case를 차단했다. 경쟁 VM 제거는 완료됐으나 전체 소유 정리 검증 전이므로 driver는 전체 down을 수행하지 않고 종료했다.

기존 cleanup transport watcher가 07:37:37 KST에 터널을 재연결했다. 이후 운영 점검에서 API `/readyz` 응답이 `ok`이고 원래 Job이 남아 있음을 확인했다. 단일 operator flock 아래 `resume-cleanup --case s1-b02-a`만 실행해 원래 Job의 가용 증거를 보존하고 소유 자원을 정리했다. 07:47:05 KST에 실험 namespace 4개 부재, worker 1대·auto, trial taint 부재, 경쟁 VM·flavor 부재의 8개 정리 검증이 모두 통과했다. 중단 중 완료 예측은 null로 기록했으며 공유 원장의 기존 세션은 계속 비용을 누적했다.

독립 분석은 이 첫 시도를 `trial_valid=false`, `execution=interrupted`, `recovered=null`, `safety=false`, `cleanup=true`로 봉인했다. 누락은 `execution_interrupted`, `request_arrivals_incomplete`, `s1_total_request_indexes`, `scenario_evidence_missing:'service_after'`다. 과학적 안전 확인용 시나리오 checks가 비어 있어 자동 `next_action`은 `safe_shutdown`을 반환한다. 이를 숨기거나 안전 판정을 true로 바꾸지 않았다. 운영 조사에서는 현재 소유 상태에 대한 별도 8개 정리 검증과 고정 3회 API 검사가 모두 통과하고 실제 위험 자원·미해결 소유권이 없음을 확인했다. 실제 안전·소유권 문제일 때 안전 처리하고 관측 유실만으로 무조건 전체 down하지 말라는 승인에 따라, 과학적 무효·false/null 필드를 보존하고 다음 등록 case로 진행한다. 이 판단과 자동 분류의 차이를 `s1-api-tunnel-repair-resolution.json`에 명시했다.

이 main case의 첫 시도는 원래 관측 유실을 포함한 판정을 그대로 주 분석에 남긴다. 두 번째 시도를 만들거나 첫 시도를 소급 통과시키지 않는다. 재개 전 source 230개 동일성, 현재 봉인된 전체 16개 attempt의 증거 해시, 원래 실패 `run.log` 보존을 확인했다. source/profile·판정 기준을 수정하지 않았으므로 새 source freeze가 필요하지 않으며 기존 freeze를 그대로 검증한다. 다음 등록 case는 `s1-b02-p`다. 앱, SLO, H, 안정창, 표본수와 source를 변경하지 않는다.

운영 증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`의 `s1-api-tunnel-*`에 기록한다. 실패 당시 터널 로그는 원래 attempt의 `cleanup-transport/transport-before-repair-1.log`, 실행 오류는 `run.log`, 최초 정리 오류는 `cleanup-error-*.json`에 보존한다. 정리 전 파일 해시는 별도 운영 감사에 기록하고 기존 완료 main 5건의 봉인 증거는 변경하지 않는다.
