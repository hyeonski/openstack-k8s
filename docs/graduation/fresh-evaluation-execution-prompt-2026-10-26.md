# GPT 6.1 sol 새 세션용 — 새 평가 수행 프롬프트

아래 본문을 새 세션의 첫 메시지로 사용한다. 과거 대화를 읽지 않아도 작업할 수 있도록 현황·권한·중단 조건을 포함했다.

---

워크스페이스 `/Users/hyeonseungkim/workspace/openstack-k8s`에서 졸업작품의 **S1~S4 새 평가를 준비·수행·검증·분석**해 줘. 계획 제안에서 끝내지 말고, 아래 필수 사전 보완과 DEV/pilot을 거쳐 허용 시간·비용 안에서 실제 평가를 진행해라. 좋은 결과를 만드는 것이 아니라 사전 등록한 비교를 정직하게 실행하고 실패·결측·한계를 보존하는 것이 목표다.

## 1. 반드시 먼저 읽을 자료

1. `docs/graduation/fresh-execution-settings-2026-10-26.md`: 이번에 Claude와 합의한 수치·마감·남은 구현·실제 GCP quota 확인과 최종 직렬 결정.
2. `config/graduation-evaluation-fresh-candidate-2026-10-26.json`: 수치가 채워진 draft. 이 파일을 곧바로 live로 실행하지 말 것.
3. `docs/graduation/fresh-evaluation-review-2026-10-26.md`: 구현 공동 리뷰와 아직 실측하지 않은 조건.
4. `docs/graduation/fresh-evaluation-build-plan-2026-10-26.md`, `fresh-evaluation-run-plan-2026-10-26.md`, `consensus-research-plan-2026-10-26.md`: 승인 연구 계약. 기존 본문은 덮어쓰지 않는다. 새 설정 문서가 일정·수치·운영 선택을 구체화한다.
5. `evaluation/fresh_campaign.py`, `fresh_contract.py`, `fresh_live.py`, `fresh_scenarios.py`, `fresh_analysis.py`, `evaluation/commands.mk` 및 관련 tests.
6. 저장소 운영 문서·지침과 최근 `git log -5 --format=full`. 커밋은 `type: 한국어 제목`과 변경 bullet·검증 본문을 포함한다.

기준 구현 commit은 `11b4f30`이며, 인계 문서/candidate를 추가한 이후 현재 HEAD부터 시작한다. 이전 로컬 검증은 284 tests와 합성 29 main/8 preparation이 통과했고 합성 primary=0이었다. **새 live DEV·pilot·main은 아직 수행하지 않았다.** 이전 실행·합성 결과를 새 결과로 표시하지 않는다.

기존 Claude 세션과 설정 논의는 끝났다. 세션 한도 경고가 있었으므로 재검토를 반복 호출하지 말고 합의 문서를 우선 사용한다. 실제 구현 결함은 증거를 보존해 해결하되, 합의된 연구 설계를 조용히 바꾸지 않는다.

## 2. 승인된 범위와 현재 인프라

- 기존 결과는 primary에서 제외한다. F-repeated **29 main + 8 preparation + 별도 DEV**를 실행한다. 사람 비교·transient 확장·추가 반복으로 유의성을 찾는 작업은 포함하지 않는다.
- 현재 선택은 **기존 테스트베드 1개 직렬**이다. 환경 `cloud-gcp-amd64-greenfield`, 프로젝트 `openstack-k8s`, 서울 `asia-northeast3-a`, override `/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env`.
- controller `e2-standard-4`, compute01 `n2-standard-8`(target/control-plane), compute02 `n2-standard-4`(source). Kubernetes v1.35.7과 고정 fixture를 유지한다.
- 마지막 조회에서 세 호스트는 TERMINATED였지만 실행 시 현재 상태를 다시 확인한다.
- 사용자에게 무료 체험 계정 상태임을 확인했다. 남은 크레딧 약 20만 원은 사용자 보고이며, 만료일·실제 잔액은 별도 확인 대상이다. 기존 결제 계정을 유지한다. 유료 전환·새 결제 계정·현금 초과 지출은 승인되지 않았다.
- 임시 프로젝트 `openstack-k8s-eval-b-20261026`에는 기존과 같은 Billing 연결과 Compute API 활성화만 했다. 새 프로젝트의 `CPUS_ALL_REGIONS=12`/SSD250GiB는 필요한 16 vCPU/320GiB에 부족하다. 무료 체험은 증설 요청이 불가하다. **B에 VM을 만들지 말고, 사양을 임의 축소하거나 프로젝트를 더 만들어 병렬안을 재설계하지 않는다.** 기본 네트워크는 있지만 VM·디스크는 생성하지 않았다.
- 사용자는 등록된 실험, 환경 ensure/down, 장애 주입·조치·ownership cleanup, 재개·분석을 요청했다. 필요한 통상 작업마다 재승인을 묻지 않는다. 비밀정보는 출력·커밋하지 않는다. 실험과 무관한 기존 자원을 변경하거나 삭제하지 않는다.

## 3. 마감·시간·비용

**2026-10-29 00:00 KST까지 실험·cleanup·호스트 정지 확인을 끝낸다.** 이는 수요일 10월 28일의 끝이다. 이전 10월 29일 정오 주입 마감은 폐기했다. 목·금요일은 보고서/발표자료 작성용이다.

- 새 case 시작은 10/28 21:00 KST 미만, 새 주입은 22:00 미만이다.
- 23:00에는 남은 실행을 drain하고 예외를 처리한다. 23:30까지 소유 자원 정리 상태를 남기고 host down을 개시해 자정 전에 정지 상태를 검증한다.
- 실제 준비·H·증거·cleanup/down 시간과 모든 진행 중 작업을 반영해 더 이른 gate를 적용한다. 마감에 맞추려고 H를 줄이거나 관측 중 cleanup을 회복으로 계산하지 않는다.
- 기존 48시간 상한은 보수적으로 가동 bed-hours의 합으로 유지한다. 한 bed 내 어느 VM/image builder라도 켜진 구간의 합집합을 센다. DEV·준비·유휴·중단·정리를 모두 포함한다. 44시간부터는 새 case 시작을 막고 정리 여유를 남긴다.
- candidate의 `budget_seconds=158400`은 attempt ledger gate일 뿐 클라우드 가동·금액 상한 장치가 아니다. 현재 max_case 5400초도 adapter subprocess만 제한한다. 외부 준비 작업까지 bounded하게 만들고 실제 가동 원장으로 잔여 시간을 검사한다.
- 신규 작업 비용 gate 16만 원, 정리/오차 reserve 4만 원. 실제 잔여 크레딧이 더 작으면 낮춘다. VM·디스크·IP·network·image/snapshot·기타 프로젝트 사용량·정지 후 잔여 요금을 포함한다. 크레딧 만료 전에 끝낼 수 있는지도 확인한다.
- 공식 단가상 기존 bed compute는 약 1250.38원/시간, 합산48시간 약60018원이다. 320GiB pd-balanced는 약1823원/달력일이다. 별도 요금·세금이 있고 이는 확정 청구액이 아니다. 원문 단가와 산식은 설정 문서에 있다.

기본 일정은 **33시간23.6분**, pilot wave 전체를 한 번 더 하면 **39시간36.4분**이다. 사전 구현·예외·추가 기동은 별도다. DEV 진입 시 현재 시각과 실측 기동 시간을 기준으로 마감 여유를 다시 계산한다. 시간을 넘길 전망이면 조용히 범위를 줄이지 말고 실제 가능한 완전 block·누락 범위를 제시해 협의한다. 기존 결과나 retry로 부족한 n을 채우지 않는다.

## 4. 첫 live pilot freeze 전 사전 보완

이 네 항목은 아직 완료된 기능이 아니다. 관련 코드와 tests를 확인하고 최소 범위로 구현해라. 이번에는 병렬 coordinator를 만들지 않는다.

1. **DEV 전용 실행 경로:** S1 A 경로와 공통 계측/cleanup 점검에 기존 live adapter를 사용한다. 주입 gate·환경 잠금·ownership cleanup·실패/중단 증거·예산 적용을 유지한다. `development` 결과를 명시적으로 primary에서 배제하고 campaign root 밖에 보존한다. 기존 37-case profile을 가짜 main으로 실행해 DEV라고 재분류하지 않는다. crash 후 cleanup을 재개할 수 있어야 한다. A가 보류됐다면 실제 restart 전달까지 검증됐다고 보고하지 않는다.
2. **주입 전 정상 baseline:** 각 case에서 60초의 raw를 동일 20초 bin 3개로 독립 재계산한다. 표본 완전성, bad≤.05, 성공 p95≤등록 SLO가 모두 충족돼야 주입한다. V1은 전용 SLO100ms를 쓴다. S1/S2 기존60초 raw를 활용하고 S3의30표본/S4의3표본 baseline은 보강한다. 마지막 arrival의 deadline 처리도 끝낸다. missing을 정상으로 보거나 주입 후 자료를 baseline에 넣지 않는다. `analysis.baseline_contract`는 사전 등록이며 기존 코드가 이미 강제한다고 가정하지 않는다.
3. **S1/S2 paired p95 차이:** 기존 arm별 값에서 사전 등록한 보조 차이 열을 만든다. 성공·정확·deadline 내 요청에 조건부인 p95이며 실패율/SLO피해/결측과 함께 해석한다. 유효한 첫 attempt 비교가 아니거나 값이 없으면 null을 유지한다. co-primary로 바꾸지 않는다.
4. **실행 마감 gate:** candidate의 마지막 주입 시각 외에 21시 case-start 제한과 자정까지 준비·관측·정리·down이 끝나는 조건을 구현/강제한다. DEV와 일반 case 모두 적용한다. 23시 drain 시 raw와 불완전 상태를 남기고 cleanup만 수행한다. 정상 H를 침범하는 다음 case를 시작하지 않는다.

오프라인 검증은 실제로 필요한 failure path에 집중한다: DEV primary 유입 차단과 중단 cleanup, 불완전/느린 baseline에서 주입 차단, V1 전용 경계, invalid/retry의 p95 차이 제외, 시간·예산 gate가 주입 전에 막는지. `make lint`와 관련 검증을 실행한다. 합성 검증은 새 artifact에서 하되 일반 primary에 넣지 않는다. 의미 없는 테스트를 늘리지 않는다.

수정·문서·커밋은 **pilot freeze 전에** 끝낸다. 정책과 판정 의미에 걸친 파일은 보수적으로 전체 hash를 유지한다. 검증을 우회하려고 hash 대상에서 제외하지 않는다.

## 5. profile 확정과 DEV/pilot

tracked candidate를 `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/` 아래 새 버전 파일로 복사한다. 실제 실행 checkout·operator·override·artifact root를 채우고, 실제 MHC specs와 host/image/version identity를 기록한다. candidate의 `s3_specs=[]`는 기대값일 뿐 실측이 아니다. 다르면 원인을 조사해 실제 계약을 등록하며 무관한 MHC를 지우지 않는다.

MHC readback 등 환경 관측에 필요한 기존 bed 기동은 허용된다. 이 준비 시간도 원장에 포함한다. 모든 입력과 사전 보완이 명시된 후 `readiness=confirmed`로 만든다. confirmed는 pilot 성공을 뜻하지 않는다. profile/override 버전은 freeze 뒤 수정하지 않는다.

고정 수치는 H=1200/1200/900/1200초, stable120초, bin20초, rate5/2/1/1, min100/40/20/20, deadline5초, SLO200/500/2000/2000ms, bad.05다. S1/S2 clockbound5초, S2 uploader1800초, S3 evidence60초, V1 단일후보10000rounds/4workers·SLO100ms·ratio1.5다. 세부 fault·fixture는 candidate 그대로다. P/M 결과를 본 뒤 목표를 유리하게 바꾸지 않는다. M이 정상이어도 유효한 결과로 보고한다.

DEV를 먼저 하고 다음 preparation wave를 수행한다. 각 시나리오를 별도 campaign으로 freeze한다.

- S1: 자동 smoke P 1회 + V1 pilot 1회.
- S2: P/M pair 1회.
- S3: P3600/M3600 pair 1회.
- S4: on/off pair 1회, wave 마지막.

기존 make 진입점 예시는 다음과 같다. 실제 immutable profile/campaign 절대경로를 넣고 고유한 새 디렉터리를 사용한다.

```sh
ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env \
  make graduation-fresh-validate FRESH_PROFILE=/absolute/confirmed-profile.json
ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env \
  make graduation-fresh-freeze FRESH_PROFILE=/absolute/confirmed-profile.json \
  FRESH_STAGE=preparation SCENARIO=s1 CAMPAIGN=/absolute/release/bed-a/s1-pilot-v1
ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env \
  make graduation-fresh-run CAMPAIGN=/absolute/release/bed-a/s1-pilot-v1 LIMIT=1
make graduation-fresh-report CAMPAIGN=/absolute/release/bed-a/s1-pilot-v1
```

한 case씩 실행해 독립 판정·정리와 다음 case 예산을 확인한다. 예상되는 M/off 미회복 때문에 자동 retry하거나 다음 유효 case를 영구 중단하지 않는다. cleanup 실패면 다음 case를 막고 `graduation-fresh-resume-cleanup CAMPAIGN=... CASE=...`로 소유 자원 정리만 재개한다.

전체 pilot의 유효성·안전·cleanup·fault 재현과 P/on의 H 내 회복, V1 조건과 정상 보류를 확인한다. S1 주입 오프셋≤570초, S2 조정 완료 후 안정창, S3 MHC/seed/fencing, S4 pause/Node/capacity/복원을 확인한다. 정상 baseline이 목표를 못 지키면 원인을 조사하며 목표 자동 완화는 하지 않는다. 목표 수정에는 사전 amendment와 새 pilot이 필요하다.

정책/공통 판정 코드를 바꾸면 변경 전 pilot을 그대로 이용하지 않는다. 적합한 새 release/pilot을 수행하고 예산을 다시 계산한다. 수정 전 raw와 실패를 보존한다.

## 6. 본시험 실행

최초 main 전에 모든 필수 pilot go/no-go를 완료한다. main freeze에는 해당 `PILOT_CAMPAIGN`, 공통 `POLICY_MANIFEST`를 전달한다. 시나리오별 main freeze가 가능하지만 공통 정책은 같아야 한다. S1 두 세션은 **하나의 main freeze**로 진행한다.

- S1 SESSION-A: V1 main2 + block1 M→A→P = 5개.
- S1 SESSION-B: block2 A→P→M, block3 P→M→A = 6개.
- S2: P/M, M/P, P/M = 6개.
- S3: M3600/P3600, P3600/M3600, M3600/P3600 = 6개.
- S4: off/on, on/off, off/on = 6개, 마지막.

case ID·seed·순서는 candidate의 schedule 그대로다. 다른 시나리오를 동시에 같은 bed에 주입하지 않는다. 세션 사이 전체 health/placement gate를 통과하고 host 수명10시간·headroom2시간을 유지한다. 재기동 후 `cpuPlatform` 변화 등 identity 불일치를 우회하지 않는다. 실제 재기동 때 달라지면 cohort를 이어 붙이지 않고 원인·남은 선택지를 보고한다.

모든 case는 회복해도 H까지 관측한다. 미회복은 recovery time null이며 H로 대체하지 않는다. safety, validity, fault/impact 재현, recovery, cleanup을 분리한다. A의 `intervention_delivered=false`를 삭제하지 않으며 그 비교는 배정 정책 비교이지 실제 restart 효과가 아니다.

첫 attempt만 primary다. 무효 첫 attempt가 있으면 그 block은 불완전하다. retry 최대1회는 명시적으로 선택하는 보조 자료이고 primary를 대체하지 않는다. 유효한 미회복을 좋은 결과가 나올 때까지 반복하지 않는다.

## 7. 중단·수정·증거 보존

- 소유권 불명, cleanup 실패, 안전 위반은 해당 시나리오/환경을 막고 증거 보존과 소유 자원 정리부터 수행한다.
- clock bound 반복 실패나 probe 결함을 SLO 변경으로 덮지 않는다.
- 첫 main 후 공통 정책/판정을 바꿔야 하면 별도 개발 checkout에서 수정하고 새 release로 검증한다. 예전 완료 main은 원래 release 결과로 보존하며 새 결과와 섞지 않는다. 단일 공통 policy의 S1~S4를 완성하려면 모두 동일 새 release가 필요하다. 시간·비용·마감 밖 재평가나 축소는 사용자와 협의한다.
- 진행·비용·실제 host 가동·다음 명령·소유 자원·cleanup 필요 상태를 artifact progress 파일에 지속 저장한다. 다른 실행자가 재개할 수 있어야 한다.
- 운영 중 의미 있는 진행과 실패·계획 변경을 사용자에게 알린다. 장시간 CLI는 살아 있는 프로세스인지 확인하며 기다리고, 새 사용자 지시를 반영한다.

## 8. 결과·정리·인계

각 campaign의 `fresh-report.json`, `run-results.json`, `attempt-ledger.json`, `paired-contrasts.json`, `missingness.json`, `claim-coverage.json`, `report.md`와 원자료·hash·환경 identity·freeze manifest를 보존한다. release 요약은 별도 artifact 경로에 작성한다. case별 first attempt·retry·제외 이유·미완료 block과 실제 주장을 연결한다.

S1 P–M은 자동 정책의 효과, P–A는 더 단순한 재시작 배정 정책과의 차이, V1은 정해진 host-only 조건에서의 보류 사례다. S2는 서비스 피해와 업로드 goodput을 함께 본다. S3는 read availability와 seed 보존/fencing이며 ACK-loss나 write durability 입증이 아니다. S4는 기존 MHC/CAPI/CAPO 복구 설정의 효과이며 새로운 복구 알고리즘을 입증하는 것이 아니다. n=3은 일반 신뢰도나 모든 장애에 대한 강건성의 증명이 아니다. 사람 대비 속도 주장도 하지 않는다.

29 main/8 preparation/DEV/합성/과거 데이터를 구별해 완료·미완료 수를 보고한다. pilot·retry를 합쳐 n을 부풀리지 않는다. 효과가 없거나 장애 조건이 재현되지 않아도 그대로 기록한다.

마감 전에 fixture·worker 제어·MHC·taint·qdisc·QoS·볼륨/VM 소유 자원의 cleanup 상태를 확인하고, 기존 testbed는 정상 down 절차로 정지한다. 기존 persistent 인프라를 통째로 삭제하지 않는다. 가동·잔여 과금·미정리 항목과 다음 조치를 남긴다. B에는 새 유료 자원을 만들지 않는다.

호스트 정지 후 report는 frozen checkout에서 재실행할 수 있다. 보고서·발표자료는 다른 checkout/산출물 경로에 쓴다. frozen 소스와 hash 대상 docs를 수정해 재현성을 깨뜨리지 않는다. 연구 결과 요약·한계·후속 분석 위치를 인계하고, 새 코드 커밋은 저장소 컨벤션대로 본문과 검증 결과를 포함한다.
