# 평가 체계 공동 구현 리뷰 및 실행 인계

기준 구현: `11471b3`. 사용자가 지정한 기존 Claude CLI 세션 `0effb442-3fcd-4249-a986-8281729d054c`를 재사용했다. 1차 독립 리뷰, 2차 반론·수정 원칙 합의, 3차 수정본 재검토를 완료했다. 최종 수정본 재검토 및 검증 결과는 아래에 기록한다. 클라우드 기동·장애 주입·live pilot·본시험은 이번 로컬 검증에 포함되지 않는다.

## 수정한 실행·판정 결함

| 영역 | 수정 | 검증 의미 |
|---|---|---|
| S3 실행 | `digest` 지역 변수와 함수 충돌로 seed 생성부터 중단하던 오류 수정 | 실제 `FreshS3.finish`의 SQL seed·MHC 비교 경로를 외부 API mock으로 실행 |
| S4 off 정리 | H 뒤에도 pause 유지. 소유 VM 시작→Node Ready→MHC 복원. 시작 응답 소실 후 재개도 Ready 재확인 | unhealthy 상태에서 unpause하면 삭제 race가 발생하는 mock controller와 실제 cleanup 경로 검증 |
| S2 관측 | H 뒤 clock bound+deadline+3초 tail 확보. primary 창은 동일 H. 진척 누락은 독립 판정 missing으로 보존 | receiver clock −1.5초인 trace의 마지막 arrival 누락 재현 |
| S3 seed | read 요청 deadline과 별도의 증거 수집 timeout. 회복 후 seed 조회 불가는 안전 불명, 실제 변조는 안전 실패 | unknown과 corruption 구분. 미회복 M의 조회 불가만으로 trial을 무효화하지 않음 |
| 캠페인 종료 | malformed JSON도 invalid 판정·raw hash·finished 상태로 닫음 | `running`으로 남아 다음 freeze를 막는 교착 재현 |
| freeze | pilot/previous ID 분리, 해당 시나리오의 pilot–main 계약 비교, profile 차이 기록 | H/SLO/bin/허용률/deadline/clock/fixture/V1/timer 변경은 새 pilot 필요 |
| 증거 보존 | Git ignored 로컬 override·생성 비밀파일을 source snapshot에서 제외 | 선택 profile과 override 자체는 기존처럼 별도 hash 고정 |
| 주입 gate | 긴 준비 후에도 H·cleanup 및 S2 관측 tail을 호스트 종료 전 확보하는지 재확인 | 초기 환경 준비 시각의 여유만 믿지 않음 |
| 분석 | 사건별 관측 경과 시간, paired arm 결과·D·SLO 위반·S2 goodput·S4 capacity 추가 | 미회복 군의 recovery time을 H로 대체하지 않고도 피해 차이를 보고 |

`tests/test_fresh_evaluation_live_review.py`가 이번 공동 리뷰의 회귀 테스트다. 합성 검증은 실험 결과가 아니다.

## 논의하여 유지한 분석 원칙

- **A군:** 같은 진단 guard 뒤 같은 worker 재시작 정책에 배정된 군이다. 보류를 무효로 지워 조치된 run만 선택하지 않는다. `intervention_delivered=false`와 P–A 비교의 주장 제한을 자동 기록한다. 미전달 block은 실제 재시작의 효과가 아닌 배정 정책의 비교다.
- **retry:** 첫 attempt만 primary이고 모두 공개한다. 첫 attempt가 무효면 완전한 paired n은 3 미만이 될 수 있다. retry는 그 block을 채우지 못하며 보조 자료로만 남는다. 비용을 감수할지 case별 명시적으로 결정한다.
- **hash:** 판단·guard와 도구가 섞인 파일은 보수적으로 전체를 정책 hash에 둔다. 이를 빼서 기존 연구 release에 수정을 몰래 섞지 않는다. 정책/공통 판정 변경은 새 release가 필요하다.
- **동결 범위:** 실행 checkout의 코드와 hash 대상 docs도 동결한다. 확정 profile은 `.state/<환경>/evaluation-profiles/`처럼 source 검색 범위 밖에 둔다. 토론·결과 서술은 다른 checkout이나 artifact 경로에서 작성한다.
- **재분석:** 현재 `report`는 동결 당시 구현을 요구한다. 사후 분석 코드 결함을 발견하면 frozen 결과를 덮어쓰지 않고 결함·영향·한계를 보고한다. 버전별 독립 reanalysis 기능은 이번 범위 밖이다.
- **V1 재후보:** 현재 새 preparation은 S1 smoke도 포함한다. 추가 후보 pilot 비용은 V1 28분만이 아니라 smoke 45분을 합친 잠정 73분+여유다. 기본 29 main+8 preparation에는 포함되지 않는다.

## 새 profile 입력과 판정 계약

1. 모든 시나리오: `horizon_seconds`, `stable_seconds`, `bin_seconds`, `min_samples`, `deadline_seconds`, `slo_ms`, `bin_max_bad_fraction`을 명시한다. bin bad는 오류·잘못된 응답·deadline 초과·SLO 초과의 합집합. healthy는 완전한 bin, 허용 bad 비율 이하, 성공 요청 p95≤SLO를 모두 요구한다. 실패율과 SLO 위반 비율은 별도 지표다.
2. S1/S2: 원격 clock offset/왕복 불확실성 상한을 측정한다. `schedule`/`validate`의 `bin_contracts`에서 bin당 표본 수·허용 bad 정수 건수를 확인한다. 1 rps의 짧은 bin에서는 p95가 사실상 최댓값에 가까울 수 있다.
3. V1: 사전 후보와 선택값, `v1_condition.slo_ms`, `bin_max_bad_fraction`을 별도로 정한다. `baseline_p95_ratio=1.5`는 고정 S1 정책과 같다. 정책 baseline 60초와 실제 관측 창을 raw에서 재계산하고 절대/상대 조건을 함께 검증한다.
4. S3: 실제 MHC specs, 3600초 toleration, force-detach 비활성 상태, `evidence_timeout_seconds`를 등록한다. read probe timeout을 1,000행 seed 최종 수집에 재사용하지 않는다.
5. 환경/운영: override·실행 checkout·artifact root·운영자·예산·cleanup 여유·마지막 주입 시각, fixed fixture와 fault를 등록한다. 보정 값은 과거 성능이나 합성 trace에서 채우지 않는다.

`readiness=confirmed`는 필수 입력이 명시됐다는 뜻이며 live pilot 성공을 대신하지 않는다. main은 해당 시나리오의 유효한 pilot 결과와 동일한 측정·주입 계약을 요구한다. 변경이 필요하면 기존 raw를 보존하고 새 preparation에서 다시 검증한다. 다른 시나리오의 calibration 값과 운영 예산 변경은 manifest의 `pilot_profile_changes`에 공개한다.

## 실행 순서

1. 변경을 실행 checkout에 반영하고 로컬 검사를 통과시킨다. 기존 미완료 fixture·실행 process가 없는지 확인한다. greenfield 전용 환경 override를 사용한다.
2. source 범위 밖에 확정 profile을 만들고 운영·측정 입력을 채운다. 이 문서의 경로 변수는 실제 절대경로로 설정해야 한다.

```sh
# PROFILE: 확정 profile, OVERRIDE: 같은 환경의 override, RELEASE: 새 artifact root
make graduation-fresh-schedule FRESH_PROFILE="$PROFILE"
make graduation-fresh-validate FRESH_PROFILE="$PROFILE"

ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-freeze FRESH_PROFILE="$PROFILE" FRESH_STAGE=preparation SCENARIO=s1 CAMPAIGN="$RELEASE/s1-pilot"
ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-run CAMPAIGN="$RELEASE/s1-pilot" LIMIT=1
# 첫 smoke 증거/cleanup 확인 후 V1 pilot
ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-run CAMPAIGN="$RELEASE/s1-pilot"
make graduation-fresh-report CAMPAIGN="$RELEASE/s1-pilot"

ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-freeze FRESH_PROFILE="$PROFILE" FRESH_STAGE=main SCENARIO=s1 CAMPAIGN="$RELEASE/s1-main" PILOT_CAMPAIGN="$RELEASE/s1-pilot" POLICY_MANIFEST="$RELEASE/s1-pilot/policy-manifest.json"
# SESSION-A 5개: V1 2 + 첫 P/M/A block
ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-run CAMPAIGN="$RELEASE/s1-main" LIMIT=5
make graduation-fresh-report CAMPAIGN="$RELEASE/s1-main"
# SESSION-B 6개: 같은 freeze, 같은 checkout
ENV_OVERRIDE_FILE="$OVERRIDE" make graduation-fresh-run CAMPAIGN="$RELEASE/s1-main" LIMIT=6
make graduation-fresh-report CAMPAIGN="$RELEASE/s1-main"
```

3. S2→S3→S4 순서로 각각 preparation pair를 freeze/run/report한 뒤 main 6개를 새 manifest로 freeze/run/report한다. `SCENARIO`와 campaign 경로를 해당 시나리오로 바꾸며 공통 `POLICY_MANIFEST`는 최초 준비 manifest와 같아야 한다. pilot·main에 쓰는 해당 시나리오 계약은 동일해야 한다. S4는 마지막이다.
4. 원자료와 함께 각 campaign의 `fresh-report.json`, `run-results.json`, `paired-contrasts.json`, `missingness.json`, `claim-coverage.json`, `report.md`를 사용한다. S1 11, 나머지 각6 main을 scenario별로 확인한다. 서로 다른 scenario의 요청/시간을 표본으로 풀링하지 않는다. pilot·과거 결과·합성 결과는 primary에 넣지 않는다.
5. interruption/cleanup 실패는 `graduation-fresh-resume-cleanup CAMPAIGN=... CASE=...`로 정리만 재개한다. 결과 확인 후 무효 case의 보조 retry가 필요하면 `graduation-fresh-run ... CASE=...`를 명시한다. 유효한 미회복은 재시도 대상으로 바꾸지 않는다.

## pilot에서 확인할 운영 한계

- 실행 예산 gate는 attempt 원장의 경과 시간과 다음 case의 등록 상한으로 진입을 판단한다. 클라우드 청구 총액이나 호스트 유휴 시간을 실시간 합산하는 비용 계량기는 아니다. 환경 준비·정리 시간은 실제 pilot으로 다시 산정한다.
- S1은 주입 provisioning 후에도 총 1,800초 load 안에 H와 종료 확인 시간이 남아야 한다. S2는 진단·분리·rate 조정 뒤 안정창이 남는 H를 확인한다.
- S3의 Kubernetes exec probe와 S4의 API proxy probe는 해당 경로의 비용을 포함한다. 네이티브 DB/외부 서비스 클라이언트 latency로 확대 해석하지 않는다.
- S1은 세션 사이 GCP `cpuPlatform`까지 동일한 host identity를 요구한다. 재기동 때 플랫폼이 바뀌면 실행이 차단된다. pilot에서 확인하고 실제로 달라지면 기존 cohort를 조용히 이어가지 않는다.
- S4 pause의 설치 버전 동작, VM/Node 회복과 MHC 복원, 실제 usable capacity는 live pilot에서 확인해야 한다.
- 29 main+8 preparation 일정은 유지한다. 기간 추정은 실제 pilot 측정 전까지 잠정값이며, 미확정 입력을 합성값으로 채워 즉시 실행 가능하다고 표시하지 않는다.

## 검증·재검토 증거

원문 CLI 대화와 로그는 Git에서 제외된 `artifacts/fresh-claude-review-2026-10-26/`에 보존한다. 이 문서는 합의 내용과 실행 절차만 추려 기록한다. 최종 검증과 Claude 수정본 확인 결과는 다음과 같다.

| 확인 | 결과 |
|---|---|
| `make lint` | **284 tests OK**, shell 검사 통과; 평가 관련 59개 포함 |
| 실제 CLI 합성 main | 29개 freeze→run→report, 29개 유효, primary sample count 0 |
| 실제 CLI 합성 preparation | 8개 freeze→run→report, 8개 유효, primary sample count 0 |
| 일반 report에 합성 입력 | exit 2로 거절 |
| draft live validation | exit 2로 미확정 입력 거절 |
| 기존 승인 구축·실행 문서 | round-07 hash와 일치 |
| whitespace | `git diff --check` 통과 |
| Claude 3차 리뷰 | 차단 결함 없음; 수정 원칙/코드 일치, 확정 profile 후 live pilot 진입 준비 상태에 동의 |

검증 파일: `make-lint-final.log`, `validation/commands.json`, `validation/validation-summary.json`, `approved-plan-check.json`. Claude는 읽기 전용 코드 리뷰를 수행했고 테스트 실행은 Codex가 수행했다. `review-01/02/03-prompt.txt`, `review-01/02/03-response.json` 및 추출 Markdown이 원문 대화다.

Claude의 선택적 제안 두 가지는 적용하지 않았다. 주입 전 milestone을 오류로 처리하는 현재 동작은 프로토콜 시각 오류를 숨기지 않는 보수적 판정이다. 추적된 필수 소스 파일이 없을 때 freeze를 실패시키는 것도 불완전한 checkout을 허용하지 않는 동작이다. 현재 실행 경로에 장애가 되는 결함으로 판단하지 않았다.

최종 합의는 **“로컬 검증을 마쳤고, 필수 입력을 명시한 profile로 live pilot에 진입할 준비가 됐다”**이다. 아직 live pilot이나 본시험의 성공을 확인한 상태는 아니다. 이번 변경은 기존 결과를 새 지표로 재사용하지 않으며, S1~S4 29개 main과 8개 preparation의 범위를 유지한다.
