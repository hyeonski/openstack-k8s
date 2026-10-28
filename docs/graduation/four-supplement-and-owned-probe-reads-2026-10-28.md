# 보충4회 승인과 worker 축소 후 probe 읽기 보완

사용자는 무효 s3-b02-m3600 및 s3-b03-m3600도 각각 별도 supplemental 정확히1회 측정하도록 추가 승인했다. 기존 S1 A/S2 P 각1회와 합쳐 main29 뒤 순서대로 보충 총4회다. 원래 첫29 주분석과 모든 원무효·raw·판정은 불변이며, 원 block 동시 paired 결과로 대체하거나 성공까지 반복하지 않는다. 각 보충은 독립 block/최대1회이며 네 건 모두 실제 종료하기 전에 완료/down/heartbeat 삭제하지 않는다. 실제 안전·소유권·비용 한도는 계속 지킨다.

승인 수신 당시 source4708e66/PID11319의 s3-b03-p3600이 실행 중이었다. source를 바꾸거나 중단하지 않고 현재 case의 자연 종료·cleanup·판정·봉인 다음 경계에서 멈추는 운영 marker를 예약했다. 추가 작업은 별도 staging에서 준비했다. 이 marker는 새 승인된 handoff이며 완료된 wrapper 재실행을 의미하지 않는다.

원인을 구분한다. b03 M의 고정 binding SSH/IAP 읽기 및 controller 변경 전 정리 검증은4708에서 보완됐다. b02 M은900/900 관측 후 worker 축소 후속 probe의 workload API nodes 읽기 연결 실패를 cleanup-only로 복구한 것이며 당시 재발 방지 source 수정은 없었다. 이번 보완은 이 후속 읽기 경로에 해당한다. 최초 연결 유실의 네트워크 원인은 여전히 미확정이다.

소유 worker 수동 scale의 기존 journal과 상속된 실제 worker lock FD/inode가 있는 probe만 읽기 guard를 사용한다. 고정 workload nodes/readyz, 생성된 동일 probe Pod UID의 상태/events/logs/delete-wait만 원래30초 읽기 상한 및 기존360초 probe 단계 안 최대3회/backoff1,2초로 재조회한다. 기존 watcher/공유 reconnect lock이 연결을 복원하기를 수동으로 기다리며 ensure나 worker scale을 다시 보내지 않는다. 재시도 전/후 journal·kubeconfig SHA·cluster/MD/CA UID·실제 target replica 안정 수렴·CA0을 확인하고, Pod/run/Node UID를 확인한다. 권한/identity 오류와 deadline 초과는 즉시 보존한다. delete-wait 응답 유실은 실제 동일 Pod 이름의 부재부터 읽어 확인하며 delete를 반복하지 않는다. management-plane 읽기는 기존 단일 호출을 유지한다. probe 생성·부하·scale·patch·delete 명령과 실험 정책·앱·SLO/H는 바꾸지 않는다. 정상 읽기 값은 그대로 반환하고 오류·시각·관측 공백을 probe evidence에 남긴다.

보충 등록은 S3 동일 scenario의 두 origin을 명시적으로 구별하고 각각 다른 freeze 경로/독립 block을 사용한다. main29 전 보충 admission을 거부하고, 앞 보충이 봉인되기 전에 뒤 보충을 허용하지 않는다. 네 번째 실제 시도 전 down하지 않으며 supplemental max_attempts=1을 유지한다. 계획 비용이 신규작업 한도를 넘으면 pending 범위를 그대로 두고 fault admission 전에 조사를 위해 멈춘다. 과학적 safety=false이더라도 실제 소유 정리가 검증되고 비용이 충분하면 조사 대기하며 그 값만으로 전체 down하지 않는다. 실제 비용/정리 안전 gate와 원 next_action 분류는 유지한다.

현재 P는 정리10을 모두 통과했으나 clock_step_between_requests로 무효 봉인되고19:23:31KST에 PID11319가 자연 종료했다. raw index914→915의 wall-minus-monotonic 변화는+3.980372초였고,19:15:01KST macOS timed의 settimeofday adjust+3.980385065초와 약13μs 차이로 일치한다. 관측 전18:58:59KST에는-3.951622128초 보정도 있었다. 원판정 valid=false/fault·impact=true/recovered=null/safety=true/cleanup=true/missing=[clock_step_between_requests]를 보존하며 P 재측정은 추가 승인되지 않았다. 시스템 시각·설정·분석 임계값·UTC 생성은 바꾸지 않았다. 읽기 전용 NTP는+0.047248±0.002284초,120.870초 wall/monotonic 점검의 offset range0.000934초·인접최대0.000008822초였다. 이후 보정이 없다는 보장은 아니며 원 clock 유효성 gate를 계속 적용한다.

경계의 원 봉인은 총33=prep10(유효8/무효2)+main23(유효18/무효5), 보충0이다. 원무효 총7건 및 과거V7의 별도 무효/HOLD를 모두 공개한다. 현재 원자료/frozen hash를 보존한 뒤 수정6파일, 전체source234와 최초230 대비 정확14파일 diff·영향·AST를 새 freeze에 묶는다. 과학/calibration source6·분석기·앱·fault·정책·부하·SLO/H·안정창·표본수는 원 SHA/계약 그대로다. 원 준비8은 원판정 재계산·계약·AST·회귀·hash로 재사용하며 재주입하지 않는다. source exemption이나 옛 manifest 변경은 없다. 미실행 main6만 원순서로 남고 이후 보충4회를 실행한다.

추가 S3 각 약48분(실측 최대와 정리복구 포함 duration x1.2), 전환15분과 기존 최종정리25분을 단1회 포함한 잠정 계획은10월29일04:09:37KST·약145748원이었다. 신규146234원 대비 여유약486원으로 좁아 조기 알렸다. 실제 경계·전환 뒤 완료작업을 제외해 다시 갱신한다. 이는 실시간Billing이 아닌 계획 추정이다. 같은 열린 공유원장을 유지하고 정리reserve40000원·불확실성20000원은 단1회이며 무료체험 현금초과 금지를 지킨다. 초과 예상 시 부족액과 선택지를 보고하고 범위를 임의 삭제하지 않는다. 중단 중 forecasts=null이다.

검증은 staging/실제 fresh 및 worker/probe 회귀188건, 최소읽기8, clock 안정성, source234/기존33봉인/원 calibration binding·시나리오/helper/probe AST에 결합한다. 근거는 artifacts/fresh-evaluation-measurement-repaired-2026-10-27/four-supplement-cleanup-read-repair/에 둔다. 모든 원무효·source 경계·후속 보충의 비동시성·clock 한계를 최종 분석에 공개한다.
