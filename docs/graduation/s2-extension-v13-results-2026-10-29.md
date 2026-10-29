# S2 extension v13 실행 결과 — 2026-10-29

네 case를 **각 1 attempt로 순차 실행했고 모두 trial_valid=true, missing=[], safety=true, cleanup=true, VERIFIED**로 종료했다. S 세 건의 split_only=true이며 x03은 유효한 미회복(recovered=false)이다. P anchor는 split_and_qos=true, recovered=true이나 impact_realized=false다. **20:11:00 KST에 VM 3대 TERMINATED와 원장 종료를 확인**했다. 20:00 down 기한 초과는 실행 중 사용자가 명시적으로 승인한 시간 연장에 따른다.

시작·freeze HEAD는 `8494a23c065a1a65df8fd1dbdd8bf66c7a56392a`, 브랜치는 `codex/fresh-evaluation-execution-20261026`다. 요청한 v12 결과 문서는 시작 당시 이미 docs 커밋 `8494a23c065a1a65df8fd1dbdd8bf66c7a56392a`에 정리돼 있었고 checkout이 깨끗해 추가 빈 커밋은 만들지 않았다. 현장 source 수정은 0이다.

PROFILE: `/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v13.json`

SHA-256: `2ff0aa6f8f83ee763672fd62f3acc22f569c7d2b35d713c8a9eaccae6ab653ce`

v12 SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`

JSON 전체 재귀 비교 결과 아래 두 경로만 다르다. 과학적 값, hosts, management_uids, credit_reference의 path·sha를 포함한 나머지 값은 동일하다.

| JSON 경로 | v12 | v13 |
|---|---|---|
| `operations.artifact_root` | `bed-extension-v12` | `bed-extension-v13` |
| `operations.stability.read_identity.environment_run_id` | `env-8093c4a92ee7` | `env-b331ec9024d3` |

artifact_root 전체 경로는 `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v13`다. 원 diff와 두 profile SHA는 `operations/profile-v12-v13-diff.json`에 보존했다. v12·v13 frozen source_sha256 및 policy_sha256가 모두 같다.

ensure 후 phase=ready의 run_id `env-b331ec9024d3`를 읽었다. VM ID·type·RUNNING 상태와 Cluster/MachineDeployment/CA Deployment UID를 gcloud·kubectl 읽기로 대조했고 모두 일치했다. freeze 뒤 첫 case 전에는 `scripts/lib/fresh_reads.py:identity`를 직접 1회 호출해 run_id·VM ID/RUNNING·management UID 조건을 재검증했다.

| VM | 기존 ID | 종료 상태 |
|---|---|---|
| osk8s-compute01 | `4452491138774596731` | TERMINATED |
| osk8s-compute02 | `190540613588614267` | TERMINATED |
| osk8s-controller | `8689617440184466555` | TERMINATED |

management UID는 Cluster=`dc6833da-7c7d-4085-a065-3541d15e1c2d`, MachineDeployment=`4f6f3df8-f2f8-4886-95c6-1333eefd3c3e`, CA Deployment=`280ef1f8-75ba-452b-a3ee-3b333bedc594`로 v12 값과 같았다.

ensure는 **17:24:46–17:30:34 KST, 348.097초**로 1회 성공했다. 직전 성공과 같은 ENV_OVERRIDE_FILE, v12 profile, v12 operations 경로로 실행했다. 실패 분기의 hop 진단·재ensure는 0회다. v13 validate 및 forward_credit margin>0 확인 후 `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v13/s2-extension`에 freeze-extension했다.

ensure 전 기존 TERMINATED 기준 v12 preflight가 9/9 통과했다. 첫 sandbox 호출은 ps와 gcloud 자격증명 접근 제한으로 두 항목을 수집하지 못했고, 같은 읽기 검사를 필요한 권한으로 재호출한 결과를 별도 파일로 보존했다. 어느 호출도 ensure·lease·주입을 수행하지 않았다. preflight 코드에 내장된 옛 시간 표기 대신 이번 사용자 gate를 운영 기록에 적용했다.

모든 harness action은 `ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env`와 `bash evaluation/graduation-evaluation.sh --fresh`를 사용했다. case마다 `run --limit 1`을 호출했고 재시도는 0회다. extension manifest의 attempt_cap=1을 유지했다. 각 case 후 원 판정·cleanup·credit를 확인했다.

| Case | KST 시작–종료 | cap/attempt | trial_valid | missing | split_only | recovered | cleanup | 조치 후 위반율 % | admission margin 원 |
|---|---|---|---|---|---|---|---|---:|---:|
| s2-x01-s | 17:31:55–18:10:03 | 1/1 | T | `[]` | T | T | T | 2.628 | 7,042.18 |
| s2-x02-s | 18:10:33–18:48:42 | 1/1 | T | `[]` | T | T | T | 2.830 | 5,329.26 |
| s2-x03-s | 18:49:02–19:26:40 | 1/1 | T | `[]` | T | F | T | 3.024 | 3,615.43 |
| s2-x04-p | 19:27:01–20:04:42 | 1/1 | T | `[]` | — | T | T | 0.000 | 1,928.27 |

T=true, F=false, —=P에서는 split_only 해당 없음. S 세 건은 fault_realized=T, impact_realized=T, safety=T다. P는 fault_realized=T, impact_realized=F, safety=T이며 split_and_qos=T다. x03의 recovered=F는 유효 측정 결과로 보존했고 재시도하지 않았다. 네 case 각각 injection_applied는 1개다. 동일 원인 2건 연속 무효 조건은 발생하지 않았고 resume-cleanup은 필요하지 않았다.

P의 후속 QoS rate 조절은 기존 소스의 유한 rate ladder에 따른 같은 attempt 내 정책 동작이다. 조치 후 위반율은 첫 action_applied부터 H 끝까지 계산했다. 원 strict 판정을 사후 지표로 바꾸거나 유효 미회복을 무효로 처리하지 않았다.

| Case | H 위반율 % | H 실패율 % | H 조건부 p95 ms | 불건강 bin | upload B/s |
|---|---:|---:|---:|---:|---:|
| s2-x01-s | 2.542 | 0.000 | 466.49 | 3 | 1832386.56 |
| s2-x02-s | 2.792 | 0.000 | 467.15 | 3 | 1832386.56 |
| s2-x03-s | 2.833 | 0.000 | 473.18 | 6 | 1826269.87 |
| s2-x04-p | 0.333 | 0.000 | 364.61 | 0 | 610795.52 |

S의 조치 후 위반율은 2.628–3.024%(case 단순 평균 2.827%)이고 같은 날짜 P anchor는 0.000%였다. S의 조건부 p95는 466.49–473.18ms, P는 364.61ms다. S 평균 upload는 1,830,347.66 B/s, P는 610,795.52 B/s로 약 66.6% 낮았다. 이 고정 fixture에서는 분리 단독 S의 조치 후 구간에 위반이 남았고 P의 조치 후 구간에서는 관측되지 않았지만, S n=3/P n=1 및 고정 S→P 순서이므로 일반적인 QoS 필요성·인과 효과를 확정하지 않는다. P의 impact_realized=F를 뚜렷한 장애 영향에서의 회복으로 바꾸지 않는다.

분석은 `fresh_extension_analysis.py`로 수행했다. `analysis/posthoc-results.json`은 기존 canonical main·지정 보충을 각각 별도 cohort로 유지하며 extension을 main29·보충에 합치지 않는다. p95·실패율·upload는 H 전체 기준이고 p95는 성공·내용 일치·deadline 내 요청에 조건부다. 조치 후 위반율과 같은 구간의 지표로 오해하지 않는다.

최신 사용자 지시 `아냐 기한 넘겨도 일단 수행해봐`는 `operations/time-gate-amendment-user.json`에 기록했다. 마지막 case 시작은 19:27:01 KST로 원 19:30 시작 gate 안이었다. down은 20:05:10–20:11:00 KST이며 원 20:00 완료 기한 초과를 숨기지 않는다. 시간 gate 외 비용·동일 원인 연속 무효 중단·cap 1·source 수정 금지 조건은 유지했다.

이번 bed 세션은 9973.972초(2.7705시간)다. 계획 비용률 2,500원/bed-hour는 6,926.37원, 4,000원/calendar-day를 같은 구간에 비례 배분하면 461.76원, 합계 **약 7,388원**이다. 실제 Billing 청구액이 아니며 보존 디스크 등의 종료 후 비용은 남는다. credit_reference는 변경하지 않았고 과거 원장을 표시 잔액에서 이중 차감하지 않았다.

종료 검증의 모든 항목이 통과했다: phase=stopped, VM 3대 TERMINATED, 열린 원장 세션 0, 모든 attempt VERIFIED/cleanup=T, 점유 advisory lock·활성 평가 프로세스 0, frozen source/profile/override 일치. v12 기존 419개 파일의 바이트와 profile SHA도 모두 보존됐다. v12 네 case는 ‘측정 전 거부, injection 0’으로 남겼고 campaign·원자료를 수정하지 않았다. 지시된 새 ensure 증거 디렉터리만 v12 operations 아래 추가됐다.

macOS 화면 조작·수동 시간/네트워크/전원 설정 변경은 0이다. 사용자가 기존 clock guard에 한해 자동 시간 임시 Off/복원 예외를 허용했고 네 lease 모두 normal_release로 원래 network_time=true를 복원했다. 최종 state.json은 status=restored, restored_network_time=true, pending request 없음이다. 과거 UI/시간 서버 표기의 일치를 이번에 새로 검증했다고 주장하지 않는다.

별도 source 회귀 테스트는 실행하지 않았다. source 변경이 없고 validate·freeze·실제 identity·sealed measurement·cleanup·최종 hash 검증으로 이번 실행을 확인했다. Git에는 이 결과 문서만 추가하며 profile·raw·원장·운영 증거는 로컬 ignored 경로에 보존한다.

주요 증거는 v13 root 기준 다음과 같다.

- `operations/preflight-v12-before-ensure-authorized.json`, `operations/ensure-01.log`, `operations/execution-policy.json`
- `operations/profile-v12-v13-diff.json`, `operations/environment-ready-read.json`, `operations/profile-live-identity.json`
- `operations/validate-v13.json`, `operations/forward-credit-before-freeze.json`, `operations/fresh-identity-before-first-case.json`
- `s2-extension/frozen-manifest.json`, `s2-extension/cases/<case>/attempt-01/measurement-sealed.json`, `s2-extension/cases/<case>/attempt-01/judgement.json`, `s2-extension/cases/<case>/attempt-01/cleanup.json`
- `operations/admission-*.json`, `operations/time-gate-amendment-user.json`, `operations/environment-down.log`, `operations/final-verification.json`
- `analysis/analysis-inputs.json`, `analysis/posthoc-results.json`, `analysis/case-dispositions.json`, `analysis/execution-summary.json`
- `operations/v12-preservation-before.json`, 운영 보조 스크립트 사본
