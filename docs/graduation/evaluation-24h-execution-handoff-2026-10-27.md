# GPT 6.1 Sol — 준비 병목 보완과 24시간 내 평가 수행

워크스페이스 `/Users/hyeonseungkim/workspace/openstack-k8s`에서 **반복되는 준비·원격 수집 실패를 최소한의 보완으로 줄이고, preparation 8개와 main 29개를 수행·분석·정리**해라. 사용자가 이 작업을 새 GPT 6.1 Sol 세션에서 자동 시작하도록 명시적으로 요청했다. 계획이나 프롬프트 작성으로 끝내지 말고 보완·검증 뒤 실제 실험을 시작하고 완료까지 진행한다.

## 최신 권한·기한

사용자의 최신 지시는 다음과 같다: “지금 다 끝난거 같으니까 준비에서 최대한 걸리지 않고 실험을 24시간 안에 완료할 수 있도록 준비해주고, 이 준비 + 실험 시작까지 새로운 세션에서 네가 자동으로 시작해줘. 새로운 세션 모델은 GPT 6.1 Sol로 해서.”

이 지시는 기존 “현재 DEV 종료 후 다음 실험 보류”를 해제하는 명시적 재개 승인이다. 원래 HOLD 기록을 삭제·덮어쓰지 말고, 새 승인 시각·문구·source를 별도 재개 원장에 남긴다. 새 실행 root/driver가 이 최신 승인을 명시적으로 소비하도록 한다. 예전 driver의 HOLD 검사를 무조건 삭제해 우회하지 않는다. 이 새 세션이 유일한 실행자다. 기존 스레드 `01a17733-8c21-78b0-845c-6b9bd9e88b58`의 자동 점검은 삭제됐다는 종료 기록이 있으나, 활성 프로세스·잠금·자동화 중복을 확인한다.

**24시간 목표의 기준 시각은 2026-10-27 01:10:19 KST(`2026-10-26T16:10:19Z`), 완료 목표는 2026-10-28 01:10:19 KST(`2026-10-27T16:10:19Z`)다.** 준비 보완·실험·판정·소유 cleanup·호스트 정지까지 포함한다. 재개·재시도 때 시계를 다시 시작하지 않는다. 원래 10/29 00:00 KST 종료 한도와 누적44/48시간·금액 제한도 유지하되 더 이른 기한을 적용한다. 24시간에 맞추려고 H·안정창·표본 수·안전 조건을 줄이거나 미완료를 완료라고 보고하지 않는다.

기존 남은 계획은 약31시간22분으로 목표보다 길다. **24시간 완료를 근거 없이 약속하지 말고 실제 절감 가능한 시간을 계산해 구현·실행한다.** 필요한 약7시간22분 절감이 확보되지 않으면 그 사실과 가능한 종료시각·범위 대안을 조기에 사용자에게 알린다. 자동 범위 축소나 기한 초과는 하지 않는다. 필요한 결정 대기 중에도 독립적인 로컬 보완·분석·안전 정리를 계속한다.

## 현재 확인된 완료 상태

- 최신 인계 commit `b8db4cd`; 실험 source `6730ecf`. 시작할 때 현재 HEAD/status를 확인하고 다른 작업을 덮어쓰지 않는다.
- 정상 calibration3회+별도validation2회 완료. S1 SLO200ms 유지. 새로 반복하지 않는다.
- 새 S1 A DEV attempt-02는 `trial_valid=true`, `safety=true`, `recovered=true`, `cleanup=true`. 실제 restart·Pod 교체·동일Node/VM/compute·clock·H·9000개 요청을 검증했다. attempt-01은 H 후 IAP TLS EOF로 infra-invalid이며 원자료를 보존했다. DEV primary=0.
- **A 단순 재시작도 이번 DEV에서는 주입 후180초부터 회복 기준을 충족했다.** 재시작은 효과가 없고 P만 효과가 있어야 한다는 가정으로 부하·SLO·정책을 조정하지 않는다. 본시험의 null/유사 효과도 유효한 결과다.
- preparation0/8, main0/29. 기존 operator driver는 실행하지 않았다.
- 10/27 01:03:58 KST 최종 readback에서 호스트3대 TERMINATED. worker auto/1 등13개 복원 점검 통과. 누적 가동약4시간29분40초, 원장 추정약32544원(실제 Billing 아님). 기존320GiB 디스크·snapshot14개 보존.

먼저 읽을 자료:

1. `docs/graduation/fresh-evaluation-calibrated-dev-result-2026-10-27.md`와 `artifacts/fresh-evaluation-calibrated-2026-10-26/progress.json`, `dev-attempt-01-failure-analysis.md`, `HOLD-NEXT-EXPERIMENTS.json`.
2. `docs/graduation/fresh-evaluation-resume-after-calibration-2026-10-26.md`, `s1-baseline-amendment-2026-10-26.md`, `controller-platform-amendment-2026-10-26.md`.
3. 기존 `fresh-execution-settings-2026-10-26.md`, `fresh-evaluation-execution-prompt-2026-10-26.md`, 연구·구축·실행 계획. 과거 “DEV未완료/정상 보정 필요” 설명은 최신 완료 증거로 대체한다.
4. `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-controller-x86-v3.json` (SHA256 `363d546937a229cbc3429fc589100c6d22e8cf6e34819dd4986d6476b810e33b`). 이전v2를 사용하지 않는다.
5. `artifacts/fresh-evaluation-development-calibrated-2026-10-26/dev-v1`의 두 attempt·frozen source와 `artifacts/fresh-evaluation-calibrated-2026-10-26/execute-release-v3.py`.
6. `evaluation/fresh_live.py`, `fresh_scenarios.py`, `fresh_analysis.py`, `fresh_campaign.py`, `fresh_contract.py`, `fresh_operations.py`, `graduation_evaluation.py` 및 관련 scenario·worker·remote 실행기·tests. 저장소 지침과 최근 커밋 컨벤션.

## 먼저 보완할 좁은 범위

로컬에서 **60분 내 핵심 보완·실행 계획 확정**을 목표로 한다. 90분 시점까지 새 큰 체계를 설계하지 말고 실제 변경·검증·시간 절감과 미완료 문제를 보고한다. 준비 자체가 장시간 새 개발 프로젝트가 되지 않게 한다. 기존312개 테스트와 완료한 DEV를 무조건 반복하지 말고 변경 영향에 맞는 검증을 수행한다.

### A. 원격 수집 오류로 실험 전체를 잃지 않기

S1은 최종 host_sample 예외가 `FreshS1.finish()`의 표준 requests/contract 생성까지 막았다. S2에도 종료 시 원격 요청 로그를 가져오는 경로가 있다. 각 시나리오를 짧게 감사해 필수·보조 증거, 수집 시각, 저장 위치, 재수집 가능성을 명시한다.

- 요청·사건·필수 상태 자료를 가능한 즉시 내구성 있게 저장한다. 최종 보조 조회가 실패해도 이미 확보한 요청·이벤트를 표준화·판정 가능한 형태로 남긴다. 항목별 missing/unknown을 보존한다.
- 읽기 전용 조회에 횟수·누적 시간 제한을 둔 재연결/재시도를 적용한다. 관측 시각·각 시도와 오류를 기록한다. 이미 저장된 원격 파일은 실험을 다시 하지 않고 다운로드만 재개할 수 있게 한다.
- **완료 시점의 host 통계는 장애가 계속됐는지를 확인하는 필수 역할이 있다.** 빠진 것을 단순 보조로 재분류하거나 나중 통계로 과거 시점을 채우지 않는다. 시간 구간이 중요한 통계는 원격 timestamp와 함께 미리 저장/주기 수집하고, 허용 관측 간격과 실패 의미를 본시험 전 등록한다.
- VM stop·fencing·volume detach·정책 mutation을 읽기 재시도와 같이 무조건 재실행하지 않는다. 응답 유실은 identity/readback으로 확인하고 중복 side effect를 막는다.
- 과거 실패한 DEV 판정은 고치지 않는다. 앞으로의 모든 arm에 공통 적용할 수집·판정 계약을 변경 기록과 새 freeze로 명시한다.

### B. 반복 worker 준비의 실제 비용 줄이기

현재 매 case마다 auto/1→fixed/2→필요시 live migration→auto/1을 수행한다. 이번 DEV fixture 준비는 약387.5초였으며 새 VM·Calico·터널 대기와 cleanup 비용이 반복된다. nominal 시간표에 이미 포함된 시간을 다시 더하지 말고 실제 준비/부하/H/수집/정리/기동을 분해해 임계 경로를 계산한다.

안전하고 비교 조건이 동일하게 유지된다면 **한 host session 안에서 준비된 worker2개를 유지하며 case별 서비스·장애·QoS·taint·volume 등만 완전히 초기화하는 방식**을 검토·구현할 수 있다. 이는 시간 절감을 위한 이번 승인 범위의 운영 변경이다. 기존 auto/1 계약을 조용히 무시하지 말고 amendment·새 profile/validator/cleanup contract에 동일한 case 시작 상태와 세션 종료 auto/1 복원을 등록한다. cluster/MD/VM/Node identity, source/target 배치, workload·영향 잔존과 제어기 정책을 모든 arm에서 같게 검증한다. S3/S4가 실제 VM·volume 상태를 바꾸는 경우 별도 재준비/격리가 필요하므로 무조건 재사용하지 않는다.

기존 fixture 격리와 비교 가능성을 입증할 수 없거나 구현이 더 비싸면 이 최적화를 채택하지 않는다. case간 잔존 부하·캐시/초기화 차이·정책 상태 누적을 숨겨 시간만 줄이지 않는다. VM 재사용은 독립된 여러 환경을 시험했다는 증거가 아니다.

### C. 연결 오류·정리·회전과 연구 실패를 구분

로컬 API tunnel 조회 실패를 실제 VM/Node NotReady로 단정하지 않는다. 준비 중 제한된 재연결을 사용하되 준비 timeout은 리셋하지 않는다. cleanup은 중간 상태·ownership을 저장하고 cleanup만 재개한다. 잠금이 풀리지 않았는데 down하지 않는다.

controller는 승인된 동일E2 ID/type + 실제x86_64, Intel/AMD 모델 기록 조건을 유지한다. 두 N2 compute의 등록 ID/type/platform은 엄격히 확인한다. host 수명10시간을 고려해 block 경계에서 회전하고, 무의미한 재기동·원하는 플랫폼이 나올 때까지의 재시도는 하지 않는다.

기존 시간 예약이 `max_case=90분`처럼 실제보다 넓어서 끝부분 실행을 막을 가능성도 확인한다. 상한과 예상시간은 구분한다. 안전한 검증 근거가 있으면 시나리오별 실행 상한을 사전 등록할 수 있지만 H·tail·안정창·cleanup/down 예약을 침범하거나 시간 gate를 해제하지 않는다.

## 검증 재사용과 실제 실행

새 운영 보완에 대해 오류 주입을 활용한 로컬 테스트로 일시 연결 단절·원격 파일 재수집·부분 증거·mutation 응답 유실·cleanup 재개·세션 종료 복원을 확인한다. 이는 클라우드에 새 장애를 주입하는 추가 실험이 아니라 실행기 테스트다. 테스트가 통과하면 불필요하게 반복하지 않는다.

완료한 정상보정과 A DEV는 과거 source의 증거로 보존하고 **변경 영향 표**로 재사용 여부를 설명한다. 데이터 의미·probe 경로·정책·실제 A 실행 경로를 바꾸지 않은 운영 보완이면 DEV 전체를 기계적으로 다시 하지 않는다. 영향을 준 경로만 필요한 확인을 하고, 이미 예정된 preparation으로 검증할 수 있는 것은 거기에 통합한다. 코드가 달라졌는데 옛 hash를 같은 것으로 위장하거나 source 검증 대상을 제거하지 않는다. 계측 source가 달라 calibration 재사용이 불가능하면 정직하게 필요한 재검증과 시간 영향을 밝힌다.

전체 preparation8개의 go/no-go 후 main29개라는 기존 범위를 유지한다. calibration·DEV·native 환경 probe를 preparation/main으로 세지 않는다. 첫 main 전에 정책·판정·측정·운영 계약을 새 snapshot으로 한 번 확정하고 변경을 멈춘다. 정책의 유효한 미회복과 infra-invalid를 구분하고, 성공할 때까지 수정·반복하지 않는다. main은 first-attempt-only, 실패·결측·효과 없음도 보존한다. 사람 비교나 추가 시나리오는 넣지 않는다.

24시간 안에 들어가는 **실행 순서·세션 회전·관측 시간·준비/정리 실측·예비 시간의 합계**를 남긴 뒤, 제약을 통과하면 별도 승인 질문 없이 기동·preparation·main을 실제로 시작한다. 숫자를 줄여 계획표만 맞추지 않는다. 완료 예상은 각 case의 실제 시간으로 갱신하고, 남은 전체 범위가 기한에 못 들어갈 조짐은 즉시 알린다. 같은 bed에서 서로 간섭하는 장애를 병렬 실행하지 않는다.

## 운영·산출물

- 기존 bed/project/zone/override만 사용. 새 bed·유료 전환·현금 초과 지출 금지. 공유 누적 원장은 `artifacts/fresh-evaluation-2026-10-26/bed-uptime-cost-ledger.json`; 새 실행에서 초기화하지 않는다.
- 사용자 제공 잔액186234원 기준 신규146234원/정리40000원 한도를 유지한다. 원장20000원 예비비 중복 가산 금지. 실제 Billing과 추정 구분. 가동 누적44h부터 신규 중지/48h 상한과 새24h 기한을 모두 적용한다.
- 새 실행 root는 예를 들어 `artifacts/fresh-evaluation-24h-2026-10-27/`에 만들고, 예전 progress·release·raw를 덮어쓰지 않는다. 새 재개 승인, 24h deadline, 변경 영향, 실행 계획, 단계/유효 표본/남은 일정, 소유 자원/cleanup, 비용 원장 경로를 저장한다.
- 긴 실행을 실제로 계속 수행한다. 필요하면 이 새 스레드에 heartbeat를 하나 등록해 현재 프로세스/driver를 점검·이어가되 중복 실행하지 않는다. 변화 없는 상태는 알리지 않고 단계 완료·실패·시간/비용 문제만 알린다. 완료 또는 안전 정지 후 자동화를 종료한다. 이전 스레드 자동화를 부활시키지 않는다.
- 분석은 원자료에서 재현하고 29 main/8 preparation/DEV/calibration/재시도/무효를 구별한다. 누락을 정상으로 만들거나 H를 미복구시간의 실제 값으로 평균 내지 않는다.
- 완료 또는 중단 시 owned cleanup·worker 제어 복원·호스트3대 TERMINATED를 확인하고 가동 원장을 닫는다. 기존320GiB 디스크와14snapshot은 보존한다.
- 코드·설정·amendment·운영 개선은 기존 `type: 한국어 제목`과 변경 bullet·검증 본문으로 커밋한다. raw/비밀정보는 커밋하지 않는다. 새 실행 계약은 실제 확정값을 기록한 문서로 별도 작성하고 동결한다.

최종 보고는 “준비에서 무엇을 줄였는가, 실제 몇 시간을 썼는가, 8/29 중 무엇을 완료했는가, 어떤 연구 주장에 어떤 결과를 얻었는가, 실패·한계·남은 일은 무엇인가”를 간결하게 답한다. 24시간 목표 달성 여부와 실험의 유효성을 따로 정직하게 보고한다.
