# S4 첫 off 본시험의 주입 전 OS 시각 보정 무효

`s3-b03-p3600`의 앞선 OS NTP 무효 뒤 새 source234 `7b72f67`로 진행한 `s4-b01-off/attempt-01`은 2026-10-28 19:46:04 KST에 고정 첫 60개 기준선 요청을 시작했다. 19:46:59 KST에 macOS `timed`가 `settimeofday`로 +2.042650342초를 보정했다. 원자료 index53→54의 wall-minus-monotonic 변화 +2.042640448초와 약9.9μs 차이로 일치한다. 주입 전 clock gate가 `baseline_clock_disagreement`, `baseline_unhealthy`를 거부했다. 기준선 세 구간은 각20개이며 마지막 구간 bad6/p95=2322.22985ms, 앞 두 구간 bad0/p95=303.34425/319.04035ms였다. 60개 응답 자체는 모두 ok/correct였다. 이는 시각 영향을 설명하는 원자료이며 정상 기준선이나 유효 결과로 재분류하지 않는다.

장애 주입·MHC fault 변경 전에 중단됐다. 자연 cleanup이 trial namespace 부재·worker1/auto·trial taint 부재의 6항목을 모두 확인했고 19:51:57 KST에 판정·봉인이 끝났다. canonical PID21223과 CLI21237은 자연 종료했으며 단일 operator flock 해제를 실제 확인했다. 원판정은 `trial_valid=false`, `fault_realized=false`, `impact_realized=false`, `recovered=null`, `safety=false`, `execution=interrupted`, `cleanup=true`와 원 missing 목록 그대로다. 자동 분류 `safe_shutdown`은 과학 안전성 실패를 포함하지만, 실제 소유 환경 정리·예산 통과에 근거해 운영 조사 후 미실행 다음 case로 진행하는 판단과 구분한다. 원판정·원자료·표본수를 변경하지 않는다. S4 off 추가 retry 또는 보충은 승인되지 않았으며 생성하지 않는다.

실행 종료 후 실제 같은 cluster/MD UID·worker1/노드 Ready·네 trial namespace 부재·기존3VM ID/type/RUNNING·읽기 IAP의 고정8항목을 독립 재확인했다. 실제 자연 cleanup probe의 `read-guard.json`은 enabled=true, target1, worker FD 상속 및 같은 cluster/MD/CA를 기록했고 mutation 반복·ensure는 false였다. 정상 읽기만 진행돼 `read-attempts.jsonl`은 생성되지 않았다. 이를 실패 기록 누락으로 해석하지 않는다. 완료 cleanup·scale·probe를 재실행하지 않았다. 기존33봉인과 이번1건, 전체34봉인/frozen/raw 및 source234 해시가 그대로다.

추가 읽기 NTP 질의는 두 exchange timeout을 보존하고 최종 +0.012106±0.001949초를 반환했다. 실패 exchange의 offset 필드는 측정값으로 사용하지 않는다. OS 시각 설정·NTP 서비스·UTC 생성·분석기·clock 기준선을 수정하지 않는다. 고정120.463초 wall/monotonic 안정성은 range0.000938892초·인접최대0.000009060초로 한 번 통과했으며 향후 OS 보정 부재를 보장하지 않는다. 이번도 원 clock gate가 무효를 올바르게 차단한 경우라 실행 source 수정·새 freeze·준비8 재주입·회귀 재실행은 하지 않는다. 원 source234에 봉인된188회귀 증거를 유지한다. 조사 중 환경변수 누락으로 첫 읽기 봉인 검증이 중단된 기록도 남기며 고정 환경 경로를 명시해 같은 읽기 검증을 완료했다. 실제 실험 시도는 추가되지 않았다.

같은 profile/승인/freeze와 열린 공유 원장을 유지해 `s4-b01-on`부터 남은 main5만 원순서로 재개한다. 이후 승인된 S1 A→S2 P→S3 b02 M→S3 b03 M 보충 각1회, 총4회를 독립 block에서 측정한다. 첫 main29 및 무효들은 그대로이고 보충을 원 paired block에 대입하지 않는다. 중단 중 forecasts=null이며, 완료 case 제외+남은 main5+보충4+최종 정리25분 단1회를 포함한 19:54 KST 계획은 10월29일03:32/약144075원, 신규146234원 대비 약2159원 여유다. 재개 실측 시각으로 다시 갱신한다. 실시간 Billing이 아니며 정리 reserve40000·불확실성20000·무료체험 현금초과 금지는 유지한다.

조사와 원증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s4-baseline-clock-repair/`에 보존한다. 원무효 총8건(prep2+main6), 과거V7/HOLD 별도와 모든 source 경계·비동시 보충 한계를 최종 보고한다. main29+보충4 실제 측정·최종 분석/보고·소유정리·기존3VM TERMINATED·공유 원장 종료 전 heartbeat를 삭제하지 않는다.
