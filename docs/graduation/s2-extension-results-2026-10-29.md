# S2 extension 실행 결과 — 2026-10-29

환경 준비 실패로 S2 extension 4건은 모두 **미실행(attempt 0)** 이다. 15:23 KST에 기존 VM 3대를 기동했으나 클러스터 Ready 확인이 실패해 재시도 없이 중단했고, **15:48:07 KST에 3대 TERMINATED 및 공유 원장 종료를 확인**했다. 장애 주입·S/P 측정은 없으므로 이 실행은 K8s 분리 또는 Neutron QoS의 효과에 대한 새 근거를 제공하지 않는다.

## 실행 조건과 시간

- 브랜치: `codex/fresh-evaluation-execution-20261026`.
- 실행 기준 커밋: `81164c3a9cf08d218f494acd7e47485441b11209` (`15a96a2` 사전 수정 포함). 시작 시 Git 작업 트리는 깨끗했다.
- PROFILE: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v12.json`.
- SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`.
- ROOT: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v12`.
- 모든 harness action은 `export ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env` 후 `bash evaluation/graduation-evaluation.sh --fresh <action>`으로 호출했다. preflight와 사후 분석은 지정된 Python 진입점을 사용했다.
- 코드·profile 변경, 새 GCP VM 생성, 사양 변경, 유료 전환, case 재시도, mutation 재전송은 없었다.

| 시각(KST) | 작업과 결과 |
|---|---|
| 15:22:49 | 새 preflight 9/9 통과: 깨끗한 HEAD, VM identity/type/zone, 3대 TERMINATED, 프로세스·활성 lock 없음, 열린 원장 없음, clock guard, credit 확인 |
| 15:23:11 | environment-ensure 1회 시작, 공유 원장 세션 개시 |
| 15:26:56 | 기존 workload guest ACTIVE 확인 기록; 이어서 클러스터 Ready 대기 |
| 15:42:03 | ensure 실패: `TimeoutError: cluster did not become Ready; last error: kubectl exited 1` |
| 15:42:18 | environment-down 1회 시작 |
| 15:48:07 | down 성공, VM 3대 TERMINATED 확인 후 원장 세션 종료 |
| 15:48:25 | 종료 후 preflight 9/9 재통과 |
| 15:48–15:50 | 사후 분석 생성 및 macOS 시간 설정 확인 |

19:50 admission gate에 도달하기 전에 환경 실패로 종료했다. 따라서 19:50에 새 case를 시작하는 판단 자체가 없었고 이후 재기동하지 않았다. 20:40 down 완료 및 21:30 결과 제출 기한보다 일찍 정리했다. 파일명에 들어간 시각보다 각 증거의 `checked_utc`/원장 시각이 기준이다.

## Case별 판정

`—`는 측정/판정 없음이다. 미실행을 `trial_valid=false`, 회복 실패, `cleanup=true`, 또는 빈 missing 목록으로 바꾸지 않는다. 환경 종료 확인은 case cleanup 판정과 별개다.

| Case | Mode | Attempts | trial_valid | fault_realized | impact_realized | recovered | safety | cleanup | missing | checks.split_only | 결과 |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| s2-x01-s | S | 0 | — | — | — | — | — | — | — | — | 환경 Ready 실패로 미실행 |
| s2-x02-s | S | 0 | — | — | — | — | — | — | — | — | 환경 Ready 실패로 미실행 |
| s2-x03-s | S | 0 | — | — | — | — | — | — | — | — | 환경 Ready 실패로 미실행 |
| s2-x04-p | P | 0 | — | — | — | — | — | — | — | — | 환경 Ready 실패로 미실행 |

extension의 무효 attempt는 0건이다. 모든 case가 admission 이전에 막혔으므로 `judgement.json`이나 `CLEANUP_FAILED` attempt가 없고 `resume-cleanup`도 실행하지 않았다. 근본 원인이 API tunnel, Kubernetes, 네트워크 또는 다른 구성 중 무엇인지는 이번 로그만으로 구분할 수 없다. 고정 소스의 `wait_cluster(900)`가 마지막 `kubectl exited 1`과 함께 timeout했다는 사실까지 확인됐다.

`freeze-extension`은 down 완료 뒤 사후 분석 입력을 만들기 위해 1회 실행했다. 이 manifest는 네 case가 모두 pending인 계획 기록이며, 성공한 환경 준비나 live 실행의 증거가 아니다. 기존 main29·보충 campaign 및 원판정은 변경하지 않았다.

## 사후 분석 지표

`fresh_extension_analysis.py`가 원래 유효 main 첫 attempt와 별도 보충 결과를 읽었다. `all-case-disposition.json`은 같은 입력의 무효·미실행 행도 campaign 경로와 함께 보존한다. extension을 main29 또는 보충과 합치지 않았고 새로운 pooled estimate를 만들지 않았다.

조치 후 위반율은 첫 `action_applied`부터 H 끝까지이며, 조치가 없는 M은 `diagnosis`부터의 비율이다. 따라서 M의 열은 실제 조치 효과를 뜻하지 않는다. p95는 H 전체에서 성공·내용 일치·deadline 내 요청에 조건부인 지연이며, 조치 후 p95가 아니다. 실패율도 H 전체 기준이다. strict 표기는 **V/F/I/R/S/C = trial_valid / fault_realized / impact_realized / recovered / safety / cleanup** 이다. 원 strict를 사후 지표로 승격하지 않는다.

### S2 P / S / M

P 비교 대상은 main 유효 2건과 extension x04(미실행)를 함께 표시하되 cohort를 구분한다. S는 계획 n=3, 실제 n=0이며 M은 main 유효 n=3이다.

| Case | Cohort/mode | 조치·진단 후 위반율 % | H 위반율 % | H 실패율 % | 조건부 p95 ms | 불건강 bin | upload B/s | strict V/F/I/R/S/C |
|---|---|---:|---:|---:|---:|---:|---:|---|
| s2-b01-p | main/P | 0.000 | 0.208 | 0.000 | 358.17 | 0 | 628271.79 | T/T/F/T/T/T |
| s2-b01-m | main/M | 1.721 | 1.917 | 0.000 | 448.71 | 1 | 1821026.99 | T/T/T/T/T/T |
| s2-b02-m | main/M | 2.339 | 2.250 | 0.000 | 447.59 | 3 | 1819279.36 | T/T/T/T/T/T |
| s2-b02-p | main/P | 0.000 | 0.292 | 0.000 | 352.23 | 0 | 623028.91 | T/T/F/T/T/T |
| s2-b03-m | main/M | 1.863 | 1.667 | 0.000 | 441.85 | 1 | 1806172.16 | T/T/T/T/T/T |
| s2-x01-s | extension/S (미실행) | — | — | — | — | — | — | —/—/—/—/—/— |
| s2-x02-s | extension/S (미실행) | — | — | — | — | — | — | —/—/—/—/—/— |
| s2-x03-s | extension/S (미실행) | — | — | — | — | — | — | —/—/—/—/—/— |
| s2-x04-p | extension/P (미실행) | — | — | — | — | — | — | —/—/—/—/—/— |
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

무효 S1 A 행의 높은 위반·실패율은 불완전한 요청과 결측을 포함한 저장 지표이며, 관측된 서비스 성능의 유효 추정치로 비교하지 않는다. 유효 main 및 보충의 `missing=[]`이고 cleanup=T다. 무효 행의 원 missing 목록·attempt 오류·campaign 경로는 `all-case-disposition.json`에 보존했다. S1 V1은 SLO가 달라 P/M/A 분석에서 제외한다.

## 비교와 해석

- **S 대 P, S 대 M:** S 실측이 없어 API 위반율·지연 및 upload goodput의 차이를 계산할 수 없다. x04도 미실행이어서 같은 날짜 P anchor가 없다.
- 기존 S2 main P는 조치 후 API 위반율 0%, H 위반율 0.208–0.292%, 조건부 p95 352.23–358.17 ms였다. main M은 진단 후 위반율 1.721–2.339%, H 위반율 1.667–2.250%, p95 441.85–448.71 ms였다. 이는 기존 날짜의 기술 통계다.
- 기존 main P의 upload goodput은 623,029–628,272 B/s, M은 1,806,172–1,821,027 B/s였다. case 평균은 각각 약 625,650 및 1,815,493 B/s로 P가 약 65.5% 낮았다. 결합 정책 P의 API 지표 개선과 upload 처리량 감소가 함께 관측됐지만, 분리와 QoS 각각의 기여는 이 비교로 분해할 수 없다.
- 기존 main P 2건은 impact_realized=F이고 recovered=T다. 이 결과를 뚜렷한 장애 영향에서 회복한 두 건으로 해석하지 않는다. 별도 보충 P는 impact_realized=T지만 main에 합치지 않는다.
- **이번 실행으로 “K8s 분리만으로는 부족하고 Neutron QoS가 필요하다”는 주장을 뒷받침하거나 반박할 수 없다.** S가 API를 보호하지 못한 유효 결과라면 해당 조건의 QoS 필요성 근거가 되고, 보호했다면 주장을 축소해야 하지만, 이번에는 어느 조건도 측정되지 않았다.
- S1 P의 조치 후 위반율은 0.078–0.136%, M의 진단 후 위반율은 2.444–2.633%, A는 2.243–2.804%다. 이 역시 기존 결과의 사후 기술 비교이며 본 extension의 신규 결과가 아니다.

## 비용과 종료 검증

- 원장에 기록된 실제 bed 세션: **1496.093초 = 24분 56.093초** (15:23:11.116931–15:48:07.210327 KST). ensure·대기·down을 포함하며 VM별 청구 실행시간의 합계가 아니다.
- 고정 계획 비용률 2,500원/bed-hour로 **약 1,039원**, 같은 구간의 calendar-day 비용률 4,000원/일을 비례 배분하면 **약 1,108원**이다. 실제 청구액이 아니며, VM 종료 후에도 보존 디스크 등 비용은 남는다.
- preflight의 12,156초 예약 기준 forward credit margin은 시작 전 11,765.22원, 종료 후 10,627.15원으로 모두 양수였다. 실제 청구 cutoff는 미상이며 12시간 미반영 청구 가정을 사용한다. 과거 원장을 표시 잔액에서 다시 차감하지 않는다.
- VM readback: osk8s-controller(e2-standard-4), osk8s-compute01(n2-standard-8), osk8s-compute02(n2-standard-4) 모두 기존 ID 및 TERMINATED 확인.
- 공유 원장 최신 세션 stopped 기록 확인, 열린 세션 0. 종료 후 평가 프로세스 0, 점유된 advisory lock 0. 남은 비점유 lock 파일은 삭제하지 않았다.
- clock guard는 시작 전후 state가 동일한 restored이며 활성 lease/pending request가 없었다. case를 시작하지 않아 새 clock lease를 얻거나 network time을 Off로 바꾸지 않았다.
- macOS UI에서 자동 시간 설정 **On**을 직접 확인했고 `/etc/ntp.conf`는 **`server time.asia.apple.com`**이다. UI는 Apple(time.apple.com.)라는 표기를 계속 보여 원래 서버 주소를 입력해 완료했으나 표시가 바뀌지 않았다. 관리자 권한의 `systemsetup` 직접 조회는 암호가 없어 불가능했다. 따라서 **On과 설정 파일의 서버는 확인했지만, UI 표기와 실제 daemon 서버의 일치까지 독립 확인했다고 주장하지 않는다**. 이 차이는 미해결 검증 한계로 남긴다.

## 한계 및 후속 위험

- S arm은 계획상 n=3, 단일 날짜의 소규모 사후 분석이다. 이번 실제 extension 표본은 n=0이며 x04 anchor도 없다.
- S1 목적지 compute01은 n2-standard-8로 compute02(n2-standard-4)보다 크다. [ADR-0017](../adr/0017-increase-recovery-target-compute-capacity.md)에 따라 용량·배치 차이를 인과 해석에 반영해야 한다.
- p95는 성공 요청에 조건부이고, M의 진단 이후 구간은 P/S의 조치 이후 구간과 anchor가 다르다. 원 strict/결측을 유지하며 새 가설 검정이나 통합 primary를 만들지 않는다.
- 클러스터 Ready 실패의 근본 원인은 미확정이다. source/profile 수리나 재기동은 이번 작업에서 하지 않았다. 다음 실험 전에 별도 진단이 필요하다.
- 실제 청구 지연·보존 자원 비용과 시간 서버 UI/daemon 확인 한계가 남는다.

## 로컬 증거와 산출물

다음 경로는 ROOT 기준이다. raw·비밀정보·환경 override·profile·원장은 Git에 추가하지 않고 이 결과 문서만 커밋한다.

- `operations/preflight-execution-20261029T1524KST.json`: 실행 전 9/9 검증.
- `operations/environment-ensure-1793254991113783000/`: 실패 로그·phase 시간.
- `operations/environment-down-1793256138973471000/`: 종료 로그와 환경 record.
- `operations/post-down-verification-20261029T1548KST.json`: VM·원장·clock guard·프로세스·lock 재검증.
- `s2-extension/frozen-manifest.json`: down 뒤 보존한 미실행 계획.
- `analysis/posthoc-results.json`: 지정 분석기의 원 출력.
- `analysis/all-case-disposition.json`: 무효·미실행 및 원 campaign을 포함한 판정표.
- `analysis/execution-summary.json`: 실행 실패·시간·비용·종료·clock 확인 범위.
