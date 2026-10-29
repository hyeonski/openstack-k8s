# S2 extension 사전 준비 및 실행자 인계 — 2026-10-29

이번 작업은 사전 수정·오프라인 검증·커밋·읽기 전용 preflight까지만 수행한다. 실제 environment-ensure, live freeze, case 실행, 장애 주입, VM 조작은 수행하지 않았다. 원래 main29·보충·준비 자료와 manifest, release/authorization 체인은 수정하지 않았다.

## 고정 cohort와 구현

순서는 `s2-x01-s`, `s2-x02-s`, `s2-x03-s`, `s2-x04-p`다. purpose/stage는 별도 `extension`, 각 case 최대 1 attempt이며 기존 primary와 합치지 않는다. `freeze-extension`은 깨끗한 커밋과 새 전용 디렉터리를 요구하고 커밋/source가 freeze 도중 변하면 거부한다. 이번에는 synthetic freeze/run만 시험했다.

`FreshS2.finish`의 진단식, 연속 2회 진단, 다음 관측 시각, `now+420 < H end` 분리 진입 조건을 P/S가 공유한다. `split_if_enabled`의 `b['node']` 이동, Ready/readback, `action_requested`/`action_applied`의 대상과 actor도 같다. 차이는 P만 `set_rate`와 후속 QoS rate ladder를 수행하는 것이다. 따라서 QoS 처리 자체의 시간과 QoS 조정 이벤트는 S에서 발생하지 않으며, 실제 실행의 절대 시각까지 동일하다는 뜻은 아니다.

미부착 QoS policy/rule은 fixture에서 그대로 생성한다. `FreshOwnedLab.create_owned`는 해당 policy의 rule을 읽어 `max_kbps == 6000`과 `direction == egress`를 확인하며 포트 부착을 요구하지 않는다. 기존 `S2.cleanup`은 포트가 무정책이면 unset을 건너뛰고 소유 policy를 삭제한다. 이후 `Campaign.verify_cleanup`이 해당 policy 부재를 확인한다. 미부착 삭제, 6000 rule 소유 확인, 다른 rate 거부를 오프라인 테스트했다. 이 경로를 이번에 클라우드에서 실행했다고 주장하지 않는다.

초안의 `fresh_analysis.py`에 있던 두 줄의 S 분기는 live calibration 소스 동등성 검사를 실패시켰다. 기존 release 검사를 넓히는 대신 해당 파일을 원본 그대로 유지했다. 새 `fresh_extension.judge_split_only`가 기존 `_judge`의 결과에서 S2/S extension에 한해 `split_and_qos`를 `split_only`로 바꾸고 safety 및 이에 종속된 safe_recovered만 계산한다. 캠페인과 측정봉인에서 이 경로를 선택한다. P/M은 기존 경로를 그대로 사용한다. UTC 지연, request/bin 계산, 회복 정의, contract_valid, 조치 요청/적용의 H 범위 검사, uploader의 H 전체 제공 조건은 변경하지 않았다.

## v12와 credit

- profile: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v12.json`
- profile SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`
- credit: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/extension-prep-2026-10-29/latest-credit-20261029T144000KST.json`
- credit SHA-256: `efe664e0d83dbce98c1eb3c667c582db99d7e814775dfea293b910bd647e3e23`

v11 대비 변경은 `operations.artifact_root`의 `bed-extension-v12`와 `operations.stability.credit_reference`의 경로/SHA뿐이다. profile의 모든 과학적 값과 host identity가 동일함을 재귀 비교했다. profile 및 credit은 기존 `.state/`·`artifacts/` 정책대로 로컬 증거이며 Git에 강제로 포함하지 않았다.

credit 사용자 원문은 `₩320,850 / ₩435,523 크레딧 사용됨`이다. 보고 시각은 사용자 지시에 따라 2026-10-29 14:40 KST 무렵으로 기록했고 정확한 청구 cutoff로 취급하지 않는다. total 435523, used 320850, displayed_remaining 114673, cleanup reserve 40000, 기타 reserve 20000이다. 과거 원장을 새 표시잔액에서 다시 차감하지 않는다. 기존 12시간 미반영 청구 가정과 비용률을 유지한다.

`fresh_campaign.py validate --profile <v12>`는 통과했다. 예약은 요청된 `4*37*72+1500 = 12156`초다. forward margin은 시간에 따라 감소하므로 최종 값은 커밋 후 생성되는 `extension-prep-2026-10-29/preflight-final.json`의 `checks.credit.forward_credit.margin_krw`를 기준으로 한다.

## 검증과 사후 분석

신규 extension 관련 테스트는 22개다. 실제 분리 함수의 P/S 호출 비교, 1회 cap, synthetic 봉인/판정, H 밖/요청 없는 조치 및 uploader 계약, 미부착 자원 정리, 분석의 분수 시각·결측·첫 attempt 선택·보충 분리·원자료 해시, preflight 실패 차단을 포함한다. 원격 호출 등록부 audit는 348 calls, unregistered 0이고 호출 내용과 정책은 이전 커밋과 동일하다.

첫 sandbox 내부 전체 실행은 240개 중 localhost bind 권한 오류 1개였다. 해당 테스트는 sandbox 밖에서 별도로 통과했다. 추가 테스트를 포함한 최종 전체 회귀는 243개 모두 통과(83.105초), 별도 bind 테스트는 1개 통과(0.510초)했다. 최종 전체 로그는 `extension-prep-2026-10-29/fresh-regression-final.log`, 별도 bind 로그는 `localhost-bind-test.log`다. 최초 실패 로그도 `fresh-regression-sandbox-failure.log`에 보존한다.

`evaluation/fresh_extension_analysis.py`는 saved strict 결과를 보존하면서 S1/P/M/A 및 S2/P/S/M의 조치 후 SLO 위반율, H 전체 위반율·실패율·조건부 p95·불건강 bin·upload goodput을 출력한다. 조치 시각이 없으면 진단 시각을 쓰며, 둘 다 없으면 null이다. 부분 구간의 분모는 등록 도착 index/rate로 계산한다. missingness와 오류를 함께 표시한다. S1 V1은 다른 SLO 때문에 별도 조건으로 제외한다. 출력은 사후 분석이며 원래 primary를 대체하지 않는다고 명시한다.

기존 자료로 읽기 전용 점검한 `historical-posthoc-preview.json`에는 S1 유효8, S2 원래 P/M 유효5, `s2-b03-p-supplement01` 1건이 서로 구분돼 있다. 원래 무효·미실행 행은 제외 사유를 표시하고 재시도로 대체하지 않는다. 이 preview에는 아직 실행하지 않은 extension 결과가 없다.

실행 후 분석할 입력 경로(아래 상대 경로는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/` 기준):

| CLI 인자 | 경로 |
|---|---|
| `--extension` | `bed-extension-v12/s2-extension` |
| `--main` | `bed-a/s1-main-v1` |
| `--main` | `bed-transport-v2/s1-main-transport-v2` |
| `--main` | `bed-transport-v2/s2-main-transport-v2` |
| `--main` | `bed-judgement-closure-v3/s2-main-transport-v2` |
| `--supplement` | `bed-s1-read-v9/s2-supplement-transport-v2` |

출력은 `--output`으로 입력 캠페인 밖의 새 JSON에만 쓴다. 기존 파일을 덮어쓰지 않는다.

## preflight와 실행자 조건

`evaluation/fresh_extension_preflight.py`는 clock guard 실행/설치 소스/복원 상태/활성 lease 및 pending request, 현재 전원의 sleep 설정, 평가 프로세스, 활성 advisory lock, 열린 공유 원장 세션, 등록 ID/type/zone의 VM 3대 TERMINATED, 깨끗한 커밋/source, v12 변경 범위·validate, forward credit을 검사한다. 기존 lock 파일을 삭제하거나 생성하지 않고 읽기 FD로 점유 여부만 확인한다. 모든 검사 실패를 JSON에 남기며 실패 시 종료 코드는 1이다.

최초 sandbox 조회 실패와 커밋 전 실패도 보존했다. macOS 프로세스/GCP 조회는 sandbox 밖에서 재실행했다. AC Power의 sleep은 0이지만 Battery Power는 1분이므로 현재 전원을 실제 조회하며 AC 연결을 유지해야 한다. 일시적인 앱의 sleep assertion만으로 준비 완료 판정을 내리지 않는다. macOS 전원 설정은 변경하지 않았다.

실행자는 커밋 이후 `preflight-final.json`의 모든 check가 true인지 확인하고 ensure 직전 다시 검사한다. 이 결과는 시점 한정 상태 확인이며 17:00 실행 성공 보증이 아니다. 새 출력 파일명을 사용한다.

환경은 기존 driver가 사용하는 `ENV_OVERRIDE_FILE`과 `scripts/lib/common.sh` 방식으로 로드한다. 필수 identity 값은 다음과 같다. 비밀정보를 담은 local.env 내용은 출력하거나 커밋하지 않는다.

| 변수 | 값 |
|---|---|
| `ENV_OVERRIDE_FILE` | `/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env` |
| `ENVIRONMENT_NAME` | `cloud-gcp-amd64-greenfield` |
| `GCP_PROJECT_ID` | `openstack-k8s` |
| `GCP_ZONE` | `asia-northeast3-a` |
| `STATE_DIR` | `/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield` |

기존 `fresh_release_driver.py`는 옛 release 승인과 ACTIVE 파일을 읽으므로 extension에 그대로 실행하지 않는다. 별도 지시를 받은 실행자가 준비 문서 6절의 v12 CLI를 사용한다. 16:30 ensure, 17:00 첫 case, 19:50 이후 새 case 금지, 20:40 down 완료를 적용한다. 상속 profile은 `cost-bounded-targets-only`이고 예전 calendar 값도 보존하므로 이 새 시각을 자동 강제하지 않는다. 실행자가 각 case admission 전에 해당 cutoff를 확인해야 한다.

실패 시 재시도·현장 source 변경은 금지한다. 소유 cleanup만 복구하고 무효 결과를 보존한다. cleanup 확인 실패나 비용 gate 실패면 중단/down한다. 실험을 시작하기 전의 조회만으로 터널·Neutron·서비스 준비 중 오류를 배제할 수 없으며, 남은 credit margin은 실제 청구 보증이 아니다.
