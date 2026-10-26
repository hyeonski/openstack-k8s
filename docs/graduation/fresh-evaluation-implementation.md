# F-repeated 로컬 구현과 live pilot 인계

2026-10-26 사용자 결정에 따라 전체 S1~S4를 구현했다. 이 문서의 검증은 합성 trace·mock·로컬 검사다. 클라우드 기동, 배포, 장애 주입, live smoke, pilot, 본시험은 수행하지 않았다. 기존 raw와 승인된 구축·실행 상세안은 수정하지 않았다. 과거 결과를 본 설계임을 profile에 명시했고 새 primary에 과거 결과를 입력하는 경로를 차단한다.

## 진입점과 일정

```sh
python3 evaluation/fresh_campaign.py --help
make graduation-fresh-schedule
python3 evaluation/graduation_evaluation.py schedule --profile config/graduation-evaluation-fresh.json
python3 evaluation/fresh_campaign.py validate --profile config/graduation-evaluation-fresh.json
```

마지막 명령은 **현재 초안에서 exit 2가 정상**이다. 미확정 값을 기본값으로 대체하지 않는다. `schedule`은 구조·순서·표본 수를 검사하면서 초안의 null을 허용한다. `validate`, live `freeze`, live `run`은 이를 거절한다. 기존 `graduation-evaluation-*` 명령은 기본적으로 구 profile을 사용하며 34개 case ID가 유지된다. 새 profile은 schema 3, `--fresh` 또는 위 새 진입점으로 선택한다.

| 시나리오 | 본시험 | 준비 | 세션 |
|---|---:|---:|---|
| S1 P/M/A | 3block × 3군 = 9 | P 자동 smoke 1 | A/B |
| S1 V1 | 2 | pilot 1 | A |
| S2 P/M | 3pair × 2군 = 6 | pair pilot 2 | C |
| S3 P3600/M3600 | 3pair × 2군 = 6 | pair pilot 2 | D |
| S4 on/off | 3pair × 2군 = 6 | pair pilot 2 | E |
| 합계 | **29** | **8** | 개발 smoke 묶음은 별도 |

명시적 case ID·purpose·block·seed·order·session은 `config/graduation-evaluation-fresh.json`에 있다. S1은 seed로 정한 순환 균형 순서, 두 군 비교는 2:1 순서 불균형을 공개한다. 요청·정책 window·stage·retry·pilot은 새 main 표본이 아니다. H와 T는 추가하지 않았다.

## 로컬 합성 재현

다음은 네트워크가 필요 없는 개발 검증 전용이다. 새 디렉터리를 사용하며 기존 campaign을 덮어쓰지 않는다.

```sh
python3 evaluation/fresh_fake.py config/graduation-evaluation-fresh.json > /private/tmp/fresh-synthetic-profile.json
python3 evaluation/fresh_campaign.py freeze --synthetic --stage main --profile /private/tmp/fresh-synthetic-profile.json --campaign /private/tmp/fresh-synthetic-main
python3 evaluation/fresh_campaign.py run --synthetic --campaign /private/tmp/fresh-synthetic-main
python3 evaluation/fresh_campaign.py report --synthetic-report --campaign /private/tmp/fresh-synthetic-main
```

준비 8개 검증은 새 경로와 `--stage preparation`을 사용한다. synthetic profile은 `readiness=synthetic-only`로 표시되므로 live freeze를 통과하지 않는다. 일반 report는 synthetic campaign을 거절한다. 합성 report의 primary sample count는 항상 0이며 파일 이름도 `synthetic-`로 시작한다. 이 trace가 좋은 복구 결과를 생성해도 실험 성공 증거가 아니다.

## 구현 파일과 상태

| 작업 | 로컬 구현 | 주요 파일 | 남은 실환경 검증 |
|---|---|---|---|
| B01 | schema·명시적 37 case·dry schedule·profile 선택·freeze | `fresh_contract.py`, `fresh_campaign.py`, fresh JSON, `commands.mk` | 환경·예산·계측·pilot 값 확정 |
| B02 | UTC/process clock, arrival/start/completion, rejection·미완료, raw provenance adapter | `fresh_evidence.py`, `fresh_analysis.py`, S1 loadgen, S2 workload | 실제 probe 부하·clock 오차·출력 수집 완전성 |
| B03 | 기존 P와 no-action M 재사용, 같은 worker 재시작 A | `fresh_scenarios.py:FreshS1`, 기존 S1 policy hook | Pod 교체·Node/VM/compute 불변·경합 지속 |
| B04 | V1 정상 defer와 예외 구분, 후보 목록/선택 gate, 실제 P 조치도 관측 | `FreshS1`, 독립 V1 판정 | host 경합·서비스 정상 후보 성립 |
| B05 | raw 재계산, validity/recovery/safety 분리, 고정 bin·마지막 안정 tail, paired raw 차이·결측·claim coverage | `fresh_analysis.py`, `fresh_campaign.py:report` | 등록된 SLO·안정창·bin을 pilot으로 확인 |
| B06 | attempt별 경로·원장·hash·cleanup 차단·cleanup-only resume·명시적 retry·도구 변경 감사 | `fresh_campaign.py`, `fresh_live.py` | 실제 API 응답 소실 및 ownership 복원 |
| B08 | 독립 fresh S2 P/M, receiver의 연속 probe, H 전체 uploader·진척·분리/QoS readback | `FreshS2`, `RemoteProbe` | receiver/Nova/Neutron/OVS 실제 동작과 upload cap |
| B09 | 동일 admitted 3600초 timer, 연속 read, NotReady와 진단 분리, fencing→OOS, M 무개입·H 뒤 cleanup | `FreshS3` | guest SSH/firewall, 실제 fence 근거·Cinder identity·seed |
| B10 | MHC on/off, 전체 H 관측, MHC ownership/복원, 교체 identity·물리 배치·scheduler로 capacity probe 배치 | `FreshS4Run`, `run_s4`, capacity 판정 | 설치된 controller의 pause 반영·교체·실제 usable capacity |

위 Python 파일은 `evaluation/` 아래 있다. B07 사람과 B11 transient는 선택 범위 밖이며 구현 완료로 표시하지 않는다. 새 live bridge는 기존 환경/fixture 준비·정리 함수를 재사용하지만 legacy schedule/verifier는 사용하지 않는다. 정책이 회복해도 H를 끝까지 관측한다. S1은 총 load 1,800초 전체를 유지하고 주입 후 H가 남은 부하 시간에 들어오는지도 검사한다. 총 요청 수는 rate×seconds이며 현재 9,000개다. warmup은 총 시간에 포함되고 현재 0이다.

## raw와 판정 의미

`events.jsonl`은 주입 요청/확인, 실제 NotReady 관측, 진단, 조치 요청/적용, H 종료, cleanup을 구분한다. applied는 외부 상태를 처음 확인한 시각이다. 정확한 물리 전이는 요청~확인 사이의 구간으로 보고하고 알려지지 않은 전이 시각을 꾸며내지 않는다. 정책의 사후 success flag는 판정에 사용하지 않는다. 다른 process/host monotonic 값의 차감은 거절한다. 서로 다른 장비의 UTC 정렬 정확도는 live pilot에서 측정해야 하며, 이 제약을 적용 시각의 구간·관측 한계에 남긴다.

정규화 요청은 원본 파일·row·field·변환 규칙을 가진다. 새 live 계측은 `requests.jsonl`, 기존 scenario raw는 attempt 아래 `raw/`에 복사 보존한다. `observations/contract.json`은 실제 identity/configuration/progress snapshot의 공통 view이고 provenance에 원본 경로와 변환을 명시한다. 판단·조치 코드는 `fresh_scenarios.py`, 계측과 독립 분석은 별도 파일에 있다. 기존 혼합 policy 파일 전체는 보수적으로 policy hash에 넣는다. S1의 contender 확인은 기존 계약에서는 보존하고 fresh policy hook에서는 주입 identity를 읽지 않으며, 경합 지속은 독립 관측으로 판정한다.

- latency primary는 예정 arrival→완료, 보조는 실제 시작→완료다. 성공 latency와 전체 실패율·queue 지연·generator rejection·미완료를 같이 낸다.
- 미회복 시간은 null이며 H로 치환한 평균을 내지 않는다. 마지막 연속 healthy tail이 안정창을 채워야 최종 회복이다. 재악화하면 앞선 회복을 최종 회복으로 세지 않는다.
- D는 완전한 고정 bin의 관측된 위반 시간 하한이다. 미관측 시간은 별도다. 누락·중복·시간 역전은 evidence defect로 남는다.
- `trial_valid`는 증거/fixture/군 계약, `safety`는 대상·순서·identity, `recovered`는 H 내 서비스 결과다. S4는 전체 recovered에 capacity도 요구하고 서비스·capacity 결과도 각각 남긴다. 유효한 M 미회복은 삭제·retry 대체하지 않는다. 잘못된 대상/안전 실패도 결과표에 남긴다.
- V1은 `held`, `condition_not_realized`, `misaction`, `exception`을 구분한다. 예외 중단은 정상 보류가 아니다.
- S3 read availability와 고정 seed 보존만 관측한다. 지속 write 내구성이나 ACK 무손실을 주장하지 않는다. M3600은 native 기본 설정 대조가 아니다. S4는 기존 MHC/CAPI/CAPO 동작의 효과다.

보고서는 `run-results`, `attempt-ledger`, `paired-contrasts`, `missingness`, `claim-coverage` JSON과 전체 표를 출력한다. 첫 attempt를 primary로 고정하고 나머지 retry도 모두 공개한다. pilot/main은 서로 다른 manifest이고 pilot을 main에 합치지 않는다. report는 manifest에 등록된 경로만 읽고 campaign/purpose/policy/identity/raw hash가 다르면 실패한다.

## 초안 확정과 다음 단계 gate

지금 저장소의 draft는 live freeze가 불가능하다. 다음은 **이 단계에서 실행하지 않은** 향후 운영 절차다.

1. 개발 checkout과 실행 checkout을 분리할 경우 전체 구현을 실행 checkout에 먼저 반영한다. 활성 campaign의 source를 수정하면서 계속 실행하지 않는다. 로컬에서 발견한 기존 campaign 상태는 `verified`, `reviewed-with-exceptions`, `superseded-*`였고 raw는 변경하지 않았다. 실행 process 조회는 sandbox에서 불가능했으며, 신규 live 운용 전 운영자가 확인한다.
2. draft를 별도 파일로 복사해 H·SLO·bin·안정창·최소 표본·deadline과 실제 예산/운영자/종료 시각을 합의·calibration한다. 구현 구조상 S1 H≥900초, S2 H≥600초이며 S1은 남은 1,800초 load 안에 H와 종료 clock 확인용 30초 여유를 확보해야 한다. 이는 확정된 실험 H가 아니라 현재 정책의 진단·조치 상한을 수용하는 validation 제약이다. S1/S2 현재 sampler timeout/deadline은 5초다. 두 군의 `max_clock_offset_seconds`도 calibration 후 확정하며, 원격 generator UTC의 오차·왕복 불확실성 구간을 주입 전과 H 종료 후 `clock-checks.jsonl`에 기록한다. 허용 범위를 벗어나거나 확인이 누락되면 주입/유효 판정을 차단한다. 변경이 필요하면 코드·계측·새 freeze를 함께 검토한다.
3. `fault`에는 `fresh_contract.SUPPORTED_FAULTS`의 실제 고정 주입기를 등록한다. S1은 4 CPU worker/4 vCPU pbkdf2 부하, S2는 20Mbps/1MiB×4096 chunks, S3은 TCP 6443/5432 차단, S4는 정확한 worker VM stop이다. 지원하지 않는 강도를 profile 숫자만 바꿔 실행하지 않는다. V1 후보는 pilot 전에 `cpu_workers=4`와 `workload_rounds`를 목록으로 정하고 하나를 `v1_selected`로 선택한다. 실제 정상 서비스 조건은 pilot으로 확인한다.
4. S2 `uploader_seconds`는 H+600 이상으로 등록한다. cap 4096MiB가 20Mbps에서 H 이전 소진되지 않는 조건을 검사한다. 초기 port/QoS/공유 workload/진척, S3 volume/seed/timer/MHC 정책, S4 초기 capacity를 `initial_fixture`, `timers`에 등록한다. `initial_fixture`는 `fresh_contract.SUPPORTED_FIXTURE`의 정확한 reset 계약을 사용한다. `timers.mhc_policy`는 `{"s3_specs": [실제 MHC spec들]}` 형식이며 MHC가 없으면 빈 목록을 등록한다. S3 seed는 profile seed·block·purpose에서 결정하므로 같은 pair의 P/M은 같은 1,000개 행을 사용한다. 실제 상태는 각 run에서 새로 읽으며 복구 뒤 identity를 재사용하지 않는다.
5. `operations`의 `execution_checkout`은 실행 저장소 절대경로, `artifact_root`는 해당 release의 새 campaign 상위 경로, `environment_override`는 그 환경 전용 override 절대경로다. `ENV_OVERRIDE_FILE`도 같은 경로여야 하고 환경명/project/zone이 profile과 일치해야 한다. shell이 `STATE_DIR=.state/<environment>`를 선택한다. override 내용은 비밀정보를 복사하지 않고 경로와 hash를 고정한다. pilot 비용으로 실제 `max_case_seconds`, `cleanup_seconds`, `budget_seconds`를 재산정한다. 과거 20시간·날짜 추정은 승인으로 사용하지 않는다.
6. `readiness=confirmed`와 모든 필수 값이 갖춰진 별도 profile로 preparation을 freeze한다. source를 바꾸지 않은 완전한 pilot manifest를 사용한다. G0/G2 운영 승인 후에만 향후 live 준비/실행을 한다.

향후 CLI 문법:

```sh
# 운영 입력·live 승인 후에만 사용
ENV_OVERRIDE_FILE=/absolute/environment.env make graduation-fresh-freeze FRESH_PROFILE=/absolute/confirmed.json FRESH_STAGE=preparation SCENARIO=s1 CAMPAIGN=/absolute/artifacts/release/s1-pilot
ENV_OVERRIDE_FILE=/absolute/environment.env make graduation-fresh-run CAMPAIGN=/absolute/artifacts/release/s1-pilot
make graduation-fresh-report CAMPAIGN=/absolute/artifacts/release/s1-pilot
```

main freeze에는 추가로 `FRESH_STAGE=main`, `PILOT_CAMPAIGN=<완료한 preparation 경로>`, `POLICY_MANIFEST=<공통 preparation의 policy-manifest.json>`을 준다. S1 전체 main 세션은 하나의 freeze를 계속 사용한다. S2/S3/S4는 각 시나리오 pilot/main freeze를 따로 만들 수 있으나 공통 정책 hash가 같아야 한다. main freeze는 필수 pilot의 독립 유효성·안전·cleanup·장애 재현을 확인하고, P/on의 H 내 복구 및 V1 정상 보류를 요구한다. 새로운 release/정책을 섞으려면 artifact root를 분리한다.

`run --limit N`은 case 경계에서 멈춘다. 실패 attempt는 덮어쓰지 않는다. 중단 시 `resume-cleanup --case <id>`는 실제 ownership record를 읽어 정리만 수행하며 불확실한 주입/조치를 재요청하지 않는다. 관측 gap을 남긴다. 새 시도는 `run --case <id>`로 명시하고 최대 추가 1회다. 유효한 미회복을 유리한 retry로 대체할 수 없다. cleanup 실패면 다른 case로 넘어가지 않는다.

평가 도구만 수정할 때는 새 campaign freeze에 `--previous-campaign`을 주고 profile의 `operations.tool_change_allowlist`, `impact_analysis`를 등록한다. policy manifest에 포함된 변경은 이 경로로 우회할 수 없다. 영향 분석은 `{"judgement_semantics_changed": false, "policy_changed": false, "affected_scenarios": ["s1"], "reason": "변경의 근거와 영향"}`와 같은 구조로 등록한다. 공통 판정 의미/정책을 바꾼 경우 이 경로로 우회하지 않는다. diff와 영향 분석은 `tool-change-audit.json`에 hash와 함께 보존한다. S1 main의 변경은 같은 freeze를 이어서 수행하지 않으며 새 연구 cohort로 재설계한다.

MHC off는 소유한 MachineHealthCheck에 `cluster.x-k8s.io/paused` annotation과 별도 ownership annotation을 붙이고 spec/UID를 확인해 원복한다. annotation의 remediation 중단 의미는 [Cluster API 공식 문서](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking.html)의 Skipping Remediation을 따른다. 설치된 controller 버전에서 실제 반영되는지는 live pilot gate다.

## 검증 표 연결

`tests/test_fresh_evaluation.py`는 외부 API를 호출하지 않는다. fake trace에는 synthetic 표시가 있고 실제 조치 hook은 mock으로 분리한다.

| 구축 상세안 검증 | 테스트 |
|---|---|
| 29+8/구 34 ID/1,800초 9,000개/다른 rate 산식 | `test_B01_schedule_counts_and_legacy_exact_ids`, `test_B05_B06_all29_and8_synthetic_campaigns_and_primary_rejection` |
| schema/중복/없는 군/미확정 값 차단 | `test_B01_draft_live_blocked_and_bad_schema` |
| 정상 회복/재악화/각 시나리오 M 미회복 | `test_B02_B05_normal_relapse_unrecovered_queue_and_missing` |
| 누락·중복·queue·rejection·시간 역전·clock domain | `test_B02_B05_request_defects_and_clock_domains`, `test_B02_event_time_reversal_and_execution_exception_not_hold` |
| 연속 요청 계측 | `test_B02_open_loop_probe_records_every_arrival_offline` |
| 잘못된 재시작/summary 독립/V1 조건 불성립 | `test_B03_B04_wrong_target_v1_outcomes_and_summary_independence` |
| 적용 후 응답 소실→중복 요청 금지 | `test_B03_restart_hook_and_unknown_effect_never_replayed` |
| source/profile/분석 변경·과거 혼입 | `test_B01_B06_freeze_profile_source_analysis_hash_and_history`, 전체 합성 campaign 테스트 |
| cleanup 실패/재개/새 attempt·원 시도 보존 | `test_B06_cleanup_failure_resume_no_replay_and_retry`, `test_B06_partial_S4_prepare_without_record_can_cleanup` |
| 전체 freeze 경로에서도 S1 main 중복 차단 | `test_B06_all_scenario_freeze_cannot_duplicate_S1_main` |
| S2 M 조치 억제/P 분리·QoS hook | `test_B08_real_split_hook_suppresses_M_and_confirms_P` |
| S3 fencing→OOS/미확인 fencing 거절/M 억제 | `test_B09_real_fencing_hook_order_M_suppression_and_deadline` |
| S4 MHC ownership/복원·대상/usable capacity | `test_B10_restore_mhc_ownership_and_readback`, `test_B08_B09_B10_safety_snapshots` |

실제 명령과 결과는 작업 완료 보고 및 로컬 `artifacts/fresh-local-validation-2026-10-26/`에 저장한다. runtime 권한이 필요한 확인은 위 표의 로컬 테스트가 대신 실증한 것이 아니며 live pilot에서 확인한다. 재검토와 최종 오프라인 검증을 마친 관련 변경만 한국어 `feat:` 커밋으로 묶는다. live 실험은 실행하지 않았다.

## 합의안 기준 재검토와 수정

재검토에서 다음 문제를 재현하고 수정했다. 기존 승인 문서의 hash와 과거 raw는 유지했다.

| 영역 | 발견한 문제와 수정 | 추가 회귀 검증 |
|---|---|---|
| B01/B06 | schema의 잘못된 타입·불완전한 pilot pair·미지원 case 옵션, scope/건수/Git metadata 변경을 거절한다. 선택 profile의 동시 변경·복사 중 source 변경도 검출한다. | schema/완전한 live schema/freeze metadata 테스트 |
| B02 | 원격 UTC offset과 sampling 불확실성을 확인하고, probe 응답이 generator clock/arrival 필드를 덮어쓰지 못하게 했다. 시각 역전·clock step은 미확정 결과로 남긴다. 영향·탐지·진단·조치 시간을 별도 지표로 제공한다. | clock bound/clock step/probe metadata/monotonic H 테스트 |
| B03/B04 | A가 `verify()`의 시각까지 비교해 항상 실패하던 문제와 namespace 누락을 수정했다. 최초 조치 직후 캐시뿐 아니라 실제 마지막 서비스 identity와 종료 시점 host 경합도 확인한다. 알려진 정상 policy defer는 각 군에서 정상 보류로, 예외는 예외로 남긴다. | 같은 worker 재시작/정상 defer/경합 종료 테스트 |
| B05/B06 | lock 획득 뒤 최신 campaign을 다시 읽는다. 중단 시 cleanup 후 다음 case를 시작하지 않는다. source 변경·판정 오류가 발생해도 완료 attempt의 원장과 hash를 먼저 보존한다. cleanup의 실패 proof를 재개 시 덮어쓰지 않고 별도 이력으로 남긴다. | stale 상태/interrupt/source 변경/cleanup 재개/잘못된 raw 테스트 |
| B06 | 이전·외부 experiment record를 현재 attempt로 채택해 cleanup하지 않는다. 미완료 fixture가 있으면 환경 기동/변경부터 차단한다. 실제 host identity/flavor를 같은 campaign의 case 사이에서 유지하고, 동일 release artifact root의 live 예산을 시나리오별 freeze마다 초기화하지 않는다. | foreign S4 record/미완료 환경 차단/시나리오 간 예산 테스트 |
| B08 | S2의 기존 두 window 진단에서 빠진 egress·qdisc overlimit·CPU guard를 복원했다. 정책 동작과 독립된 receiver의 1초 진척 관측, 고유 chunk integrity, 종료 H 밖 byte 제외 및 edge 관측 한계를 추가했다. 주입 재현은 policy flag 대신 raw counter에서 다시 계산한다. 정체는 낮은 goodput 결과로 보존하며 좋은 결과로 재분류하지 않는다. | cross-layer 진단/uploader 경계·결측/raw counter/예외 시 raw 보존 테스트 |
| B09 | run마다 달랐던 seed를 pair 안에서 동일하게 만들고 등록 seed 1,000행을 독립 재계산한다. 전후 동일 손상·잘못된 process/volume·fencing power/host/최종 상태·M의 불필요한 fencing을 검출한다. | seed/power/restart/process/volume/MHC/M fence proof 테스트 |
| B10 | capacity 수집 완료가 H 이후인 snapshot은 primary 복구 증거에서 제외한다. H 안의 MHC 설정 변경, Node schedulability, 교체 identity/배치를 확인한다. capacity probe 수명과 사전 probe 여유도 H에 맞춘다. | H 경계/MHC 변경/긴 H의 probe lifetime 테스트 |

S2 uploader goodput은 H 안의 첫/마지막 실제 receiver 관측 사이 고유 byte 증가를 H로 나눈 **하한**이다. 경계에서 관측하지 못한 시간은 `upload_edge_unobserved_seconds`로 공개하며, H 이후 byte로 빈 구간을 채우지 않는다. 1초 창에서 진척이 없는 것과 생성 부하의 소진·관측 누락을 구분한다. 정상 조치 중의 정체를 이유로 P의 불리한 결과를 삭제하지 않는다.

재검토 때 기존 TC JSON은 필드/단위 감사에만 읽었다. 20Mbps의 rate 검증은 현재 고정 주입기 설정에서 유도하며 과거 성능값을 새 표본으로 사용하지 않는다. S3/S4의 최종 확인은 H 이후에도 기록할 수 있지만, 복구 시각과 capacity 안정 판정은 H 내 관측만 사용한다.

추가 테스트는 `tests/test_fresh_evaluation_review.py`에 있다. 최종 `make lint`는 **270 tests OK**(새 평가 45개 포함), shell 검사 통과, `git diff --check` 통과다. 실제 CLI의 합성 `main` 29개와 `preparation` 8개도 각각 freeze/run/report를 완료했다. 두 보고서의 primary sample count는 0이며 일반 primary report의 합성 입력 거절, draft live validation exit 2를 확인했다.

최신 로컬 증거는 `artifacts/fresh-review-validation-2026-10-26/`의 `validation-summary.json`, `commands.json`, `make-lint.log`와 각 합성 campaign에 있다. 이전 `fresh-local-validation-2026-10-26/`는 재검토 전 검증 이력으로 보존한다. 두 묶음 모두 live 실험 증거가 아니다. 다음 live pilot에는 아직 H/SLO/clock bound·주입/V1 후보·실제 MHC spec·환경 override/identity·예산/운영 입력 확정과 운영 승인이 필요하다.
