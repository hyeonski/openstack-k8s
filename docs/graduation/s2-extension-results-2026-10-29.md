# S2 extension 실행 결과 — 2026-10-29

환경 재기동은 **16:08:28 KST에 성공**했지만, S2 extension 네 case는 각 1 attempt 모두 **장애 주입 전 준비 실패로 무효**가 됐다. 고정 profile의 `read_identity.environment_run_id=env-8093c4a92ee7`과 새 환경 `env-aef5b165ff9f`가 달라 Neutron 준비 검사에 앞선 하네스 identity guard가 준비·정리를 거부했다. 각 case에 `resume-cleanup`을 1회씩 수행해 모두 `VERIFIED`, `cleanup=true`로 봉인했고 **17:15:49 KST에 기존 VM 3대 TERMINATED 및 원장 종료를 확인**했다. S/P 성능 측정값은 없으며 QoS 필요성에 관한 새 근거를 얻지 못했다.

## 고정 조건과 직전 시도

- 브랜치: `codex/fresh-evaluation-execution-20261026`. 이번 실행 시작 HEAD는 `6a99d5591be27e2f62baad59504812c09f189c23`이며 작업 트리는 깨끗했다.
- 기존 freeze의 HEAD는 `81164c3a9cf08d218f494acd7e47485441b11209`다. 두 HEAD 사이 변경은 직전 결과 문서뿐이며 frozen/current source·profile·override 검사를 통과했다. **다시 freeze하지 않았다.** 기존 frozen manifest SHA는 시작 전후 동일하다.
- PROFILE: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v12.json`.
- SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`.
- ROOT: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v12`.
- 모든 harness action은 `export ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env` 후 `bash evaluation/graduation-evaluation.sh --fresh <action>`으로 호출했다. preflight와 분석은 지정된 Python 진입점을 사용했다.
- 코드·profile·SG 규칙·OpenStack 설정을 수정하지 않았다. 새 GCP VM 생성, 사양 변경, 유료 전환, case 재실행, 실험 mutation 재전송은 없었다. 기존 하네스가 수행한 소유 워커 준비·정리만 실행했다.
- 직전 시도(15:23:11–15:48:07)는 ensure Ready timeout으로 attempt 0이었다. 해당 기록과 분석 파일, 문서 커밋 `6a99d55`를 보존했다. 사용자가 별도로 승인한 이번 환경 재기동은 case 재시도가 아니다.
- 직전 시도 종료 뒤 생성된 pending 4건의 manifest를 그대로 사용했다. 이번 시작 시 순서 `s2-x01-s → s2-x02-s → s2-x03-s → s2-x04-p`, 모두 pending·attempt 0을 확인했다.

## 이번 실행 시간과 admission gate

| 시각(KST) | 작업과 결과 |
|---|---|
| 16:02–16:03 | 새 preflight 9/9: VM 3대 TERMINATED, 열린 원장·활성 평가 프로세스·lock 없음, source/profile/clock/credit 확인 |
| 16:03:07 | environment-ensure 1회 시작 |
| 16:08:28 | Ready 성공. 전체 ensure 321.170초(5분 21초), 17:30 ready gate 통과 |
| 16:09:09–16:24:04 | s2-x01-s attempt-01: 준비 실패 → CLEANUP_FAILED → resume-cleanup 1회 → 무효·cleanup=true |
| 16:25:24–16:39:51 | s2-x02-s attempt-01: 준비 실패 → CLEANUP_FAILED → resume-cleanup 1회 → 무효·cleanup=true |
| 16:40:33–16:54:50 | s2-x03-s attempt-01: 준비 실패 → CLEANUP_FAILED → resume-cleanup 1회 → 무효·cleanup=true |
| 16:55:21–17:09:31 | s2-x04-p attempt-01: 준비 실패 → CLEANUP_FAILED → resume-cleanup 1회 → 무효·cleanup=true |
| 17:09:55 | 모든 case 종료·정리 확인 직후 environment-down 시작 |
| 17:15:49 | VM 3대 TERMINATED 확인 및 원장 세션 종료 |
| 17:16:15 | 종료 후 preflight 9/9 재통과 |

| 다음 case | gate 확인(KST) | 직전 cleanup | 예약 후 forward margin(원) | 결정 |
|---|---|---|---:|---|
| s2-x01-s | 16:08:52 | 초기 preflight 통과 | 10,723.22 | 19:50 이전·margin 양수, 1회 실행 |
| s2-x02-s | 16:24:59 | true | 10,006.45 | 19:50 이전·margin 양수, 1회 실행 |
| s2-x03-s | 16:40:07 | true | 9,333.97 | 19:50 이전·margin 양수, 1회 실행 |
| s2-x04-p | 16:55:03 | true | 8,670.63 | 19:50 이전·margin 양수, 1회 실행 |

각 admission은 하네스의 case+정리+종료 예약 10,800초를 반영한 forward credit을 확인했다. x01 이후에도 identity 불일치가 남아 있음을 기록했고, 사용자 지시의 세 진행 조건(cleanup=true, 19:50 이전, margin>0)이 모두 충족돼 다음 case를 실행했다. 19:50에 도달하기 전에 네 case를 모두 종료했으므로 별도 대기나 추가 실행 없이 즉시 down했다. 20:40 down·21:30 결과 기한을 지켰다.

## Case별 판정과 원인

F=false, T=true, null=판정 가능한 회복 관측 없음. 각 행은 저장된 `judgement.json` 그대로다.

| Case | Mode | Attempts | trial_valid | fault_realized | impact_realized | recovered | safety | cleanup | checks.split_only | 결과 |
|---|---|---:|---|---|---|---|---|---|---|---|
| s2-x01-s | S | 1 | F | F | F | null | F | T | 없음 | 무효·VERIFIED |
| s2-x02-s | S | 1 | F | F | F | null | F | T | 없음 | 무효·VERIFIED |
| s2-x03-s | S | 1 | F | F | F | null | F | T | 없음 | 무효·VERIFIED |
| s2-x04-p | P | 1 | F | F | F | null | F | T | 해당 없음 | 무효·VERIFIED |

네 case 모두 `execution=interrupted`, `checks={}`이며 missing은 다음 8개다.

- `baseline_clock_origin_invalid`
- `baseline_first_arrivals_incomplete_or_duplicate`
- `baseline_unhealthy`
- `execution_interrupted`
- `horizon_missing`
- `phase_sequence_incomplete`
- `scenario_evidence_missing:'initial'`
- `semantic_event_missing_or_duplicate`

이는 baseline·주입·H 측정에 도달하지 못한 결과다. `safety=false`를 실제로 관측한 위험한 S/P 조치로 해석하지 않으며 `recovered=null`을 유효한 미회복으로 바꾸지 않는다. S의 `checks.split_only=true`는 하나도 확인되지 않았다. fault/impact도 실현되지 않았으므로 S 또는 P의 효과를 판단할 수 없다.

확인된 직접 원인은 다음과 같다.

1. 새 ensure의 environment record는 `env-aef5b165ff9f`다.
2. v12 및 frozen profile의 `operations.stability.read_identity.environment_run_id`는 `env-8093c4a92ee7`로 고정돼 있고, 각 attempt의 `operational-read-context.json`에도 그 값이 복사됐다.
3. 준비 과정에서 워커 2대 Ready까지 진행한 뒤 `scripts/test_resources.py → reconcile_before_probe → scripts/lib/fresh_reads.py:identity`가 두 ID의 불일치로 `RuntimeError: environment identity changed`를 발생시켰다. Neutron 캐시 조회·재시작 및 실험 adapter/주입 전 거부다.
4. 자동 정리는 워커를 1대로 되돌렸지만 같은 readiness guard에서 실패했다. 이후 허용된 `resume-cleanup`은 이미 1대인 소유 상태를 확인하고 auto mode를 복원해 정리를 봉인했다. 네 case 모두 시험 namespace 부재, `worker_auto_one=true`, `no_trial_taints=true`가 검증됐다.
5. case는 각 1회만 실행했고, cleanup-only 재개는 각 1회였다. 무효를 유효로 승격하거나 profile/state identity를 맞춰 쓰지 않았다.

## 연결 진단과 복구 여부

이번 ensure는 성공했으므로 사용자 절차 4의 **ensure 실패 시에만 수행하는** VM RUNNING 상태 네트워크 진단 분기에 들어가지 않았다.

| 구간 | 이번에 확인한 범위 |
|---|---|
| Mac → controller / workload API | ensure의 management/workload Kubernetes Ready 검사가 통과했고, case 준비 중 워커 2대 Ready도 기록됐다. readiness 경로의 응답은 확인 |
| controller → floating IP | 별도 nc/ping/route 진단 미수행. 이번에 이 구간의 지속 timeout은 확인되지 않음 |
| router namespace → CP fixed IP | 별도 ping/nc 미수행 |
| CP VM 게스트·Neutron agent/ipset | 실패 분기의 console/agent/ipset 진단 미수행. guest 고장 또는 agent dead/cache 불일치로 이번 실패를 판정하지 않음 |

직전 controller→endpoint:6443 timeout의 **근본 원인과 이번 재기동으로 정상화된 경위는 확정하지 못했다**. 이번 case의 차단 지점은 네트워크 hop으로 관측된 장애가 아니라 로컬 하네스의 고정 read identity 검사다.

명확한 Neutron agent down/dead 또는 ipset 불일치 증거가 없으므로 수동 `docker restart`는 **0회**, 허용 복구 뒤 추가 ensure도 **0회**다. 이번 재기동의 ensure 1회와 네 case의 cleanup-only 재개만 수행했다. 읽기 전용 원인 증거는 `operations/ensure-retry-20261029T070229Z/`에 보존했다.

## 사후 분석 지표

`fresh_extension_analysis.py`가 원래 유효 main 첫 attempt와 별도 보충 결과를 읽었다. `all-case-disposition-ensure-retry-20261029T070229Z.json`은 같은 입력의 무효·미실행 행도 campaign 경로와 함께 보존한다. extension을 main29 또는 보충과 합치지 않았고 새로운 pooled estimate를 만들지 않았다.

조치 후 위반율은 첫 `action_applied`부터 H 끝까지이며, 조치가 없는 M은 `diagnosis`부터의 비율이다. 따라서 M의 열은 실제 조치 효과를 뜻하지 않는다. p95는 H 전체에서 성공·내용 일치·deadline 내 요청에 조건부인 지연이며, 조치 후 p95가 아니다. 실패율도 H 전체 기준이다. strict 표기는 **V/F/I/R/S/C = trial_valid / fault_realized / impact_realized / recovered / safety / cleanup** 이다. 원 strict를 사후 지표로 승격하지 않는다.

### S2 P / S / M

P 비교 대상은 main 유효 2건과 extension x04(무효)를 함께 표시하되 cohort를 구분한다. S는 계획·시도 n=3, 유효 n=0이며 M은 main 유효 n=3이다.

| Case | Cohort/mode | 조치·진단 후 위반율 % | H 위반율 % | H 실패율 % | 조건부 p95 ms | 불건강 bin | upload B/s | strict V/F/I/R/S/C |
|---|---|---:|---:|---:|---:|---:|---:|---|
| s2-b01-p | main/P | 0.000 | 0.208 | 0.000 | 358.17 | 0 | 628271.79 | T/T/F/T/T/T |
| s2-b01-m | main/M | 1.721 | 1.917 | 0.000 | 448.71 | 1 | 1821026.99 | T/T/T/T/T/T |
| s2-b02-m | main/M | 2.339 | 2.250 | 0.000 | 447.59 | 3 | 1819279.36 | T/T/T/T/T/T |
| s2-b02-p | main/P | 0.000 | 0.292 | 0.000 | 352.23 | 0 | 623028.91 | T/T/F/T/T/T |
| s2-b03-m | main/M | 1.863 | 1.667 | 0.000 | 441.85 | 1 | 1806172.16 | T/T/T/T/T/T |
| s2-x01-s | extension/S (무효) | — | — | — | — | — | — | F/F/F/—/F/T |
| s2-x02-s | extension/S (무효) | — | — | — | — | — | — | F/F/F/—/F/T |
| s2-x03-s | extension/S (무효) | — | — | — | — | — | — | F/F/F/—/F/T |
| s2-x04-p | extension/P (무효) | — | — | — | — | — | — | F/F/F/—/F/T |
| s2-b03-p | main/P (무효) | — | — | — | — | — | — | F/—/—/—/—/T |

보충 P는 아래처럼 별도로 보존한다. main의 무효 P를 대체하지 않는다.

| Case | Cohort | 조치 후 위반율 % | H 위반율 % | H 실패율 % | 조건부 p95 ms | 불건강 bin | upload B/s | strict V/F/I/R/S/C |
|---|---|---:|---:|---:|---:|---:|---:|---|
| s2-b03-p-supplement01 | supplemental | 0.000 | 0.500 | 0.000 | 357.12 | 1 | 616038.40 | T/T/T/T/T/T |

### S1 P / M / A

| Case | Mode | 조치·진단 후 위반율 % | H 위반율 % | H 실패율 % | 조건부 p95 ms | 불건강 bin | upload B/s | strict V/F/I/R/S/C |
|---|---|---:|---:|---:|---:|---:|---:|---|
| s1-b01-m | M | 2.444 | 2.600 | 0.000 | 184.82 | 2 | — | T/T/T/T/T/T |
| s1-b01-a | A | 2.804 | 2.867 | 0.000 | 188.67 | 3 | — | T/T/T/T/T/T |
| s1-b01-p | P | 0.136 | 0.650 | 0.000 | 154.13 | 2 | — | T/T/T/T/T/T |
| s1-b02-p | P | 0.117 | 0.683 | 0.000 | 157.38 | 2 | — | T/T/T/T/T/T |
| s1-b02-m | M | 2.633 | 2.733 | 0.000 | 186.64 | 2 | — | T/T/T/F/T/T |
| s1-b03-p | P | 0.078 | 0.567 | 0.000 | 155.31 | 0 | — | T/T/F/T/T/T |
| s1-b03-m | M | 2.594 | 2.783 | 0.000 | 187.57 | 3 | — | T/T/T/T/T/T |
| s1-b03-a | A | 2.243 | 2.383 | 0.000 | 188.77 | 5 | — | T/T/T/T/T/T |
| s1-b02-a | A (무효) | 100.000 | 87.700 | 87.417 | — | 53 | — | F/F/F/—/F/T |

### 기존 무효·미실행 보존

| Case / 원 campaign | 판정 또는 제외 사유 |
|---|---|
| s1-b02-a / bed-a/s1-main-v1 | 무효 첫 attempt: execution interrupted, request arrivals incomplete, total request indexes 부족, `service_after` 증거 없음. cleanup=T, recovered=null |
| s2-b03-p / bed-transport-v2/s2-main-transport-v2 | 무효 첫 attempt: `judgement_error:UnboundLocalError` (`start` 미할당), cleanup=T. 후속 보충으로 대체하지 않음 |
| s1-b03-m, s1-b03-a / bed-a/s1-main-v1 | 원 manifest의 미실행 슬롯. 위 유효 행은 bed-transport-v2의 별도 기록 |
| s2-b03-m / bed-transport-v2/s2-main-transport-v2 | 원 manifest의 미실행 슬롯. 위 유효 행은 bed-judgement-closure-v3의 별도 기록 |

무효 S1 A 행의 높은 위반·실패율은 불완전한 요청과 결측을 포함한 저장 지표이며, 관측된 서비스 성능의 유효 추정치로 비교하지 않는다. 유효 main 및 보충의 `missing=[]`이고 cleanup=T다. 이번 extension 네 무효 행은 위 8개 missing을 유지하며 모든 성능 지표가 null이다. 무효 행의 원 missing 목록·attempt 오류·campaign 경로는 `all-case-disposition-ensure-retry-20261029T070229Z.json`에 보존했다. S1 V1은 SLO가 달라 P/M/A 분석에서 제외한다.

## 비교와 해석

- **S 대 P, S 대 M:** S의 유효 실측이 없어 API 위반율·지연 및 upload goodput의 차이를 계산할 수 없다. x04도 무효여서 같은 날짜 P anchor가 없다.
- 기존 S2 main P는 조치 후 API 위반율 0%, H 위반율 0.208–0.292%, 조건부 p95 352.23–358.17 ms였다. main M은 진단 후 위반율 1.721–2.339%, H 위반율 1.667–2.250%, p95 441.85–448.71 ms였다. 이는 기존 날짜의 기술 통계다.
- 기존 main P의 upload goodput은 623,029–628,272 B/s, M은 1,806,172–1,821,027 B/s였다. case 평균은 각각 약 625,650 및 1,815,493 B/s로 P가 약 65.5% 낮았다. 결합 정책 P의 API 지표 개선과 upload 처리량 감소가 함께 관측됐지만, 분리와 QoS 각각의 기여는 이 비교로 분해할 수 없다.
- 기존 main P 2건은 impact_realized=F이고 recovered=T다. 이 결과를 뚜렷한 장애 영향에서 회복한 두 건으로 해석하지 않는다. 별도 보충 P는 impact_realized=T지만 main에 합치지 않는다.
- **이번 실행으로 “K8s 분리만으로는 부족하고 Neutron QoS가 필요하다”는 주장을 뒷받침하거나 반박할 수 없다.** S가 API를 보호하지 못한 유효 결과라면 해당 조건의 QoS 필요성 근거가 되고, 보호했다면 주장을 축소해야 하지만, 이번에는 어느 조건도 유효하게 측정되지 않았다.
- S1 P의 조치 후 위반율은 0.078–0.136%, M의 진단 후 위반율은 2.444–2.633%, A는 2.243–2.804%다. 이 역시 기존 결과의 사후 기술 비교이며 본 extension의 신규 결과가 아니다.

## 비용과 종료 검증

- 이번 실제 bed 세션은 **4362.545초 = 1시간 12분 42.545초** (16:03:07.303547–17:15:49.848191 KST)다. ensure·준비·실패·cleanup·down 및 사이 대기를 모두 포함한다.
- 고정 계획 비용률 2,500원/bed-hour로 **약 3,030원**. calendar-day 4,000원/일을 같은 구간에 비례 배분하면 **약 3,232원**이다. 실제 Billing 청구액이 아니며 VM별 청구시간 합계도 아니다.
- 직전 ensure 실패 세션 24분 56.093초를 포함한 두 세션 합계는 **5858.638초 = 1시간 37분 38.638초**, 동일 비례 비용 모델로 **약 4,340원**이다. 보존 디스크 등의 종료 후 비용은 계속 남는다.
- 종료 후 preflight의 전체 예약 12,156초 기준 forward margin은 6,723.73원으로 양수였다. 실제 청구 cutoff 미상, 12시간 미반영 청구 가정 및 정리 40,000원·기타 20,000원 reserve를 유지했다. 과거 원장을 표시 잔액에서 재차 차감하지 않았다.
- 기존 ID/type의 controller(e2-standard-4), compute01(n2-standard-8), compute02(n2-standard-4) 모두 TERMINATED. 공유 원장 최신 세션 stopped, 열린 세션 0. 종료 후 평가 프로세스·점유 advisory lock 0. 비점유 lock 파일은 보존했다.
- clock guard는 시작 전후 state가 같은 `restored`, active lease/pending request 없음이다. 네 case 모두 lease 획득 전 실패해 이번에는 network time Off나 시계 변경이 없었다.
- 17:10 KST macOS UI에서 자동 시간 **On**을 직접 재확인했고 `/etc/ntp.conf`는 `server time.asia.apple.com`이다. UI의 `Apple (time.apple.com.)` 표기는 남아 있다. 관리자 `systemsetup` 현재 서버 직접 조회가 불가능했던 직전 검증 한계는 해소했다고 주장하지 않는다. 이번 작업에서는 시간 설정을 변경하지 않았다.
- 분석기가 저장된 첫 attempt 해시를 확인했고 네 case 모두 attempt=1, VERIFIED, cleanup=true, 동일 frozen manifest/source/profile를 재확인했다. 코드 변경이 없어 회귀 테스트를 다시 실행하지 않았다.

## 한계 및 남은 위험

- S는 계획·시도 n=3이지만 유효 n=0, P anchor도 무효다. 단일 날짜의 소규모 사후 분석이며 main29·보충을 합치거나 원 strict를 바꾸지 않는다.
- S1 목적지 compute01(n2-standard-8)은 compute02(n2-standard-4)보다 크다. [ADR-0017](../adr/0017-increase-recovery-target-compute-capacity.md)에 따른 용량·배치 차이가 있어 자동 대응 효과만의 인과 비교로 볼 수 없다.
- p95는 성공 요청에 조건부다. M은 진단 시각, P/S는 조치 시각을 anchor로 써 조치 후 구간이 동일하지 않다.
- **고정 v12 read identity와 재기동 environment run ID의 불일치가 해결되지 않았다.** code/profile 변경 금지에 따라 수정하지 않았다. 네 case의 1-attempt cap은 소진됐으므로 기존 cohort를 다시 실행할 수 없다.
- 직전 네트워크 timeout의 근본 원인, 시간 서버 UI/daemon 일치, 실제 청구액·보존 자원 비용은 별도 확인이 필요하다.

## 산출물과 증거

ROOT 기준 경로이며 raw·비밀정보·profile·원장·진단 파일은 Git에 추가하지 않고 이 결과 문서만 커밋한다. 직전 파일은 덮어쓰지 않았다.

- `operations/ensure-retry-20261029T070229Z/preflight.json`, `execution-inputs.json`: 이번 사전 조건, 시작 당시 pending 4건, frozen SHA, 원장 세션.
- `operations/ensure-retry-20261029T070229Z/admission-s2-x0{1,2,3}-s.json`, `admission-s2-x04-p.json`: case별 cleanup·시각·비용 gate.
- `operations/ensure-retry-20261029T070229Z/case-failure-identity.json`, `before-resume-*.log`, `before-resume-*.jsonl`: identity 불일치와 원인 증거.
- `operations/environment-ensure-1793257387300645000/`: 성공한 ensure의 phase 시간·환경 record.
- `s2-extension/cases/<case>/attempt-01/`: prepare·cleanup 로그, 원 judgement/metrics, cleanup proof와 봉인 해시.
- `operations/environment-down-1793261395191745000/`: 종료 로그·환경 record.
- `operations/ensure-retry-20261029T070229Z/post-down-verification.json`: 종료 후 9/9 검증.
- `analysis/posthoc-results-ensure-retry-20261029T070229Z.json`: 지정 분석기의 원 출력.
- `analysis/all-case-disposition-ensure-retry-20261029T070229Z.json`: 모든 extension 무효 및 기존 무효·미실행 원 campaign 포함.
- `analysis/execution-summary-ensure-retry-20261029T070229Z.json`: 실행·정리·비용·clock·원인 요약.
- 직전 `analysis/posthoc-results.json`, `all-case-disposition.json`, `execution-summary.json`은 15:48 종료 당시 미실행 snapshot으로 보존한다. 최신 결과로 혼동하지 않는다.
