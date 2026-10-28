# 읽기 연결 복구 후속 버전과 보충 A 측정

사용자는 S1 `s1-b02-a/attempt-01`의 연결 오류 읽기 재시도 누락 보완과 추가 A 측정 1회를 승인했다. 진행 중인 `s1-b03-p`는 기존 source로 자연 종료·cleanup·독립 판정·증거 봉인까지 유지한다. 기존 단일 driver의 다음 case 진입 gate에 운영 handoff 표식을 등록하며, 관측이나 정리를 중단하거나 별도 클라우드 실험을 실행하지 않는다. 패치와 오프라인 테스트는 `/private/tmp/openstack-k8s-transport-repair-20261028`에서 먼저 준비한다.

`s1-b03-p`는 2026-10-28 10:04:56 KST까지 유효·안전·정리 통과로 봉인됐고 canonical driver는 handoff gate에서 자연 종료했다. `impact_realized=false`도 그대로 보존하므로 정상 유지를 복구 효과와 혼동하지 않는다. 이 경계까지 실제 main 9건은 유효 8건·무효 1건이다. 기존 230개 source와 원자료는 전환 직전에도 동일했다.

S1의 실제 `kubectl wait/get/logs/rollout status` 읽기 경로와 workload Client 읽기에 제한된 transport 래퍼를 적용한다. reset/refused/Broken pipe 등 명시적인 일시 연결 오류만 최대 3회, backoff와 재연결·UID 확인 시간을 합친 원래 단계의 총 deadline 안에서 재시도한다. `kubectl wait --timeout`도 남은 시간으로 줄여서 다시 시작한 대기가 시간을 초기화하지 않게 한다. 기존 preparation/cleanup watcher와 동일한 재연결 flock 및 listener 재확인을 사용한다. 동일 Job UID, 준비 cluster UID 또는 이미 확인한 최종 서비스 Pod UID를 재확인한다. 주입·patch·restart·delete·exec는 반복하지 않는다. 영구 오류·대상 변경·누적 deadline 초과는 종료하며 통신 공백을 보간하지 않는다. 원래 오류와 각 읽기 시도·재연결 로그는 증거에 남긴다.

앱·부하·fault·정책·SLO·H·안정창·표본수·분석기는 변경하지 않는다. `FreshS1.finish`의 읽기 래퍼를 제거하고 `finish_once`를 원래 이름으로 정규화했을 때 전체 scenario 모듈 AST가 기존과 정확히 같아야 한다. 바뀐 mixed source 파일 전체와 새 transport/등록 코드도 후속 freeze의 source hash에 포함한다. 이전 source 검사를 제외하는 allowlist를 사용하지 않는다.

기존 `freeze`는 S1 adapter 파일의 transport 변경도 정책 경계 변경으로 분류하므로, 명시적인 `freeze-transport` 후속 등록 경로를 사용한다. 이 경로는 승인된 전체 새 source map·정확한 diff hash·오프라인 테스트 결과·최소 읽기 검증·이전 frozen manifest 및 모든 봉인 증거를 검증한다. profile은 artifact root만 바꾼다. 기존 preparation 8건은 원래 source/원자료로 독립 판정을 재검산하고 main과 scenario 계약이 같음을 확인한 뒤 재사용한다. prep를 재주입하거나 이전 완료 case를 새 cohort의 완료로 복사하지 않는다. 새 cohort에는 기존 main29 중 미실행 case만 원래 순서로 등록한다. 이전 freeze와 원래 무효 판정·raw는 그대로 남는다.

전환 경계는 `s1-b03-p` 종료 뒤, 다음 `s1-b03-m` 시작 전이다. 최종 보고는 각 arm의 source cohort와 경계를 공개한다. 기존 source의 b03 P와 후속 source의 M/A가 같은 block에 속한다는 사실과 source 전환도 함께 표시한다.

보충 case `s1-b02-a-supplement01`은 원래 main29 순서를 모두 마친 직후에 실행한다. purpose는 `supplemental`, block은 `supplement-b02-a`, 시도 한도는 1회다. 원래 b02 A 첫 시도의 무효를 대체하지 않으며 이후 시점의 A를 원 block과 동시 paired 관측으로 취급하지 않는다. 주 분석은 원래 29개 첫 시도를 유지하고, 보충 결과는 별도로 공개한다. driver 완료 조건은 main29와 추가 A 1회 모두 실제 측정된 뒤 최종 소유 정리·3대 종료·공유 원장 종료로 확장한다.

추가 A는 기존 최대 실측 약 46분에 기반해 20%를 포함한 약 55분, 약 2,450원의 계획 비용을 반영한다. 공유 원장의 신규작업 146,234원·정리 reserve 40,000원·기존 불확실성 20,000원 1회 원칙을 유지한다. 중단 중 예측은 null이며 재개 후 완료 작업을 제외하고 추가 1건을 포함해 갱신한다.

실제 평가와 같은 Python 3.11.16에서 전체 fresh 회귀 125건, 컴파일, 시나리오 AST 동일성, diff 검증을 통과했다. 최소 읽기 확인은 고정 3회 API `/readyz`, cluster/MD UID, Ready worker 1대, 실험 namespace 부재, 기존 GCP 3대 ID·종류·RUNNING의 7개 항목이 모두 통과했다. 이 결과와 새 source 234개, 정확한 변경 9개 파일 diff hash, 기존 frozen manifest·봉인 증거를 `transport-transition-authorization.json`에 묶었다. 실제 원자료를 사용한 전환 사전 감사에서 준비 8건 재사용과 잔여 main 20건·보충 1건을 확인했다. `transport-release-active.json`은 새 profile·승인 hash를 가리키며 기존 단일 heartbeat의 완료 조건도 main29와 보충 1회 모두를 요구하도록 갱신한다.
