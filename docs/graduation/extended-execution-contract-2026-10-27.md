# 기한 연장 후 실제 평가 실행 계약 — 2026-10-27

사용자는 수집 보완·74개 검증 통과와 잔여32시간23분 추정, preparation0/8·main0/29를 보고받은 뒤 **“네 괜찮으니 시작하세요”**라고 답했다. 이는 전체8+29개를 유지하면서 원래 한도인 **2026-10-29 00:00 KST**까지 기한을 연장하고 시작하라는 승인이다. 승인 수신 후 기록 시각은2026-10-27 08:02:30 KST다. 과거 HOLD·첫24시간 목표와 미달 사실은 보존하며24시간 시계를 재시작하거나 달성으로 표시하지 않는다.

source는 수집 보완 `4c2dc22`와 이 계약을 추가하는 후속 문서 commit이다. 정상 측정 여섯 파일·정책·SLO·H·stream·표본 수는 유지한다. 수집은 [원격 자료 수집 amendment](collection-operations-amendment-2026-10-27.md)를 동일하게 적용한다. 기존 정상3회+validation2회와 유효 A DEV는 재사용하며 반복하지 않는다. DEV의 원래 frozen source/profile 및 sealed evidence hash를 검증하고, SHA가 같은 분석기로 기존 raw를 독립 판정하여 새 운영 원장에 검토 결과를 남긴다. 기존 report나 원시도를 수정하지 않는다.

새 immutable profile은 `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261027-collection-v4.json`, 새 실행 root는 `artifacts/fresh-evaluation-24h-2026-10-27/`다. V3와 예전 driver는 실행하지 않는다. 새 driver는 새 승인 파일·기존 HOLD SHA·profile SHA를 확인하고 단일 배타 잠금을 가진다. 복수 driver 실행 및 불확실한 action 재시도는 금지한다.

## 동결 운영값

- preparation8개는 S1 P/V1 → S2 P/M → S3 P3600/M3600 → S4 on/off 순서다. 전부 독립 판정한 뒤 공통 go/no-go를 적용한다. 유효한 P/on 미회복 또는 V1 조건 미성립은 no-go이며 성공할 때까지 반복하지 않는다.
- main29개는 사전 고정한 S1 11개(S1 SESSION-A/B 경계 유지), S2/S3/S4 각6개 순서다. first-attempt-only를 지키고 실패·무효·무효과를 보존한다. 실제 안전·ownership 문제가 생기면 다음 case를 막고 정리한다.
- 같은 bed에서는 한 case만 실행한다. 기존 auto/1→fixed/2→필요한 배치 확인→auto/1 cleanup을 유지한다. 검증되지 않은 worker 재사용을 적용하지 않는다.
- S1/V1 모두 nominal45분, S2 38분, S3 35분, S4 25분을 사용한다. case 합1369분×1.2+6운영묶음×50분=1942.8분이다. 이 추정과 관측된 최대 case시간×1.2 중 큰 값을 잔여 case에 적용한다. 완료한 case·calibration·DEV를 미래 작업에 다시 합산하지 않는다. 예비50분을 실제 기동/정리 비용과 중복 가산하지 않는다.
- 기동 전에 전체 잔여 범위가 달력·누적 가동·비용 gate를 통과해야 한다. 각 case 뒤 실측을 반영해 다시 계산한다. 시간표가 벗어나면 조기에 통지하고 안전 정지하며 임의 축소/초과를 하지 않는다.
- cold ensure3600초, fixture1800초, adapter5400초, cleanup1800초, host down1800초, host headroom10800초의 기존 상한을 유지한다. 예상시간을 상한으로 오해하거나 상한을 줄여 진입시키지 않는다.
- 기존10시간 host 수명과 case당3시간 안전 예약을 유지한다. preparation 중 수명 부족 또는 main의 시나리오·S1 block 경계에서는 명시적 down→ensure로 회전한다. controller는 동일E2 ID/type+실제x86_64·Intel/AMD 모델 기록, N2 두 compute는 등록 ID/type/플랫폼을 정확히 확인한다. 원하는 플랫폼을 고르는 재기동은 금지한다.
- case 시작은10/28 21:00 KST 이전, 주입은22:00 이전, drain23:00, down 시작23:30, 세 호스트 TERMINATED와 원장 종료는10/29 00:00 이전이다. 더 이른 whole-phase reservation이 우선한다.
- 공유 가동/비용 원장은 `artifacts/fresh-evaluation-2026-10-26/bed-uptime-cost-ledger.json`이며 초기화하지 않는다. 누적44h부터 신규 중지·48h 상한, 신규146234원·정리40000원, 기존 추정식의reserve20000원1회 조건을 유지한다. 실제 Billing으로 표시하지 않는다.

08:02 KST 시점 전체 예상은10/28 16:25 KST 부근이며 지연에 따라 갱신한다. 이 승인은 예산 초과·새 bed·유료 전환·원자료 삭제를 허용하지 않는다. 기존320GiB 디스크와14snapshot을 보존한다.

## 실행·종료

새 driver는 첫 budget gate 후 명시적 ensure부터 실제 실행한다. 완료된 case는 재실행하지 않고 미완료 attempt가 있으면 cleanup-only 검토로 전환한다. source/profile/preregistration은 첫 preparation부터 고정하며 첫 main 이후에는 변경하지 않는다. 수집 오류가 나도 남은 표본을 정상으로 채우지 않는다.

이 새 chat의 heartbeat 하나만 현재 driver·잠금·progress·비용/시간·cleanup을 확인한다. 정상 진행 중에는 중복 실행하거나 변화 없는 상태를 알리지 않는다. 실패·완료·시간/비용 문제·필요한 결정만 통지하고, 완료 또는 안전 정지 뒤 자동 점검을 종료한다. 이전 chat의 자동화를 복원하지 않는다.

마지막에는 원자료에서 새 preparation/main 보고서를 재생성하고29/8/DEV/calibration/무효를 분리한다. 소유 cleanup·worker auto/1·세 호스트 TERMINATED·공유 원장 종료·보존 자원 readback을 확인한다. 실제 관측이 끝나기 전 완료를 주장하지 않는다.
