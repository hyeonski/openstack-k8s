# 새 평가 체계 구축 상세안

작성: 2026-10-26. 설계·작업 명세이며 실제 최종 합의 상태와 승인본 hash는 [협의 기록](consensus-discussion-2026-10-26/README.md) 참조. 구현·실험은 아직 수행하지 않았다.

사용자가 기존 결과를 제외해도 된다고 허용한 뒤 작성한 변경안이다. [원 연구 합의안](consensus-research-plan-2026-10-26.md)의 연구 원칙·전체 실험 카탈로그는 유지한다. 이전 실행안의 ‘기존 34건 + S1 추가’ 구성은 이 문서와 [새 실행 상세안](fresh-evaluation-run-plan-2026-10-26.md)의 fresh cohort 구성으로 대체한다. 원래 승인 문서는 hash와 함께 보존하며 소급 수정하지 않는다.

## 1. 자료 사용 정책과 범위

기존 34건은 삭제하지 않고 개발 이력으로 보존한다. 새 논문의 primary 결과·비교·그림·표본 수에는 포함하지 않는다. 이는 결과의 좋고 나쁨에 따른 선택이 아니라 본시험 전에 정한 프로토콜·계측·버전 통일 결정이다. 과거 자료를 이미 보았다는 사실과 그것이 설계에 영향을 주었다는 사실을 공개한다. 새 run을 완전히 사전 지식 없는 확증 연구로 부르지 않는다.

기존 코드는 재사용하되 기존 결과 파일은 새 campaign 입력으로 받지 않는다. calibration·개발 smoke·연습·본시험의 용도를 manifest로 분리한다. primary에 부적절한 결과가 섞이면 보고서 생성이 실패해야 한다. 기존 자료를 새 지표로 재해석해 빈 cell을 메우지 않는다.

20시간 등 제한 때문에 S1만 새로 수행하면 S2~S4의 새 primary 증거는 없는 상태다. 과거 S2~S4를 별도의 ‘개발 cohort·탐색적 참고’ 부록에 둘 수는 있지만, 새 평가의 완료 표시에 합산하지 않는다. 기존 자료 전체를 가리는 것을 논문 품질 개선으로 자동 간주하지 않는다.

전체 작품을 새로 평가하는 기본 연구 범위는 S1~S4의 한정된 비교다. S1-only는 시간 제약용 부분 평가이며 전체 작품 평가 완료로 표시하지 않는다. 더 강한 정보 제거·요인 실험·신뢰도·환경 전이는 원 연구 계획의 확장 항목으로 남는다.

## 2. 구성과 데이터 흐름

`profile/순서 계약 → campaign runner → fixture·주입기 → 정책/비교군 → 독립 관측 → raw archive → 독립 판정 → 분석·주장 표`

runner가 주입 원인을 알더라도 정책에는 허용된 증상·상태만 전달한다. 판정기는 주입 정답과 raw를 볼 수 있지만 정책 결과의 success flag를 정답으로 삼지 않는다. 정리 동작과 평가 대상 복구 동작을 별도 actor·시각으로 기록한다.

기존 raw를 전역 schema로 전부 재작성하지 않는다. 독립 판정기의 정규화 adapter가 원자료를 읽어 공통 사건·요청·판정 view를 만든다. 아래 증거 계약은 이 정규화 출력과 manifest의 계약이다. adapter로 복원할 수 없는 필드만 실행 코드에 추가하며 원자료 파일은 원형 그대로 보존한다. 각 정규화 값에 raw 파일·필드·변환 규칙을 남긴다.

모든 case는 `PREPARED → BASELINE → INJECTED → OBSERVING → HORIZON_END → CLEANUP → VERIFIED`를 기록한다. 정책이 일찍 회복해도 비교군과 같은 관측 구간을 유지한다. 중간 실패는 attempt를 보존한 채 cleanup으로 이동한다. cleanup 실패 시 다음 case를 시작하지 않는다.

## 3. 파일별 작업 명세

아래 신규 이름·옵션은 구현 대상이며 현재 사용할 수 있는 명령이라고 간주하지 않는다.

| 작업 | 파일/영역 | 변경 사항 | 완료 조건 |
|---|---|---|---|
| B01 계약·스케줄 | `config/graduation-evaluation-fresh.json` 신규, `evaluation/graduation_evaluation.py`, shell/make 진입점 | 명시적 case 목록·block·purpose·seed·군·H·계측·SLO; 선택 profile을 freeze에 전달하고 복사/hash | 잘못된 schema·중복 ID·없는 군·미확정 parameter를 freeze 전에 거절 |
| B02 사건·요청 계측 | S1 loadgen, S2 probe, S3 실행기, 공통 evidence helper | 예정/실제 시작/완료·주입 적용·통보·진단·조치·회복 확인의 의미 분리; 단위/clock/source | fake clock·지연·누락·중복으로 사건/latency 재계산 가능 |
| B03 S1 비교군 | `evaluation/graduation_evaluation_case.py`, S1 실행 경로 | P와 기존 no-action M을 새 계약에 연결하고 A를 추가. M은 관측 동일·조치 억제; A는 동일 worker에 정확히 한 번 재시작 | node/VM/host 유지, Pod 교체, action 수, 실제 경합 유지 검증 |
| B04 host-only | S1 fixture/profile·case 판정 | 제한된 pilot parameter 후보, host 경합+서비스 정상 조건과 보류 판정 | 조건 불성립·예외 중단·정상 보류·오조치가 서로 다른 결과 |
| B05 판정·분석 | `graduation_evaluation_verify.py`, report, 분석 모듈 | mode별 계약 검증과 성능 결과 분리, profile 기반 표본 수, paired 분석, 미회복·결측 처리 | runner summary를 바꿔도 raw 판정은 동일, raw 결함은 검출 |
| B06 lifecycle·검증 | runner·freeze·cleanup, `tests/test_graduation_evaluation.py` 및 관련 tests | active source/profile 검증, 재개·새 attempt·source 변경·정리 실패 | 중복 side effect/묵시적 덮어쓰기 없음, 오염 상태 다음 run 금지 |
| B07 사람 선택 | 별도 manual case adapter·공통 안전 executor·audit | 증상 통보, 사람이 결정한 명령, 승인/거절·시작/종료·검증 기록 | 실제 사람 입력 없이 H 완료 불가; 정답 노출 H-D/H-E 구분 |
| B08 S2 신선 비교 | S2 fixture·case·판정 | M과 P를 각각 fresh fixture에서 실행, 동일 관측·부하·time budget | 기존 순차 stage를 독립 표본으로 재명명하지 않음; byte와 지연 재계산 |
| B09 S3 신선 비교 | S3 fixture·case·판정 | M3600/P3600, 연속 read probe, 사건 기록 정정, bounded 관측·안전 cleanup | M에서 fencing·out-of-service 없음; P의 fencing 순서와 seed 검증 |
| B10 S4 신선 비교 | S4 fixture·workflow·판정 | MHC on/off만 달리한 paired case, 서비스와 capacity 관측 | 제어기 설정 확인·복원; capacity readiness와 서비스 분리 |
| B11 transient 선택 | S3 주입/해제 hook·case·판정 | 사전 사건 경계의 early/late 해제와 실제 적용 시각 | 미래 정보가 정책에 유출되지 않고 예외/보류/조치를 구분 |

현재 확인한 구현상 함정:

- `verify_s1()`은 요청 수 5,400을 하드코딩한다. 새 부하 시간에 맞춰 profile과 실제 loadgen semantics에서 기대 index 집합을 계산해야 한다. 기존 버전 검증은 분리 보존한다.
- case 실행에는 `runner.run(seconds=1080)`도 하드코딩돼 있다. profile만 1,800으로 바꾸지 말고 실제 실행 인자까지 전파한다. warmup을 별도로 더하지 않는 현 의미에서 rate 5×1,800=9,000개이며, warmup 의미를 바꾸면 기대 수 산식도 변경한다.
- `schedule()`의 고정 mode 쌍·qualification ID 조회는 새 구성에서 KeyError를 일으킬 수 있다. 명시적 cases와 dependency로 대체하고, 구 profile의 34개 ID 재현을 회귀 검증한다.
- `PROFILE`과 source 목록이 고정돼 있다. 새 profile을 읽기만 하고 hash에서 빠뜨리지 않는다. 실제 선택된 설정·분석 규칙·fixture가 모두 freeze 대상이어야 한다.
- 현재 S2 검증은 fixed/dynamic 등 stage 이름·회복 성공을 전제한다. M을 해당 검증에 통과시키려고 목표를 바꾸지 말고 mode별 계약을 만든다.
- S3 검증은 회복 성공을 전제한다. 관측 H 내 미복구가 예상되는 M도 실험 계약을 정상 수행할 수 있다. `trial_valid`와 `recovered`는 별개다.
- S3 `node_not_ready_at`의 기존 의미는 진단완료다. 새 필드에 실제 관측 시각을 기록하고 schema version을 올린다.
- CLI는 현재 `freeze/run/status`, `--campaign`, `--limit` 등을 제공한다. 새 `--profile`, dry-run 등의 인터페이스는 구현·help 검증 전에는 실행 지침으로 제시하지 않는다.

## 4. 증거 계약

| 파일 | 필수 내용 |
|---|---|
| `campaign.json` | schema/cohort ID, source·profile·analysis hash, seed, ordered cases, 범위·사람 참여·추정 예산 |
| `attempts.jsonl` | case/block/attempt ID, purpose, actor, 시작·끝, 원인 분류, 이전 attempt 연결, 실행 결과 |
| `environment.json` | 실제 버전·image digest·자원·배치·identity·controller/timer·계측 경로 |
| `events.jsonl` | event ID·의미·UTC·process monotonic·clock ID·관측자·대상 UID·request ID·원자료 출처 |
| `requests.jsonl` | request ID·예정/시작/완료·deadline·상태·정확성·error·payload/byte·generator rejection |
| `observations/` | host/VM/Node/Pod/port/volume/controller의 시각 있는 raw |
| `decisions.jsonl` | 정책이 실제 읽은 신호·판단·대상·요청/응답; 주입 정답 유출 금지 |
| `cleanup.json` | 주입·QoS·taint·MHC·Pod/volume 상태의 전후와 ownership·잔존물 |
| `judgement.json` | trial_valid·fault_realized·impact_realized·recovered·safety·execution·missing·근거 파일 |
| `metrics.json` | 각 지표 값/단위/구간/계산 가능성/관측 한계; null과 0 구분 |
| `manual.jsonl` | 참여자 익명 ID·숙련도·통보·명령·정정·검증·작업 구간; 비밀정보 제외 |

정책 summary와 독립 판정의 불일치를 덮어쓰지 않는다. 외부 조치·정리·수동 구조 개입 이후의 정상화를 자동 복구 시간에 넣지 않는다. artifact는 attempt별 새 경로에 저장하며 report는 frozen campaign의 명시적 case만 읽는다.

## 5. 지표·판정 구현

공통 primary는 사전 H 내 안전 회복 여부와 서비스 영향이다. S1은 P-M과 P-A를 사전 contrast로 고정한다. 사람 선택 시 H-P는 별도 contrast다. S2는 API 오류/지연과 uploader goodput을 함께, S3는 read 가용성·seed 보존·fencing 순서를, S4는 서비스와 usable capacity를 나눠 보고한다.

요청 기반 지표는 예정 arrival을 분모에 포함한다. generator 포화는 별도 원인으로 기록하며 서비스 실패와 함께 숨기지 않는다. primary latency는 예정 arrival부터 완료까지, 실행 시작부터의 latency는 보조로 둔다. 누락·미완료·deadline 초과는 성공 지연 분포에서 지워 효과를 좋게 보이지 않도록 실패율·미완료 수를 함께 표시한다.

영향 시작, 지속 회복 구간 시작, 안정 확인 완료를 구별한다. H를 끝까지 관측하고 회복 후 재악화도 기록한다. 미복구의 recovery time을 H로 치환해 평균을 내지 않는다. 성공 run 시간은 조건부 통계, 전체 결과는 H 내 회복 비율·raw 점·paired 차이와 H 내 피해 지표로 보고한다.

SLO 위반 시간 D는 연속 관측과 고정 bin이 확보된 경우에만 계산한다. 결측은 불명으로 남기고 관측된 위반 시간의 하한과 미관측 시간을 병기한다. S3 연속 read probe는 DB read availability의 표본이지 지속 write 내구성 검증이 아니다. 외부 ACK 원장을 구현하지 않으면 ACK 무손실 주장은 계속 제외한다.

판정 축은 `실험 유효성`, `장애/영향 재현`, `서비스 결과`, `안전`, `실행 종료`, `정리 상태`다. no-action 미복구는 유효한 비교 결과다. 예외로 멈춘 run은 성공 보류로 바꾸지 않는다.

## 6. 반드시 할 검증

| 검증 입력 | 기대 결과 |
|---|---|
| 정상 회복 trace, 중간에 잠깐 정상 후 재악화 | 전자는 지속 회복, 후자는 첫 정상 순간을 최종 회복으로 삼지 않음 |
| H 끝까지 미복구한 M | trial_valid=true, recovered=false; 계약 실패로 삭제하지 않음 |
| 잘못된 대상 재시작·불필요한 fencing | 가용성이 좋아져도 안전/대상 판정 실패 |
| timestamp 필드 순서 역전·다른 host monotonic 혼용 | 지표 계산 거절 또는 불명; 음수시간을 정상값으로 보정하지 않음 |
| request 누락·중복·queue 지연·inflight rejection | 각각 검출, 예정 수와 실제 수·실패 분모 일치 |
| source/profile 변경·과거 artifact 혼입 | campaign/report 검증 거절 |
| 구 profile의 일정·새 1,800초 S1 증거 | 구 34개 ID 재현, 새 9,000개 요청 검증. 다른 rate·duration에서도 하드코딩 없이 동작 |
| 적용 후 응답 소실·재개 | side effect raw 확인 후 판단; 무조건 중복 요청하지 않음 |
| cleanup 중단·controller 설정 미복원 | 다음 case 차단, 마지막 시도 보존 |
| 실제 사람 슬롯 결측 | H 미실행, P-M/P-A 유지, 자동 대체 금지 |

위 항목은 평가기를 검증하기 위한 테스트다. 그 자체로 제품의 모든 API 실패·동시성 조건이 실증됐다고 주장하지 않는다. 필요한 작은 fake trace와 mock을 만든 후 관련 기존 테스트와 신규 검증 테스트를 실행한다. 구체적인 test ID는 구현 PR에서 이 표에 연결한다.

## 7. 작업 순서와 완료 gate

1. **B01:** 선택한 범위·cases·schema·분석 계약 초안. 결과: profile validator와 dry schedule. live 실행 금지.
2. **B02:** 사건 의미 감사·계측 수정. 결과: raw에서 지표를 재구성할 수 있는 합성 trace.
3. **B03/B04:** S1 군·음성 조건. 결과: mode 차이가 목표 조치에 한정됨을 mock과 fixture snapshot으로 확인.
4. **B05/B06:** 독립 판정·lifecycle. 결과: 위 검증 표 통과 및 기존 계약과 구분.
5. **B08~B10:** 전체 평가 선택 시 S2~S4 군을 구현. 결과: 각 군의 cleanup·H 종료·실패 판정 확인.
6. **B07/B11:** 선택된 사람/transient만 추가. 결과: 참여·통보/audit 또는 해제 hook 확인.
7. **개발 smoke·calibration:** 기능 동작·측정 가능성·조건 성립·실제 시간을 확인. 본시험 표본 아님.
8. **시나리오별 main freeze:** parameter·분석·순서·source·예산을 고정. S1의 모든 block·세션은 같은 freeze를 사용한다. 다른 시나리오는 독립 freeze를 허용하되 모든 정책 hash는 공통으로 고정한다. 실행 상세안의 gate를 통과한 뒤 본시험 진입.

단계의 완료는 문서 작성이 아니라 산출물·검증 결과로 판정한다. 미구현 옵션, null인 필수 값, 준비 실패가 있으면 freeze를 금지한다. 정책 개선이 필요하면 별도 버전으로 만들고 같은 cohort에서 개선 전후를 섞지 않는다.

B01에 앞서 개발/실행 checkout, artifact 경로, `ENV_OVERRIDE_FILE` 경로를 분리·검증한다. 이 준비 노동은 B06 추정에 포함한다. 신규 군의 live pilot은 기능·정리 검증을 겸하지만 본시험에서 제외한다. pilot도 완전한 설정의 별도 manifest를 갖고, pilot 이후 main용 설정을 새로 freeze한다. 활성 campaign의 hash 대상 파일을 변경하면서 계속 실행하지 않는다. 명령 문법은 구현 후 생성한 `--help`와 합성 실행으로 확인하여 실행 상세안의 명령 부록에 붙인다.

policy manifest는 최초 main 전에 고정한다. 판단·조치·guard 코드, threshold, 허용 정보와 정책 parameter를 포함하며 시나리오별 freeze 사이에서 같아야 한다. 사전 등록한 calibration 대상은 실험 부하·주입·측정 설정으로 구분하고 정책 튜닝을 몰래 포함하지 않는다. 평가 도구 수정은 allowlist·diff·영향 분석을 남기고 해당 시나리오의 새 cohort로 수행한다. 공통 판정 의미를 바꾸거나 정책 파일을 수정하면 단순 도구 수정으로 취급하지 않고 연구 release와 영향을 받는 비교를 다시 설계한다.

## 8. 노동 추정과 아직 확정되지 않은 입력

새 계약·계측·M 비교를 포함하므로 예전 18~23h를 그대로 적용하지 않는다. 초기 구현 분해 추정은 B01 2~3h, B02 4~6h, B03 4~6h, B04 2~3h, B05 5~8h, B06 3~4h로 **S1 공통 체계 20~30h**다. 사람은 추가 6~8h, 전체 S2~S4 군·판정·검증은 추가 10~16h, transient는 추가 3~5h를 잠정 잡는다. 실제 착수 전 코드 분해·개발 smoke 후 재산정하며 완료를 보장하는 수치가 아니다.

아래 값은 본시험 결과를 보기 전에 확정해야 한다. 미확정 상태를 숨기지 않고 profile validator가 차단하도록 한다.

| 입력 | 결정 시점·근거 |
|---|---|
| 실제 제출/종료·비용·사람 슬롯 | 실행 착수 전 사용자/운영 일정 |
| 실제 버전·controller·배치·timer | 환경 snapshot, 목표 profile과 대조 |
| H·안정창·bin·SLO·minimum samples·deadline | 현 계약 의미 감사와 독립 calibration; 본시험 전 freeze |
| 장애 강도·V1 후보와 유효 조건 | pilot 이전 후보 목록, pilot 이후 main 값 고정 |
| S2의 초기 workload/port/QoS·공유 부하 trace | 별도 pair pilot과 실제 설정 snapshot |
| 세션별 실제 run/cleanup 비용 | 개발 smoke와 pair pilot, 예산 재계산 |
| seed·군 순서·재시도 상한·선택 옵션 | 본시험 전에 명시적 manifest로 확정 |

‘설계·작업 명세가 문서화됨’과 ‘환경 의존 값까지 검증되어 즉시 실행 가능함’은 다르다. 이 문서는 전자를 완성하기 위한 상세안이며 후자는 구현·pilot 완료로만 판정한다.
