# 연결 읽기 복원과 추가 A 1회: source 전환

사용자는 연결 오류 읽기 재시도 보완과 무효 `s1-b02-a`의 추가 측정 1회를 승인하면서 진행 중인 실험 중단을 금지했다. `s1-b03-p`는 기존 source에서 자연 종료·정리·독립 판정·봉인을 마쳤으며, 2026-10-28 10:04:56 KST에 canonical driver가 다음 case 전 운영 handoff 지점에서 종료했다. 유효·안전·정리 통과 및 `impact_realized=false`를 모두 보존한다.

경계까지 preparation 10 attempt는 유효 8/무효 2, main 첫 attempt 9건은 유효 8/무효 1이다. 기존 230개 source와 모든 봉인 증거 hash는 동일하며 원판정 승격·원자료 보완·이전 결과 복사는 없다. 새 cohort는 미실행 main 20건을 원순서대로 실행하고, original main29가 모두 봉인된 뒤 `s1-b02-a-supplement01`을 별도 purpose/block에서 정확히 한 번 시도한다. 추가 A는 주분석 첫 29건이나 과거 동시 paired block을 대체하지 않는다.

허용된 kubectl wait/get/logs/rollout status의 일시 연결 오류만 최대 3회 읽기 재시도한다. reconnect·동일 Job UID 전후 확인·backoff·실제 명령이 원래 단일 누적 deadline을 공유한다. UID 변경, 영구 오류, deadline 실패와 관측 공백은 보존하고 mutation/fault/restart/delete를 재생하지 않는다. 기존 watcher와 읽기 복구는 live helper의 정확한 로컬 tunnel ensure 호출에 같은 단일 flock을 사용한다. 기존 calibration 파일은 원본 SHA로 유지한다. calibration/DEV의 앱·부하·분석·기준·계측 source 6개 binding을 모두 그대로 통과한다.

초기 미실행 승인 초안 15479fb/8d71078과 시작 전 검증 실패를 보존했다. 과거 calibration binding을 우회하는 방법 대신 실행 helper에서 reconnect를 조정하도록 확정했다. 전체 source 234개를 새로 동결하며 변경 9파일의 정확한 diff hash, 테스트, 최소 읽기 확인, 기존 frozen manifest와 준비 8건 재판정을 명시적 승인에 결합한다. source exemption은 없다. 프로필은 새 artifact_root 외에는 동일하며 workload·SG·H/SLO·안정창·표본수·분석 기준을 변경하지 않는다.

production Python 3.11.16 fresh 회귀 128건, 컴파일, 시나리오와 live adapter AST, 과거 calibration/DEV source 동일성, diff 검사를 통과했다. localhost 서버 바인딩이 sandbox에서 거부된 검사도 별도 보존한 뒤 같은 source/검사를 허용 환경에서 통과했다. 최소 읽기 확인은 고정 3회 API readyz, cluster/MD UID, Ready worker 1대, 실험 namespace 부재, 기존 GCP3 ID·종류·RUNNING의 7항목을 통과했다.

승인은 `transport-transition-authorization.json`, 원증거 전환 감사는 `transport-transition-final-audit.json`, 최소 확인과 테스트는 `transport-repair-minimal-readback.json`/`transport-repair-tests.json`에 기록한다. `transport-release-active.json`은 새 profile·승인 hash를 고정한다. 기존 단일 heartbeat의 완료 조건은 original main29, 추가 A 실제 1회, 최종 원자료 분석·소유정리·기존 3대 TERMINATED·공유 원장 종료 검증 모두다.

추가 A는 기존 최대 실측 약 46분에 20%를 포함한 약 55분·약 2,450원의 계획 비용을 반영한다. 신규작업 146,234원·정리 reserve 40,000원·기존 불확실성 20,000원 단1회 원칙을 유지한다. 중단 예측은 null, 재개 예측은 완료 작업을 제외하고 보충 1건을 포함한다. 부족 예상은 조기 알린다.
