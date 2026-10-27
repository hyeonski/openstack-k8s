# 측정 오류 수정 및 새 실행 인계

## 승인과 범위

사용자는 2026-10-27에 원인 및 관련 오류를 수정한 뒤 새 GPT 6.1 Sol 세션에서 측정을 다시 시작하고, 시간 예산 때문에 줄이지 말고 계획된 전체 실험을 수행하라고 승인했다. 10/29 08시, 24시간, 누적 44/48시간은 중단 조건이 아니다. 기존 크레딧·비용·정리 reserve와 안전 조건은 유지한다. 과거 13:30/17:30 대기 지시는 만료됐다.

현재 공유 인프라는 정지 상태다. 기존 실행 세션은 `01a178fd-a8c2-7280-9e62-cf0a877c0c1f`, 종료 root는 `artifacts/fresh-evaluation-24h-2026-10-27/pause-cost-bounded-v7`다. 해당 root와 HOLD, frozen manifest, 원자료, 무효 판정을 수정하지 않는다. 기존 heartbeat `8-29`는 삭제됐다. 새 세션만 실행자이며 단일 driver와 단일 heartbeat를 소유한다.

새 root는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27`를 사용한다. V7 profile `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261027-pause-cost-bounded-v7.json`에서 새 운영 경로와 승인 기록을 만들되, workload·fault·SLO·H·안정창·표본 수·정책·main 순서는 유지한다. 새 root 안에서는 **S4 on/off 사전 실험을 먼저**, 이어 S1 P/V1, S2 P/M, S3 P3600/M3600을 수행한다. 각 scenario 내 순서와 main 등록 순서는 유지한다. 전체 8건의 새 preparation이 충족되면 main29를 수행한다. 새 측정 코드와 동일한 freeze로 검증하기 위해 이전 유효 6건을 새 preparation 완료 건수로 복사하지 않는다. 정상 보정3+2 및 A DEV는 기존 영향 검토 방식으로 재사용하며 무조건 반복하지 않는다.

이는 이전 실패를 성공으로 교체하는 재시도가 아니라, 공개된 계측 수정 후 새 cohort다. 이전 유효6/무효1 결과를 모두 공개하고 새 main은 각 case 첫 attempt만 주 분석에 포함한다. 성공할 때까지 부하/기준을 조정하거나 재실행하지 않는다.

## 확정한 원인과 수정

1. OpenLoopProbe는 UTC anchor로 도착 예정 시각을 고정하지만 monotonic만 기다렸다. S4 H내1200건 중718건이 UTC상 1ms 이상 일찍 시작했고 최대20.057ms였다. monotonic에서는 모두 정상 순서였다. 미래 요청은 UTC와 monotonic 예약 시각을 모두 만족한 후 실행한다. 종료도 두 시계의 H 경계를 충족하도록 S3/S4 sampler에 until_utc를 기록한다. 기존 분석기의1ms검사·원자료·SLO는 변경하지 않았다.
2. S4 snapshot은8개 Kubernetes 조회와Nova 조회를 직렬로 수행한 뒤 매번 probe 확인과 물리배치 binding을 다시 조회하고5초를 더 쉬었다. 관측47건의 간격 중앙값30.033초, 최대31.272초였다. 판정기는15초 이하 간격과120초 정상 유지를 요구해 계속 streak가 초기화됐다. 약224초부터 종료까지33개 snapshot의 개별 capacity는 recovered였다. FreshS4Run에서 독립 조회를 최대6개 병렬화하고 각 조회의 시작/종료/소요를 보존한다. binding/probe 생성은 교체node별1회 수행하고, 매 snapshot의 실제 Machine/Node/VM/Pod 상태로 연속 검증한다. 최종 capacity_probe는 캐시한 생성 직후 Pending 값이 아닌 최신 snapshot의 Pod를 사용한다. 반복주기는 수집 시간을 포함한5초 목표다. 기존15초/120초 판정은 변경하지 않았다.
3. 오류 분류 helper `evaluation/fresh_failure_policy.py`를 추가했다. 새 운영 driver는 `next_action`을 실제 사용해야 한다. 정리 검증된 측정 오류는 `pause_for_measurement_repair`로 기록하고, 해당 case 이후 새 주입을 막으며 에이전트가 수정·재개를 이어간다. 오류 하나로 무조건 전체 down·heartbeat 삭제·작업 종료하지 않는다. 정리 불명은 소유 정리를 해결하고, 실제 비용 부족·안전 실패는 안전 종료한다. 유효한 미복구는 결과로 남긴다. 대기 비용도 원장에 반영하고 방치하지 않는다. 원판정 승격이나 장애 재주입의 자동 재생은 없다.

S2는 현 부하/SLO를 유지한다. P에서 약101→396~472→105~140ms, M에서 최대 구간p95510ms·2개 불건강bin이 관측됐다. 기준 근접 미달만으로 새 no-go/보정 반복을 만들지 않는다. recovered=true/0의 정상 유지와 장애 복구 효과는 구분하고 업로드 처리량 감소를 함께 보고한다.

## 검증 완료 및 남은 실제 확인

- fresh 관련103개: 첫 실행의 로컬 HTTP socket 권한 오류1개를 제외한102개 통과. 해당 calibration suite10개는 sandbox 외부에서 재실행하여 모두 통과했다. 따라서 전체103개 항목을 검증했다.
- S4 관련29개 테스트 통과. 새6개 회귀는20ms UTC slew, 이른 wake, 두시계 종료경계, 병렬조회/오류기록, node별 binding1회, 측정/안전/비용 오류 분리를 포함한다.
- 기존7개 봉인된 attempt의 전체 증거 해시와 유효성/안전/정리/복구/누락 판정을 읽기 전용 재검증해 동일함을 확인했다. 원자료를 재작성하지 않았다.
- 실제 GCP에서 병렬조회 cadence를 측정한 것은 아직 아니다. 새 세션은 ensure 후 S4 주입 전에 읽기 전용 snapshot을 약2~3분 수집해 실제 간격·각 API 소요를 확인한다. 15초 조건을 만족하지 못하면 병목 API만 조사·보완하고 source를 다시 freeze한다. 반복 점검은 원인 없는 무한 반복으로 하지 않는다. 테스트를 줄이거나 관측 누락을 나중 값으로 채우지 않는다.
- 샘플링 시계 테스트는 가상 slew 및 실제 짧은 sampler로 확인했으며, S4 pilot의 전체 H에서 실제 안정성도 확인한다. cadence 점검은 새로운 장애주입이나 과거 pilot 대체 자료가 아니다.

## 새 세션 실행 절차

1. git status, 기존 driver/자식 프로세스·잠금·자동화 부재, 환경 stopped/정리 검증, 원장 열린 session 부재를 확인한다. 다른 프로세스가 있으면 중복 시작하지 않는다.
2. 새 profile/root/승인·진행 원장과 driver를 생성한다. 위 source 및 영향 분석을 새 frozen manifest에 보존한다. 기존 V7 driver의 역사 검증과 운영 흐름은 참고하되 V7 경로/HOLD/고정 pause/이전 source SHA를 기계적으로 복사하지 않는다. old HOLD를 삭제하지 않고 새 세션 승인으로 새 root에서 시작한다.
3. `fresh_failure_policy.next_action`에 따른 운영 오류 경로를 새 driver에 연결한다. current_case, attempted/valid/invalid counts를 구분하고 종료한 프로세스의 stale PID나 과거 완료 예상치를 진행 상태처럼 보고하지 않는다. 본시험 예상은 실행이 중단됐으면 null 또는 blocked로 표시한다.
4. 기존3대만 ensure한다. 자동정지 해제 상태 유지, 사양/ID 유지, 추가 프로젝트/유료전환/현금초과 지출 없음. 원장 전체 누적 비용을 계속 사용한다. 기존 20,000원 불확실성 reserve를 다시 더하지 않는다.
5. S4 cadence를 확인하고 필요하면 최소 수정·검증·commit 후 새 source를 freeze한다. S4 on/off → S1 P/V1 → S2 P/M → S3 P/M 준비를 수행한다. 정상 진행 중 코드/profile을 수정하지 않는다.
6. 8 preparation 검증 후 등록 main29 수행: S1 P/M/A 각3+V1 2, S2 P/M 각3, S3 P/M 각3, S4 on/off 각3. 무개입 미복구는 실패한 실험이 아니다. 과거 main 결과로 보충하거나 표본 수를 줄이지 않는다.
7. 원자료 기반 분석, paired raw 차이/중앙값/범위, API·upload tradeoff, S3 timer/H 한계, S4 기존 MHC 복구 역할을 정직하게 보고한다. 최종 소유 정리·호스트 종료·원장 종료 후 heartbeat 삭제. 한국어 커밋 제목 + 변경 bullet + 검증 본문 컨벤션을 따른다.

실제 실행을 담당할 GPT 6.1 Sol 세션은 작업계획 작성으로 멈추지 말고 이 절차를 수행하고 단일 heartbeat로 완료까지 이어간다. 일시 읽기/연결 오류는 해당 단계에서 bounded retry, mutation 응답 유실은 실제 적용 상태 조회 후 처리한다. 새 사용자 승인을 다시 요구할 필요 없이 이미 승인된 수정·기동·실험·정리를 수행한다.

## 예상 산정

기존 실제case시간은 S1약44분, S2약37분, S3약32분, S4약37분이다. preparation8건은 약300분이며20% 여유와 기동/초기확인을 더하면 약6~7시간이다. main29건은 약1120분이며20% 여유 포함 약22~23시간이다. 따라서 새 실행 준비 착수로부터 첫main약6~7시간, 전체종료약28~30시간을 초기 보수 추정으로 삼는다. S4 최적화 효과를 미리 시간 절감으로 계산하지 않는다. 관측한 실측으로 매 case 후 갱신하되 완료 작업을 남은시간에 다시 더하지 않는다. 시간 목표는 admission hard gate가 아니다.

기존 원장 약62,258원에28~30시간의 계획가동비를 더하면 대략13.7만~14.2만원 범위다. 실시간 Billing이 아닌 기존 단가 기반 계획 추정이다. 신규작업146,234원 한도와 정리40,000원 reserve는 유지하며, 실제 예상이 비용한도에 접근하면 남은범위·필요비용을 사용자에게 조기에 알린다. 비용한도를 임의 해제하거나 성공하지 못한 실험을 숨겨 맞추지 않는다.
