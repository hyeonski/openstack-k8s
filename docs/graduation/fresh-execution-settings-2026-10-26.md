# 새 평가 실행 설정과 병렬 운영 결정

기준 구현은 `11b4f30`이다. 기존 Claude CLI 세션 `0effb442-3fcd-4249-a986-8281729d054c`와 3회 논의해 아래 측정·실행 원칙을 합의했다. 합의는 실환경 검증 완료를 의미하지 않는다. 이 문서는 기존 승인 연구·구축 계획을 보존하면서 설정과 일정을 구체화하는 실행 부록이다.

이후 사용자의 요청으로 **이번 작업에만 Sonnet 5.5**를 지정해 원세션을 `195711e5-a99d-4e2d-8a94-785e3d393a4b`로 분기했다. 두 차례의 추가 논의에서 단계 상한·baseline 선택·pilot 재시도·인계 조건을 확정했다. CLI에 `--model claude-sonnet-5-5`를 명시했으며 전역 모델 설정은 변경하지 않았다. 아래 최종 수치와 절차가 이전의 7200초 headroom 등 운영 초안을 대체한다. [Sonnet 최종 합의 원문](fresh-execution-settings-discussion-2026-10-26/sonnet-final-consensus.md).

**최종 운영 선택은 기존 bed 1개 직렬이다.** 사용자에게 무료 체험 계정 상태임을 확인했고, 실제 생성한 별도 프로젝트의 quota도 현재 사양에 부족했다. 아래 2개 bed 안은 검토 이력과 조건부 대안이며 현재 실행 지시가 아니다. 유료 전환·사양 축소·추가 프로젝트를 이용한 임의 재설계는 하지 않는다.

- 실행 담당: [GPT 6.1 sol 수행 프롬프트](fresh-evaluation-execution-prompt-2026-10-26.md).
- 입력 초안: [수치가 채워진 candidate profile](../../config/graduation-evaluation-fresh-candidate-2026-10-26.json). `readiness=draft`이며 바로 live 실행할 수 없다.
- 이전 구현 상태: [공동 구현 리뷰](fresh-evaluation-review-2026-10-26.md).
- 설정 원칙의 [Claude 3차 최종 합의 원문](fresh-execution-settings-discussion-2026-10-26/round-03-consensus.md)과 [원문 증거 hash](fresh-execution-settings-discussion-2026-10-26/evidence-manifest.json). 이후 무료 체험 여부·B quota를 실제 확인한 결과로 조건부 병렬안을 제외했다.
- 이번 원문 논의·조회 증거: Git 제외 경로 `artifacts/fresh-execution-settings-2026-10-26/`. Claude의 1차 제안에서 철회된 내용은 아래 최종 결정과 구별한다.

## 1. 사용자 범위와 새 마감

기존 결과를 primary에서 제외하고 S1~S4 모두 새로 평가한다. F-repeated 본시험 29개, preparation 8개, 별도 DEV를 유지한다. 사람 비교와 transient 확장은 포함하지 않는다.

사용자는 이후 마감을 **수요일 자정**으로 앞당겼다. 이를 **2026-10-28 수요일이 끝나는 24:00, 즉 10월 29일 00:00 KST까지 실험·정리·호스트 정지 확인 완료**로 적용한다. 이전의 10월 29일 정오 신규 주입 허용은 폐기한다. 목·금요일에는 보존한 raw로 보고서·발표자료를 작성한다.

| 운영 경계 | KST | UTC |
|---|---|---|
| 마지막 새 case 시작 | 10월 28일 21:00 미만 | `2026-10-28T12:00:00Z` 미만 |
| 마지막 신규 장애 주입 | 10월 28일 22:00 미만 | `2026-10-28T13:00:00Z` 미만 |
| 남은 실행 drain·예외 처리 | 10월 28일 23:00 | `2026-10-28T14:00:00Z` |
| 정리 상태 기록·호스트 down 개시 상한 | 10월 28일 23:30 | `2026-10-28T14:30:00Z` |
| 실험 운영 종료·정지 확인 | 10월 29일 00:00 | `2026-10-28T15:00:00Z` |

이 표는 끝까지 새 작업을 시작해도 된다는 허가가 아니다. 매 case의 준비·H·증거 수집·정리·호스트 정지 여유를 합산해 더 일찍 중단한다. 정상 관측 H를 마감에 맞춰 줄이지 않는다. 강제 중단한 관측은 결측/무효와 정리 상태를 그대로 보존한다.

이전의 48시간 상한은 보수적으로 **모든 bed의 가동시간 합**으로 유지한다. 이는 운영상 해석이며 사용자가 별도로 새로 승인한 48 bed-hours라고 표현하지 않는다. 한 bed에서 VM 또는 연관 image builder가 하나라도 켜진 구간의 합집합을 구하고 bed별로 합산한다. 준비·DEV·pilot·유휴·실패·정리도 포함한다. VM 3대가 동시에 켜진 한 bed의 1시간은 1 bed-hour다. 디스크 보관료는 VM 정지 후에도 별도로 센다.

크레딧 잔액 약 20만 원은 사용자 제공 정보다. 계정에서 잔액·만료일을 확인하기 전 실측 잔액으로 표현하지 않는다. 신규 작업 비용 gate는 16만 원, 나머지 4만 원은 정리·추정 오차 reserve로 둔다. 실제 가용 크레딧이 더 작으면 그에 맞춰 낮춘다. 크레딧 초과 현금 지출이나 유료 계정 전환은 이번 범위에 포함하지 않는다.

## 2. 측정 설정

| 설정 | S1 | S2 | S3 | S4 |
|---|---:|---:|---:|---:|
| 관측 H(초) | 1200 | 1200 | 900 | 1200 |
| 최종 안정창(초) | 120 | 120 | 120 | 120 |
| bin(초) | 20 | 20 | 20 | 20 |
| 요청/초 | 5 | 2 | 1 | 1 |
| bin 최소 표본 | 100 | 40 | 20 | 20 |
| 요청 deadline(초) | 5 | 5 | 5 | 5 |
| 서비스 목표 SLO(ms) | 200 | 500 | 2000 | 2000 |
| bin bad 허용 비율 | .05 | .05 | .05 | .05 |
| 완전한 bin당 허용 bad 수 | 5 | 2 | 1 | 1 |

SLO는 연구자가 사전 지정한 공학적 목표다. 외부 서비스의 실제 SLA라고 주장하지 않는다. bad는 오류·잘못된 응답·deadline 초과·SLO 초과의 합집합이다. healthy에는 표본 완전성, bad 비율, 성공 요청 p95≤SLO가 모두 필요하다. 20개 요청의 p95는 소수의 큰 값에 민감하므로 표본 수와 함께 제시한다.

**대조군이 목표를 만족해도 유효한 결과다.** Claude가 처음 제시한 과거 M 지연보다 낮은 120/150ms 목표는 반론 후 철회했다. 과거 M을 실패시키거나 새 P를 성공시키기 위해 목표를 조정하지 않는다. 과거 자료가 연구 설계에 알려져 있었다는 prior-knowledge 공개는 유지한다.

사전 등록한 보조 분석으로 S1·S2의 `scheduled_latency_p95_ms_difference`를 추가한다. 이 p95는 성공·정확·deadline 내 요청에 조건부다. 실패율, SLO 위반, 결측과 함께 보고하며 단독 우위 지표나 co-primary로 승격하지 않는다. 효과 없음, SLO 차이 없음, 조건부 지연 차이는 서로 구별한다.

### 부하·장애·타이머

- S1: 5 rps, 총 1800초, warmup 0, PBKDF2 100000 rounds, 경쟁 VM 4 vCPU/CPU workers 4. 주입 뒤 H+30초가 남아야 한다. 현재 구현상 주입 적용이 load 시작 후 570초를 넘으면 실패하므로 DEV/pilot에서 실제 오프셋을 기록한다.
- V1: 후보 하나만 사전 등록한다. 10000 rounds/CPU workers 4, 전용 SLO 100ms, bad .05, 자기 baseline 대비 p95 배율 1.5. 조건 미재현을 숨기거나 main에서 후보를 탐색하지 않는다. 후보 변경은 별도 amendment와 새 preparation이 필요하다.
- S2: 20Mbps, chunk 1MiB×4096, uploader 1800초. H+600을 충족하며 20Mbps×1200초는 4GiB보다 작다. H 뒤 clock bound+deadline+3초=13초 수집 tail을 두되 primary H를 늘리지 않는다.
- S3: 양 군 toleration 3600초, force detach 비활성, TCP 6443/5432 차단, 원 DB 프로세스 유지. seed 1000행, 새 Cinder PVC, 증거 수집 timeout 60초. H=900초의 결과로 3600초 이후 native 복구까지 주장하지 않는다.
- S4: worker VM 하나를 정확한 identity로 stop, worker 2개/HTTP replica 1개. MHC on/off readback, Node·VM·capacity와 안전한 pause 복원을 검증한다.
- S1/S2 clock bound: 5초. 실제 offset 불확실성 구간과 bin 20초 해상도를 공개한다. 이를 회복 시각 ±5초 또는 D ±1 bin이라는 오차 보장으로 해석하지 않는다.

fixture/fault의 정확한 상수는 candidate JSON과 `fresh_contract.SUPPORTED_FIXTURE`/`SUPPORTED_FAULTS`가 일치한다.

## 3. 첫 pilot 전에 필요한 최소 보완

다음은 이번 설정 논의에서 확인한 **남은 구현 작업**이다. 완료됐다고 표시하지 않는다. 실행 담당이 먼저 구현·검증하고, 그 뒤 source/policy를 고정한다.

1. **DEV 전용 진입점:** preparation 8개에는 S1 A 경로가 없으므로 DEV를 생략하지 않는다. 기존 adapter·ownership cleanup을 사용해 A 분기, 계측, 중단·정리를 점검한다. DEV 결과는 release의 campaign `artifact_root` 밖에 두고 primary=0임을 명시한다. DEV 시간을 운영 원장에는 포함한다. A가 guard로 보류됐으면 실제 재시작 경로까지 검증됐다고 주장하지 않는다. main case를 실행한 뒤 DEV라고 이름만 바꾸지 않는다.
2. **주입 전 baseline 독립 검증:** probe 준비 후 시작한 등록 stream의 **예정 arrival index 0부터 첫 60초**를 고정한다. 처음 관측된 행을 index 0으로 재정의하지 않는다. 각 `20×rate`개의 index 범위로 3개 bin을 나누고, 누락·중복·UTC/monotonic/clock-id 및 arrival schedule의 일관성을 별도로 검사한다. float 시각 경계의 반올림으로 행을 재분류하지 않는다. 세 bin이 위 healthy 조건을 모두 만족해야 하며 V1은 전용 SLO를 쓴다. 마지막 요청의 deadline 처리를 최대 5초 기다린 뒤 주입한다. 실패 후 같은 attempt에서 baseline을 슬라이딩하거나 성공하는 창을 찾지 않는다. S1/S2 원자료를 이용하되 S1 정책의 기존 90초 대기 후 마지막 60초 창은 변경하지 않고 연구 창과의 차이를 기록한다. S1의 새 gate는 경쟁 VM 생성 **이전**에 실행해야 한다. S3의 레거시30행을 재명명하지 말고 OpenLoopProbe의 동일 schema로 수집하고, S4의 3표본 baseline도 보강한다. 정상 baseline 실패 시 원인을 조사하고 목표를 자동 완화하지 않는다.
3. **보조 지연 차이 출력:** 현재 arm별 p95는 있으나 paired 차이 열은 없다. 유효한 첫 attempt의 S1/S2 비교에만 차이를 출력하고 null·실패·결측을 유지한다. 지표 선택이나 기존 primary 정의는 바꾸지 않는다.
4. **새 마감과 운영 gate:** 현재 runner가 21시 case 시작 제한과 자정 전체 종료를 자동 강제하지는 않는다. live 진입 전 case gate, 준비 시간 제한, drain/down 절차를 갖춘다. 아래 병렬 원장은 2개 bed를 선택할 때 추가로 필요하다.

단계 상한은 아래 값으로 확정한다. 개별 명령 timeout의 합이 아니라 **whole-phase deadline**이며, 기대 실행시간 추정과 구별한다.

| 단계 | 등록 위치 | 상한 |
|---|---|---:|
| 명시적 cold ensure·환경 준비 | `operations.environment_ensure_timeout_seconds` | 3600초 |
| ready/identity/터널 확인·worker/fixture 준비 전체 | `operations.fixture_prepare_timeout_seconds` | 1800초 |
| adapter 실행 | `max_case_seconds` | 5400초 |
| ownership cleanup | `operations.cleanup_seconds` | 1800초 |
| host down·정지 검증 | `operations.host_shutdown_timeout_seconds` | 1800초 |
| case 진입 시 남아야 할 host 수명 | `host_headroom_seconds` | **10800초** |

warm case는 준비30+adapter90+cleanup30+down30=180분을 예약한다. cold ensure가 추가되면 240분, 세션 교체를 위해 이전 host down30분까지 필요하면 270분이다. 자정에서 역산한 최종 시작은 각각 21:00/20:00/19:30 **미만**이다. 추가 drain·주입 마감·가동 예산 검사로 더 일찍 거절될 수 있다. cleanup/down을 중복 가산하지 않는다. 실측 예상 시간이 더 크면 큰 값을 적용하며 main 중 유리하게 상한을 줄이지 않는다.

`Campaign.environment()`는 현재 내부에서 down/ensure를 반복할 수 있다. 이 경로를 case 안에서 그대로 호출하지 않도록 보완한다. 세션 교체는 명시적 `down→cold ensure` 단계로 분리하고, case 내부에서는 이미 준비된 환경의 확인만 fixture 상한 안에서 수행한다. 환경이나 수명 조건이 불충족이면 **attempt 생성·case별 mutation 전에 admission을 거절**해 정상적인 세션 교체가 첫 attempt를 소모하지 않게 한다. attempt 진입 뒤의 실제 준비 실패는 infra-invalid로 남기고 소유 자원 정리로 전환한다. timeout은 cleanup 성공을 뜻하지 않는다.

새 운영 키는 현재 코드에 의해 모두 강제되는 상태가 아니다. validator의 필수 키·범위 검사, 실제 consumer, deadline/중단 검증을 함께 구현한다. `pilot_contract()`에는 위 단계 상한 전체와 `host_headroom_seconds`를 포함해 pilot–main 사이에 바뀌면 재pilot을 요구한다. 기존 `operations` 차이 기록만으로 일치를 검증했다고 표시하지 않는다.

`operations.budget_seconds=158400`은 44시간의 attempt ledger gate다. 실제 가동 시간 44시간에서도 새 case 시작을 중지하고 남은 4시간을 진행 중 작업과 정리에 남긴다. 실제 가동 시간·모든 진행 중 예약·bounded 준비/관측/정리/down 여유를 함께 검사한다. 자동 계량이 없는 현재 구현을 실시간 비용 상한 장치로 표현하지 않는다.

## 4. 실측 후 확정할 입력과 pilot 순서

candidate의 `timers.mhc_policy.s3_specs=[]`는 **기대 설정이며 실제 조회 결과가 아니다**. 관리 클러스터에서 실제 MHC specs를 읽어 기록하고 일치 여부를 확인한다. 다르면 소유권·기존 의도를 조사하고 실제 계약을 명시한 새 profile을 등록한다. 무관한 MHC를 삭제해 빈 목록에 맞추지 않는다.

환경 override, 실행 checkout, artifact root, operator, 실제 이미지/버전/host identity와 MHC readback을 확인한 뒤 `.state/<환경>/evaluation-profiles/`의 별도 immutable profile을 `confirmed`로 만든다. tracked candidate를 직접 수정해 여러 frozen campaign에 재사용하지 않는다. confirmed는 입력 명시 완료이며 pilot 성공과 다르다.

순서는 **사전 보완 → DEV → 모든 필수 preparation → 공통 go/no-go → main**이다. 직렬 pilot은 S1→S2→S3→S4다. policy/common judgement 변경 시 새 freeze로 필요한 pilot wave 전체를 다시 수행한다. 이전 raw는 보존한다.

go/no-go에는 baseline·fault 재현·독립 유효성·안전·cleanup, P/on의 H 내 회복, V1 조건 성립과 정상 보류, clock bound, S1 load 잔여 시간, S2 조정 시간, S3 MHC/seed, S4 pause/capacity를 포함한다. M/off가 회복하지 않았다는 이유로 실패한 pilot으로 바꾸지 않는다. main은 해당 bed·시나리오의 유효한 pilot과 동일한 계약이어야 한다.

동일 계약에서 infra-invalid pilot만 추가 attempt 1회를 허용하고 모두 보존한다. 유효하지만 P/on 미회복 또는 V1 조건 미재현이면 해당 시나리오 pilot no-go다. 같은 코드·계약으로 새 campaign을 계속 만들어 성공만 선택하지 않는다. 실제 원인을 수정하면 변경 이유와 예산을 기록하고 새 계약/source의 pilot을 검증한다. S1/S2 각각에서 clock 검증에 실패한 attempt가 연속 2회면 원인을 조사하기 전 추가 주입을 중지한다. freeze의 pilot 수용 gate를 우회하지 않는다. main first-attempt-only 원칙과 pilot의 공학적 준비 검증을 혼동하지 않는다.

### 현장 확인 체크리스트

수치 선택과 다음 실측 항목을 구분한다. 실행 담당 GPT 6.1 sol이 아래 증거를 확보한 후 profile을 물질화한다.

| 항목 | 확인할 증거 | 불일치·조회 불가 시 |
|---|---|---|
| S3 MHC specs | 관리 kubeconfig의 실제 MachineHealthCheck 목록/spec, S3 직전 재조회 | 실제 의도·소유권 조사 후 새 profile 등록; 무관한 MHC 삭제 금지 |
| host identity·cpuPlatform·사양 | GCP의 instance ID/type/platform와 준비 완료 snapshot | 동일 cohort에서 불일치 우회 금지 |
| 이미지·Kubernetes·flavor·타이머 | image checksum/ID, 실제 버전·flavor·toleration/force-detach readback | 지정 계약과 맞추고 다시 검증; 기대값을 실측으로 표시 금지 |
| 경로·운영자·override | 현재 checkout/override/artifact/profile 절대경로와 hash | 경로를 실제 환경으로 바꾼 새 immutable profile 사용 |
| 크레딧 잔액·만료일 | 기존 결제 계정 콘솔; 접근 불가 시 사용자 제공 두 값과 확인 시각 | 조회한 것처럼 표시하지 않고 필요한 정보만 요청; 로컬 보완은 계속 |
| 단계별 실제 시간 | 최초 기동·DEV·pilot의 단계별 start/end, 가동 원장 | 남은 일정 재산정; H를 줄이거나 상한을 자동 완화하지 않음 |

설정 부록과 수행 프롬프트는 현재 `source_hashes()`의 자동 대상에 포함되지 않는다. candidate의 `operations.preregistered_documents`에 두 경로를 등록했다. 실행 담당은 freeze에 **파일명·SHA-256·실제 복사본**을 보존하고 변경 검사를 구현한다. DEV도 실행 전 source/profile snapshot을 보존한다. 수정이 있으면 새 snapshot과 검증을 거쳐 최종 코드로 preparation을 freeze한다.

## 5. 1개와 2개 testbed의 시간 비교

기존 45/38/35/25/28분 per-run 추정과 20% 여유·세션 공통 50분을 적용한 계획값이다. 새 H와 추가 baseline의 실제 시간은 DEV/pilot 후 재산정한다. 추가 구축·수정·기동 지연이 자동으로 포함됐다고 해석하지 않는다.

| 직렬 단계 | nominal(분) | 여유 포함(분) |
|---|---:|---:|
| DEV | 60 | 122 |
| 전체 preparation 8개 | 73+76+70+50=269 | 372.8 |
| S1 main SESSION-A | 191 | 279.2 |
| S1 main SESSION-B | 270 | 374 |
| S2 main | 228 | 323.6 |
| S3 main | 210 | 302 |
| S4 main | 150 | 230 |
| 합계 | | **2003.6분 = 33시간 23.6분** |

pilot wave 1회 추가는 372.8분으로 총 **39시간 36.4분**이다. 이전 32시간 33.6분보다 50분 늘어난 이유는 pilot wave를 별도 세션으로 분리했기 때문이다. V1 main 2개/56분을 preparation 시간에 다시 넣지 않는다.

사전 보완 후, DEV 후, 전체 pilot 후에 **아직 남은 작업만** 다시 계산한다. 완료한 DEV나 pilot을 전체 추정에 다시 더하지 않는다. 재pilot 1회 예비가 없어도 기본 29+8을 안전하게 끝낼 수 있으면 낮아진 여유를 공개하고 진행할 수 있다. 기본 범위도 불가능하면 구체적 완전 block/미완료 대안을 사용자와 협의한다. 승인 없는 자동 축소 순서는 두지 않으며 응답 전에도 독립적인 로컬 분석과 안전 정리는 계속한다.

S1 두 main 세션의 계획 합계는 653.2분, **10시간53.2분**이다. 10시간 host 수명 안에서 무리하게 붙여 재기동을 회피하지 않는다. 세션 B의 `cpuPlatform`이 달라지면 원래 cohort와 미완료 상태를 보존한다. 같은 플랫폼이 나올 때까지 반복 재기동하거나 identity 검사를 제거하지 않는다. 새로운 동일 조건 cohort가 필요하면 남은 시간·비용을 제시하고 협의한다.

두 bed는 **A=S1→S4, B=S2→S3**로 나눈다. 같은 시나리오의 pilot/main과 모든 비교 arm·block은 같은 bed에서 한다. S4 마지막 규칙은 **그 bed 안에서 마지막**이라는 뜻이다. 격리된 B의 S3와 A의 S4는 동시에 할 수 있다.

| 두 bed 단계 | A(분) | B(분) |
|---|---:|---:|
| preparation | 197.6 | 225.2 |
| main | 883.2 | 625.6 |

공통 DEV 122분 후 preparation 병렬→모든 pilot 확인→main 병렬이면 달력 시간은 `122+max(197.6,225.2)+max(883.2,625.6)=1230.4분`, 즉 **20시간 30.4분**이다. 직렬 대비 잠재 절감은 **12시간 53분**이다. 추가 bed 구축과 병렬 운영 보완 때문에 critical path가 늘어난 만큼 이 절감에서 뺀다. 조기 배포된 bed의 대기 시간도 가동 원장에 더한다.

사용자는 크레딧과 quota가 허용하면 **총 2개** 운영에 조건부 동의했다. 그러나 뒤의 실제 quota 확인에서 조건을 충족하지 못했으므로 현재는 직렬로 진행한다. 3번째 bed는 제외한다. 향후 사용자가 조건을 변경해 다시 검토할 때에도 준비·검증·전환까지 포함한 순절감이 최소 2시간이고 마감 여유가 개선되어야 한다. 새 bed 준비에 매달려 기존 평가를 지연시키지 않는다.

## 6. 병렬화와 GCP 확인 사항

2026-10-26 read-only 조회에서 기존 `openstack-k8s`의 세 호스트는 모두 TERMINATED였다. 서울 리전 한도/사용량은 SSD 계열 500/320GiB, 공인 IP 8/0, N2 CPU 200/0, E2 CPU 24/0이다. 현재 IaC 한 bed는 320GiB pd-balanced와 3개 공인 IP가 필요하다. 같은 프로젝트 2개는 640GiB, 3개는 960GiB/9 IP로 현재 한도를 넘는다. [pd-balanced도 SSD quota에 포함된다](https://docs.cloud.google.com/compute/resource-usage#disk_quota).

같은 프로젝트에서 ENV 이름만 바꾸면 고정 VM/VPC/subnet/firewall/address 이름이 충돌한다. 별도 프로젝트에 같은 논리 hostname·주소를 유지한 동일 사양 bed를 만드는 경로를 우선 검토한다. 별도 프로젝트의 quota가 기존과 같다고 가정하지 않는다.

**무료 체험 크레딧은 기존 결제 계정을 공유해야 한다.** 새 프로젝트를 크레딧이 있는 기존 계정에 연결한다. 새 결제 계정에는 기존 무료 체험 크레딧이 적용되지 않는다. 무료 체험 계정 상태라면 quota 증설 요청도 할 수 없다. 유료 전환 없이 가능한 한도에서 판단한다. [크레딧과 결제 계정](https://support.google.com/cloud/answer/7364537?hl=en), [무료 체험 제한](https://docs.cloud.google.com/free/docs/free-cloud-features).

실제 계정의 API 조회에서는 billing enabled/open/KRW까지 확인했다. API에 무료 체험 여부·잔액·만료일 필드는 없고 브라우저는 로그인되지 않아 조회하지 못했다. 이후 사용자가 **아직 무료 체험 계정 상태**라고 확인했다. 잔액·만료일은 여전히 사용자 제공 정보와 실제 조회를 구별한다.

실제로 `openstack-k8s-eval-b-20261026`을 생성하고 기존과 동일한 결제 계정 연결 및 Compute API 활성화까지 수행했다. VM·디스크는 만들지 않았고 결제 계정 생성·유료 전환도 하지 않았다. Compute API가 만든 기본 네트워크가 있으므로 모든 종류의 리소스가 전혀 없는 프로젝트라고 표현하지 않는다.

| B 프로젝트 quota | 한도 | 현재 구성에 필요 | 판정 |
|---|---:|---:|---|
| 전역 `CPUS_ALL_REGIONS` | 12 | 16 | 부족 |
| 서울 `SSD_TOTAL_GB` | 250GiB | 320GiB | 부족 |
| 서울 `N2_CPUS` | 200 | 12 | 충족 |
| 서울 `E2_CPUS` | 24 | 4 | 충족 |
| 서울 `IN_USE_ADDRESSES` | 8 | 3 | 충족 |

리전별 CPU가 충분해도 별도의 전역 CPU 한도를 넘을 수 없다. **기존 크레딧 공유 연결은 성공했지만 동일 사양 bed 복제는 실패한 preflight**다. 신규 프로젝트를 더 만들면 한도가 해결된다고 가정하지 않는다. 증거는 `artifacts/fresh-execution-settings-2026-10-26/bed-b-project-preflight.json`이다. B는 사용하지 않는 사전 확인용 프로젝트로 인계하며 유료 리소스를 생성하지 않는다.

기존 `.state/cloud-gcp-amd64-greenfield/images/`에 v1.35.7 QCOW2 약 2.26GB와 checksum·metadata가 있다. checksum/버전 일치 확인 후 B의 이미지 경로에 복사하면 `lab-up.sh`가 이미지 재빌드를 생략할 수 있다. 기존 클러스터의 credentials/state 전체를 복사하지 않는다. 프로젝트 생성·Billing 연결은 현재 bootstrap의 선행 요건이다.

2개 운영에 필요한 구현 조건:

- bed별 ENVIRONMENT_NAME, `.state`, override, 확정 profile, artifact root, SSH 키·kubeconfig·Tofu state를 분리한다. management/workload 로컬 터널은 A 16443/16444, B 17443/17444로 분리하고 실제 설정 키와 readback을 확인한다.
- 도구 설치와 IaC init 등 공유 경로 mutation은 동시 실행하지 않는다. 필요하면 동일 commit의 독립 checkout/TF_DATA_DIR을 쓴다. 이미지·spec·버전·policy/analysis/source 계약의 동등성을 대조한다.
- release registry에 bed/profile/campaign 경로와 hash를 기록한다. atomic case claim, bed당 단일 실행, 시간·비용 예약과 실제 정산, crash 후 재개를 구현·검증한다. 각 bed root의 기존 budget gate만으로 전역 상한을 보장하지 않는다.
- 같은 policy와 첫 attempt 규칙을 유지하고, 서로 다른 scenario를 한 표본으로 풀링하지 않는다. bed가 늘었다고 n이나 환경 일반화 근거가 늘지 않는다.
- 임시 자원의 생성 목록·소유권·종료 절차를 먼저 기록한다. Terraform의 `prevent_destroy`를 무작정 해제하거나 기존 bed 자원을 삭제하지 않는다. 마감에는 가동을 중단하고 임시 디스크 등 잔여 과금 자원도 정리·기록한다.

## 7. 비용 근거와 보고

Google Cloud Billing Catalog API에서 KRW 단가를 조회했다. effective time은 `2026-10-25T07:00:00Z`다. [Catalog API 안내](https://docs.cloud.google.com/billing/v1/how-tos/catalog-api).

| 항목 | 원화 단가 |
|---|---:|
| E2 core | 38.080898184원/core-hour |
| E2 RAM | 5.080515713원/GiB-hour |
| N2 core | 55.158456263원/core-hour |
| N2 RAM | 7.392958751원/GiB-hour |
| Seoul zonal pd-balanced | 176.637500042원/GiB-month |

현재 1 bed의 컴퓨팅은 E2 4core/16GiB + N2 합계 12core/48GiB로 **약 1250.38원/시간**, 합산 48 bed-hours는 **약 60018원**이다. API의 월 단위 변환은 744시간으로, 320GiB 디스크는 **약 1823.35원/bed/달력일**이다. 두 bed의 디스크를 4일 보관하면 약 14587원이다.

이는 청구 확정액이 아니다. 공인 IP·egress·builder·이미지·snapshot·정지 후 디스크·세금·다른 프로젝트 사용량·단가 변동을 별도로 합산한다. 할인은 가정하지 않는다. 8~12만 원은 준비용 envelope이며 실제 가용 크레딧과 각 항목을 확인한 뒤 비용 원장을 갱신한다. [디스크 가격](https://cloud.google.com/compute/disks-image-pricing), [네트워크/IP 가격](https://cloud.google.com/vpc/network-pricing).

## 8. 결과 선택과 release 보존

첫 attempt만 primary다. 무효 첫 attempt를 성공한 retry로 대체하지 않는다. 추가 retry 최대 1회는 보조 자료이며 자동 반복하지 않는다. A 미전달/보류, V1 조건 미재현, M 자연 회복, safety unknown, cleanup 실패를 숨기지 않는다. H 내 미회복 시간을 H로 대입하지 않는다.

첫 main 뒤 policy/common judgement를 바꾸면 새 연구 release다. 기존 결과는 원래 release의 결과로 보존하며 새 결과와 하나의 동일 정책 평가로 섞지 않는다. S1~S4를 단일 공통 policy 결과로 완성하려면 모두 동일 새 release에서 평가해야 한다. 마감/비용을 넘는 재평가나 범위 축소는 사용자와 협의한다.

목·금요일의 report 재실행은 호스트 없이 frozen 실행 checkout에서 한다. 그 checkout과 hash 대상 문서는 수정하지 않는다. 보고서·발표자료는 다른 checkout이나 별도 산출물 경로에서 작성한다.
