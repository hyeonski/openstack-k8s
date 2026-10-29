# 평가 운영·수리 기록 통합본 (2026-10-27 ~ 10-29)

본평가 진행 중 작성한 운영 결정·수리·보충·중단 기록을 시간순으로 합쳤다. 내용은 원문 그대로이며 각 절에 원래 파일명을 남겼다. 제목 수준만 한 단계 낮추고 상대 링크를 새 위치에 맞게 고쳤다. 결과 해석은 [최종 결과](../fresh-evaluation-final-results-2026-10-29.md)와 [통합 분석](../evaluation-results-analysis-2026-10-29.md)을 따른다.

## 목차

- 계측 수정 cohort 운영 기록 (`measurement-repaired-execution-2026-10-27.md`)
- 무효 7건 원인 검토와 잔여 평가 안정화 합의 (`evaluation-stability-consensus-2026-10-28.md`)
- 평가 안정화 구현 및 재부팅 검증 인계 (`evaluation-stability-implementation-2026-10-28.md`)
- 연결 읽기 복원과 추가 A 1회: source 전환 (`transport-continuation-and-supplement-2026-10-28.md`)
- S1 main API 터널 연결 유실과 소유 정리 (`s1-main-api-tunnel-repair-2026-10-28.md`)
- S2 IAP 읽기 실패와 무효 봉인 복원 (`s2-iap-judgement-closure-2026-10-28.md`)
- S3 본시험 M 정리 중 API 터널 유실과 cleanup-only 복구 (`s3-cleanup-api-tunnel-repair-2026-10-28.md`)
- S3 실제 OS 시계 보정과 명시적 retry (`s3-os-clock-step-repair-2026-10-28.md`)
- S4 첫 off 본시험의 주입 전 OS 시각 보정 무효 (`s4-pre-injection-clock-invalid-2026-10-28.md`)
- SSH/IAP 명시 읽기 재시도와 S2 P 보충 1회 (`ssh-read-and-s2-supplement-2026-10-28.md`)
- S3 소유 binding 읽기와 controller 변경 전 정리 검증 (`s3-binding-read-and-precontroller-closure-2026-10-28.md`)
- 보충4회 승인과 worker 축소 후 probe 읽기 보완 (`four-supplement-and-owned-probe-reads-2026-10-28.md`)
- 장애 주입 전 DNS 통신 장애 복구 (`pre-injection-dns-repair-2026-10-28.md`)
- 안정화 재개 후 첫 case 준비 실패와 소유 정리 (`evaluation-stability-execution-pause-2026-10-29.md`)
- Inventory 준비 실패 수정 및 재개 검증 (`evaluation-inventory-repair-2026-10-29.md`)
- S1 supplemental operational read repair — 2026-10-29 (`evaluation-s1-read-repair-2026-10-29.md`)
- S3 process capture continuation, 2026-10-29 (`evaluation-s3-capture-repair-2026-10-29.md`)
- DNS 준비 검사 복구 및 마지막 보충 인계 (`evaluation-dns-readiness-repair-2026-10-29.md`)
- S2 extension 사전 준비 및 실행자 인계 — 2026-10-29 (`fresh-extension-preparation-2026-10-29.md`)
- S2 extension 실행 결과 — 2026-10-29 (`s2-extension-results-2026-10-29.md`)

---

## 계측 수정 cohort 운영 기록

_원래 파일: `docs/graduation/measurement-repaired-execution-2026-10-27.md`_


2026-10-27 20:56 KST 새 preparation 준비를 시작했다. 사용자 재개 승인과 profile 해시는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/restart-authorization.json`에 기록한다. 이전 V7의 7 attempt와 HOLD를 보존하고 새 완료 건수에 포함하지 않는다.

단일 실행자는 `evaluation/fresh_release_driver.py`이며 flock으로 중복 실행을 차단한다. 기존 동일 3대만 ensure하고 공유 원장을 사용한다. 150초 read-only cadence 점검은 `evaluation/fresh_cadence.py`가 실험과 동일한 snapshot 메서드로 수행한다. 정리 후 없는 MHC/deployment의 NotFound만 예상 결측으로 분리한다. 나머지 조회 오류나 15초 초과 간격은 주입 전 조사한다. 이 점검은 준비 실험을 대체하지 않는다.

preparation은 S4 on/off, S1 P/V1, S2 P/M, S3 P3600/M3600 순서로 수행한다. main은 모든 preparation go/no-go 충족 후 기존 등록 순서로만 진행한다. 계측 오류는 원판정 보존과 다음 주입 차단 후 조사 상태로 남기고 `fresh_failure_policy.next_action`으로 안전·정리·비용 오류를 구분한다. 시간 목표는 advisory이며 고정된 종료 시각으로 범위를 축소하지 않는다.

기존 정상 보정3+2는 profile에 등록된 원자료 해시와 고정 S1 workload·SLO·baseline 판정 계약을 재사용한다. 이번 계측 변경은 S3/S4 OpenLoopProbe 도착 대기와 S4 snapshot 수집에 해당하며 기존 S1 정상 보정 workload와 원판정에는 영향을 주지 않는다. A DEV는 원 freeze, 증거 해시 및 동일 S1 앱·부하·baseline·분석 코드 해시를 재검증하여 재사용하며 주 분석 표본 수는 0이다. 새 preparation과 main은 동일한 새 source freeze를 요구한다.

초기 추정은 준비 착수 후 첫 main 6~7시간, 전체 28~30시간이다. 전체 37 case와 단일 lifecycle의 보수 계획 추정은 28.82시간, 누적 비용 약139,347원이다. 이는 Billing 실측이 아니며 신규작업 한도146,234원 및 정리reserve40,000원을 유지한다. 기존 불확실성reserve20,000원은 공유 원장에서 단1회만 계산한다.

회귀 6개 통과 및 driver/cadence Python 구문 검증 완료. 실제 cadence 증거와 첫 주입 시각·건수·최종 분석은 새 root에 추가한다.

---

## 무효 7건 원인 검토와 잔여 평가 안정화 합의

_원래 파일: `docs/graduation/evaluation-stability-consensus-2026-10-28.md`_


작성일: 2026-10-28 KST. Codex와 실제 Claude CLI `claude-opus-5-5`의 토론 기록에 근거한다.

**이 문서는 구현·검증·재개 계획이다. 이 작업에서 평가 코드, macOS 설정, 인프라 상태는 변경하지 않았으며 실험 일시중지는 유지한다. 현재 상태는 NO-GO다.** 시각 보호는 검증을 통과할 때만 채택하는 우선안이다. 향후 무효가 없다는 보장은 아니다.

### 1. 검토 범위와 대화 기록

첫 질문은 요청대로 다음 문장만 사용했다.

> 어제부터 시작한 실험이 7건이나 무효처리가 되었다. 원인을 진단하고 무엇을 해결해야할지 말해달라

Claude가 읽은 것은 Codex가 점검하여 별도 폴더에 제공한 익명화된 7건 요약, 실행 사실, 관련 코드 발췌·파일이다. Claude가 작업공간 전체나 원본 로그 전체를 독립적으로 조사한 것은 아니다. 원본과의 대조는 Codex가 수행했다. 외부 전송 승인 범위에는 OS 설정 변경이나 실험 재개가 포함되지 않는다.

- 대화 세션: `e874fe49-963f-4437-af92-84edbcf2fdfd`
- 기록: [토론 아티팩트](../../../artifacts/evaluation-stability-discussion-2026-10-28/)
- 1차: 독립 진단. 2차: Codex 반론과 대안 비교. 3차: 구체적 운영안 검토. 4차: 남은 수치·조건 합의 확인.
- 원본 판정·중단 상태: [재부팅 체크포인트](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/reboot-pause-checkpoint-2026-10-28/checkpoint.json)

### 2. 왜 7건이나 무효였는가

본시험 26개 attempt 중 유효 19건, 무효 7건이다(약 26.9%). 준비실험의 무효 2건은 이 숫자에 포함하지 않는다. 이 비율은 작품의 복구 실패율이 아니다. 또한 시행마다 코드와 환경이 바뀌었으므로 이를 독립·동일분포 실패확률로 보고 남은 시행의 실패 건수를 예측하지 않는다.

| 원래 case | 직접 계기 | 무효를 확대·지속시킨 문제 |
|---|---|---|
| S1-b02-A | H 종료 후 Job 완료 확인의 API reset/refused | 연결이 약 18초 후 복구됐지만 실행은 이미 예외 경로로 진입. 최종 자료 수집 누락 |
| S2-b03-P | 진행률 읽기의 IAP 4047 | 필요한 읽기 경로의 복구 누락, H 종료 증거 누락. 분석기도 미정의 `start`를 참조하여 별도 실패 |
| S3-b02-M3600 | H 종료 후 worker 정리 확인의 API 연결 실패 | 실제 변경은 완료됐지만 후속 읽기 실패를 실행 전체 오류로 처리. 이후 동일 객체 확인 및 정리 완료 |
| S3-b03-M3600 | 주입 전 OpenStack port 읽기의 IAP 4047 | 읽기 재시도 누락. 적용하지 않은 controller 변경의 원복 파일을 정리가 요구하는 추가 문제 |
| S3-b03-P3600 | Mac 시각 약 +3.980초 보정 | UTC 지연·요청 간 시계 일관성 기준 위반. H와 정리는 완료 |
| S4-b01-off | baseline 중 Mac 시각 약 +2.043초 보정 | 일부 요청 지연이 UTC 계산에서 부풀려짐. 장애 주입 전에 무효 |
| S4-b02-on | H 종료 후 management API TLS handshake timeout | 실제 복원 변경 뒤 확인 읽기가 실패해 실행 오류 처리. 이후 동일 객체 및 정리 검증 완료 |

따라서 연결·관측 경로에서 시작한 5건과 시계 보정 2건이다. 연결 5건의 네트워크 최초 원인까지 밝혀진 것은 아니다. IAP 연결 생성 방식, 특정 네트워크 종단, Mac 네트워크 변화 등을 원인으로 확정하지 않는다.

근본적인 운영 문제는 오류 하나를 만날 때마다 해당 호출만 보완했던 것이다. workload API, management API, SSH/IAP, OpenStack, 최종 수집, 정리 확인에 일관된 실패 처리 경계가 없었다. 여기에 측정과 정리의 오류가 같은 판정으로 합쳐졌고, Mac 자동 시각 보정을 예방하지 못했다.

참조: S1 연결 (`s1-main-api-tunnel-repair-2026-10-28.md`, 본 통합본에 포함), S2 종료 판정 (`s2-iap-judgement-closure-2026-10-28.md`, 본 통합본에 포함), S3 정리 연결 (`s3-cleanup-api-tunnel-repair-2026-10-28.md`, 본 통합본에 포함), S3 주입 전 연결 (`s3-binding-read-and-precontroller-closure-2026-10-28.md`, 본 통합본에 포함), 시계 및 보충 기록 (`four-supplement-and-owned-probe-reads-2026-10-28.md`, 본 통합본에 포함), S4 시계 (`s4-pre-injection-clock-invalid-2026-10-28.md`, 본 통합본에 포함).

### 3. 토론으로 바뀐 판단

1. **시계 처리:** Codex의 초기 선호는 전체 측정을 monotonic 기준으로 바꾸는 것이었다. Claude는 요청 예약, baseline, 관측창, 이벤트 지연, 원격 probe의 시계 연결까지 바뀌므로 이번 실험 중간에 새 측정 계약을 도입하는 부담이 크다고 반론했다. 이번 잔여 평가에는 기존 UTC 계약을 보존하고, 자동 시각 보정을 제한하는 운영 보호를 먼저 검증한다. 전체 monotonic 전환·Linux 실행기 이전은 이번 기본안에서 제외한다.
2. **4047 분류:** 실제 문자열은 `Error while connecting [4047: 'Failed to lookup instance']`다. Codex가 기존 `error while connecting to`와 일치한다고 한 주장은 철회했다. 현재 SSH 분류기는 4047을 별도로 인식하지만, 다른 분류기와 실제 호출 연결 상태까지 확인해야 한다. 문자열 분류와 호출 경로 둘 다 회귀시험한다.
3. **S4 정상성:** 요청의 `ok=true`만으로 SLO 정상이라 할 수 없다. 별도 monotonic 진단 p95는 약 303/319/287ms였지만, 이는 시계 왜곡을 뒷받침하는 진단 자료일 뿐 기존 UTC 무효 판정을 바꾸지 않는다.
4. **수동 정리:** 사람이 개입했다는 이유만으로 정리를 영구 미완료로 두지 않는다. 조치 시각·대상 UID·journal과 조치 후 자동 readback으로 검증한다. H 중 개입은 결과에 미친 영향을 별도 평가한다.
5. **재시도 간격:** 총 3회라도 5초·10초 대기라면 즉시 연결 거부 시 15초에 모두 소진된다. 30초 단절을 견디려는 운영 읽기는 10초·25초 대기로 바꾸고 총 deadline 안에서 시험한다.

### 4. 구현할 변경

#### 4.1 모든 운영 읽기를 동일한 원칙으로 관리

실험 실행 경로의 원격 호출 목록을 만든다. 각각 plane, operation, identity 검증, read/mutation/capture 구분, 필수 여부, deadline을 등록한다. 임의 shell 문자열을 보고 읽기라고 추측하여 자동 재실행하지 않는다.

- 관리 API, 작업 API, SSH/IAP, OpenStack, 자료 회수, 정리 검증을 포함한다. 등록되지 않은 읽기는 preflight에서 발견하여 차단한다.
- 한 번만 관측해야 하는 host 통계 등은 원격에 원본을 먼저 저장하고 같은 파일의 다운로드만 재시도한다. 과거 관측 시각의 값을 새 관측으로 대체하지 않는다.
- 부하 발생기의 서비스 요청에는 재시도를 넣지 않는다. 서비스 오류율과 지연을 숨기면 안 된다.
- 조치·장애 주입·scale 등 mutation은 응답이 사라져도 재전송하지 않는다. journal과 대상 UID 및 실제 상태로 적용 여부부터 판단한다.
- 판정·정책 결정·안전 증명에 사용되는 읽기는 필수다. 어느 계약 항목에도 영향을 주지 않는 것이 입증된 관측만 비필수로 분류할 수 있다.

운영 읽기의 기본 정책은 다음과 같다.

| 항목 | 정책 |
|---|---|
| 시도 횟수 | 최초 포함 총 3회 |
| 각 명령 상한 | 최대 20초, 남은 전체 예산이 더 작으면 축소 |
| 대기 | 1차 실패 후 10초, 2차 실패 후 25초 |
| 준비 전·측정 봉인 후의 전체 예산 | 최대 90초. 명령, reconnect, identity 검증, 대기를 모두 포함 |
| baseline 시작 이후 및 H 중 | 기존 해당 단계 deadline을 늘리지 않음. 남은 예산에 맞춰 시도·대기 축소/중단 |
| 실패 종류 | 원문 4047, TLS handshake timeout, reset/refused, broken pipe 등 재현 fixture로 분류 확인 |
| 즉시 중단 | 권한·인증 오류, 실제 대상 부재, identity 불일치 등 영구 오류 |

identity 확인도 같은 예산에 포함하며 중첩된 3×3 재시도는 금지한다. 공통 엔진의 시간 예산과 경로별 정책을 시험한다. 특히 정책 결정에 쓰이는 읽기 지연이 작품의 반응 시간에 영향을 줄 수 있으므로 retry 이력을 남기고 코드 버전을 구분한다. 전송 보완이 측정에 무조건 중립이라고 가정하지 않는다.

#### 4.2 측정 자료를 먼저 확정하고 정리를 별도로 완료

흐름을 `H 종료 → 필수 자료 회수 → 완전성/identity/시계 검사 → measurement_sealed → cleanup → cleanup_verified`로 만든다.

봉인에는 실제 주입·H 종료 증거, 요청 수·원자료 완전성, identity, 시계 검사 및 파일 해시가 필요하다. 파일과 봉인 기록을 안전하게 flush/fsync한다. 봉인은 S3 worker 축소, S4 모드 복원 등 정리 mutation보다 앞에 와야 한다.

- 봉인 후 정리 실패가 측정 원자료를 덮어쓰거나 삭제해서는 안 된다.
- 정리 후에야 확인할 수 있는 안전 증명은 계속 필수다. 자료가 봉인됐다는 이유로 안전 검사를 생략하지 않는다.
- 다음 case는 정리가 자동 readback으로 검증된 후에만 시작한다.
- 정리의 전제조건은 실제 적용 journal에서 도출한다. 적용하지 않은 변경의 백업 파일을 요구하지 않는다.
- 예산 내 회복은 `transport_retry`, 최종 실패는 `execution_error`와 `phase`로 남긴다. 봉인 전 관측 공백과 봉인 후 정리 오류를 구별한다.
- 수동 복구 후에도 시각·UID·조치를 기록하고, 등록된 자동 readback으로 검증해야 `cleanup_verified`가 된다.

**원래의 엄격한 판정은 execution_error가 있으면 계속 무효일 수 있다.** 측정/정리 분리는 이를 몰래 완화하기 위한 것이 아니다. 예산 내 회복으로 오류를 예방하고, 예방하지 못한 경우에도 측정 증거와 실패 단계를 보존하여 전건 공통 보조분석이 가능하게 만드는 것이다.

#### 4.3 분석기가 실패한 시행도 명확히 판정하도록 수정

`fresh_analysis.py`의 `start`/`end` 초기화와 사용 guard를 고친다. H 미종료, 주입 전 실패, 빈 원자료가 분석기 exception으로 끝나지 않고 정확한 missing/unknown 사유를 반환하게 한다.

기존 26건을 새 디렉터리에 sidecar 재계산한다. 기존 raw, verdict, hash는 수정하지 않는다. 정상 유효 19건의 판정·지표 동일성을 확인한다. S2-b03-P의 분석기 오류가 구체적 H 누락 판정으로 바뀌는 것은 차이 목록에 명시한다.

#### 4.4 시각 보호: 검증될 때만 선택하는 우선안

Apple은 `systemsetup -setusingnetworktime (on|off)`와 관리자 권한 사용을 문서화한다. 그러나 이것이 모든 clock step을 차단한다는 보장은 아니다. [Apple 공식 설명](https://support.apple.com/en-mn/guide/remote-desktop/apd95406b8d/mac)

구현 단계에서 사용자가 OS 변경·관리자 권한·복원 장치 설치를 명시적으로 허용한 경우에만 다음을 수행한다.

1. 기존 NTP 설정을 저장하고 측정 전에 동기화와 기존 clock-offset bound를 확인한다.
2. baseline 직전 자동 보정을 끄고, wall/monotonic 차이 및 원격 offset을 계속 기록한다. 시스템 sleep을 막고 sleep/wake 발생도 확인한다.
3. 측정 봉인 뒤, 측정창 밖에서 원래 설정을 복원한다. 단순히 무조건 on으로 바꾸지 않고 원설정을 복원한다.
4. 프로세스 crash에도 복원되도록 독립 watchdog, 만료, 재부팅 복원 절차를 구현·시험한다. 관리자 권한의 LaunchDaemon이 필요할 수 있으며 이 설치도 승인 범위에 포함해야 한다.

제안값은 측정 보호 허용 최대 35분, watchdog 만료 45분이다. 실제 H는 S1/S2/S4 1200초, S3 900초이며 S1 전체 부하는 1800초다. **H만 보고 35분이면 충분하다고 판단하지 않는다.** baseline부터 전체 부하 및 필수 자료 회수·봉인까지 case별 최악 예산표를 먼저 계산한다. 35분에 들어오지 않으면 시작 전에 한도를 재등록하고 검증한다. 자료를 버리거나 H를 늘려 맞추지 않는다.

만료 시 현재 측정을 중단으로 기록하고 원설정을 복원한 뒤 다음 case를 막는다. 보호를 켰는데 실제 clock step이 재발하거나 원상복원 검증이 안 되면 NO-GO다. 원래 시계 판정 기준을 완화하지 않는다.

시각 보호를 구현할 수 없거나 실측 검증에 실패하면 일시중지를 유지한다. 그때 완전한 monotonic 측정 계약과 별도 데이터 구간을 설계하여 결정한다. 기존 시계 무효 2건을 monotonic 계산만으로 구제하는 대안은 사용하지 않는다. 특히 시계가 뒤로 이동하면 기존 dual-clock 대기가 실제 요청 발사 간격까지 바꿀 수 있다.

### 5. 구현 순서와 담당 파일

| 순서 | 대상 | 완료 증거 |
|---|---|---|
| 1 | 원자료·26건 판정·소스 snapshot | 해시 목록과 원본 불변 확인 |
| 2 | `evaluation/fresh_analysis.py` | 누락 H/빈 자료/주입 전 실패 처리, 26건 sidecar 차이표 |
| 3 | `evaluation/fresh_transport.py`, `fresh_live.py`, `fresh_scenarios.py`, 호출하는 runtime/worker 관리 경로 | 원격 호출 등록표, 관리·작업·SSH·OpenStack coverage, shared budget 시험 |
| 4 | `fresh_collection.py`, `fresh_campaign.py`, 시나리오 정리 경로 | durable capture, 봉인 순서, journal 기반 정리, 자동 readback |
| 5 | 관련 failure-path 테스트 | 아래 오프라인 회귀 결과 |
| 6 | 실행 driver와 새 시각 보호/복원 모듈 | OS 승인 기록, 시각 보호 및 독립 복원 검증 |
| 7 | 새 소스 snapshot·운영 정책 등록 | 기존 측정 계약 보존, 버전별 차이 및 새 freeze |
| 8 | 표본 외 통합 검증 1회 | GO 체크리스트와 로그 |

이미 보완된 부분은 재구현하지 않고 coverage와 동작을 검증한다. 기존 frozen source를 덮어쓰지 않는다. 새 driver는 새 snapshot을 사용하며, 이전 source 해시를 요구하는 재부팅 재개 절차는 새 코드 등록 절차에 맞춰 명시적으로 갱신한다. pause 파일을 지워 억지로 시작하지 않는다.

### 6. 재개 전 시험과 GO 조건

오프라인 회귀는 실제 OS 시계를 바꾸지 않는 가짜 clock/transport를 사용한다.

- 5/15/20/30초 단절 후 회복, 120초 지속 실패, 즉시 실패와 느린 timeout 각각의 총 예산.
- retry 중 identity 변경, 권한 오류, mutation 응답 유실. 잘못된 mutation 재전송 0건.
- H 종료·도착 수·정상 trace 지표 보존, 서비스 요청 자체 retry 0건.
- baseline/관측/최종 수집/cleanup별 오류 및 raw hash 보존.
- 시계 +2/+4/−2/−4초 변동을 기존 기준이 탐지하는지 확인.
- watchdog 정상 종료·강제 종료·만료·복원 경로 시험.

통합 qualification은 **표본 외 1회, 실측 45분 상한**으로 한다. 시계 관측 최소 30분과 운영 읽기 adapter에서의 20초 synthetic 실패를 겹쳐 수행한다. 공유 네트워크나 VM을 실제로 차단하지 않으며 실제 서비스 장애를 주입하지 않는다. 정리/관리 readback은 소유권이 명확한 fixture에서 검증한다.

통합 검증에는 실제 자동 보정 off→on/원설정 복원 1주기와 그 시각 경계가 포함돼야 한다. 실제 재부팅은 사용자 예정 재부팅에 맞춰 복원을 확인하며, 이 계획만으로 Mac을 강제 재부팅하지 않는다. 구현·승인 대기·사용자 재부팅 대기까지 45분 안에 끝난다는 뜻이 아니다.

GO는 다음이 모두 충족될 때만 선언한다.

1. 오프라인 회귀 및 원자료 재분석 차이 검토 통과.
2. 등록되지 않은 호출 0건, 중복 mutation 0건, 20초 읽기 실패의 예산 내 회복.
3. H/요청 수/정상 지표 보존, 시계 step 0건, 기존 offset bound 준수.
4. 자료 봉인 및 정리 검증, 시각 원복·watchdog·재부팅 복원 검증.
5. source/profile/policy/허용 시행 수가 일치하고, 기존 객체 identity와 fixture 상태 정상.
6. 중복 driver/CLI/probe가 없고 단일 실행 lock 확보 가능.
7. 사용자의 명시적 재개 지시.

qualification 실패 시 자동으로 같은 준비를 계속 반복하지 않는다. 원인과 필요한 수정만 보고한다. 준비 8건 전체 재실행은 기본 요구가 아니다. 다만 작품의 동작, fault 강도, 부하, SLO, H 등 과학적 조건이 바뀌면 이 검증만으로 이전 준비 결과를 재사용할 수 없다.

### 7. 재개 후 시행 순서와 중단 원칙

현재 승인 범위는 본시험 잔여 3건 다음 고정 보충 4건이다.

1. `s4-b02-off` → `s4-b03-off` → `s4-b03-on`
2. `s1-b02-a-supplement01` → `s2-b03-p-supplement01` → `s3-b02-m3600-supplement01` → `s3-b03-m3600-supplement01`

`s3-b03-p3600`, `s4-b01-off`, `s4-b02-on`의 추가 보충은 권고 대상으로 기록하되 아직 실행 범위에 넣지 않는다. 승인된 보충은 각각 최대 1회이며 원래 첫 attempt를 덮어쓰지 않는다.

- 일시 읽기 오류가 사전 예산 안에서 복구되고 증거가 완전하면 같은 시행을 계속한다.
- 하네스 원인의 무효 또는 시각 보호 실패가 1건 발생하면 **다음 시행 입장을 자동 중단**한다. 진행 중인 안전한 정리와 승인된 제한적 복구는 수행하고 원인을 보고한다.
- 실제 서비스 미복구는 유효한 실험 결과다. 좋은 결과를 얻기 위한 재시도는 하지 않는다.
- 새 별도 attempt나 과학적 계약 변경은 기존 허용 범위를 넘겨 자동 실행하지 않는다.

중단 체크포인트의 남은 7건 추정은 약 6시간 26분(마지막 정리 포함)이었다. 이는 시각 보호, 새 검증, 재부팅 대기, 추가 보충을 포함하지 않는 과거 운영 추정이다. 구현·검증 후 실제 잔여 시간을 다시 계산하며 현재 완료 날짜를 확정하지 않는다.

### 8. 보고서에 어떻게 사용하나

- **원래 주분석:** 계획된 29건의 첫 attempt와 원래 엄격한 판정을 유지한다. 현재 19건 유효이며 남은 3건이 모두 유효해도 최대 22건이다. 7건 무효를 제외한 분모와 시나리오·조건별 유효 수를 명시한다.
- **공통 보조분석:** 측정 완료와 정리를 구분한 규칙을 과거 26건, 최종적으로 29건 전체에 일관되게 적용한다. 사후 규칙임을 명시한다. 과거에 없던 `measurement_sealed`를 만들어 넣지 않고, 원증거에 대한 사후 완전성 감사라고 부른다. 정리 오류 2건의 구제 가능성은 감사 전 확정하지 않는다.
- **보충 분석:** 승인된 4건은 별도 표로 보고한다. 원래 무효를 유효로 대체하여 모두 동일한 29개 표본처럼 발표하지 않는다.
- 버전별 transport/시각 운영 변경, 수동 개입, 결측 편향을 공개한다. 특히 조건별 반복 수와 완전한 paired block이 부족하면 그 비교의 불확실성을 그대로 보고한다.
- 시계 무효 2건의 monotonic 수치는 원인 진단에만 사용한다. 측정 계약을 소급 변경하여 성능 개선 주장의 근거로 삼지 않는다.

### 9. 지금 완료한 것과 남은 것

완료: 7건 원인 대조, Opus 5.5 토론, 반론·정정, 안정화 구현·검증·재개 계획 문서화.

미완료: 위 코드 변경, OS 설정/복원 장치 허용 및 설치, qualification, 사용자 재개 지시, 남은 실제 측정. **이 문서의 합의를 구현 완료 또는 실험 재개 가능 판정으로 읽으면 안 된다.**

---

## 평가 안정화 구현 및 재부팅 검증 인계

_원래 파일: `docs/graduation/evaluation-stability-implementation-2026-10-28.md`_


담당: Astra High `01a1829e-502e-7792-ab6c-ddbbd3f2fe91`. 이 문서는 기존 합의와 세션 인계 문서의 구현 결과를 기록한다. 최종 GO는 실제 재부팅 복원·최종 소스 검증·새 freeze를 모두 확인한 뒤 별도 증거에 기록한다. 작성 중에는 기존 pause 세 파일, 기존 active pointer, heartbeat PAUSED를 유지한다.

### 구현 범위

- 운영 읽기: `fresh_read_budget.py`가 최초 포함 3회, 명령 20초, 작업 90초, 10/25초 backoff를 공유한다. 중첩 호출은 같은 deadline을 사용한다. 구조화된 Kubernetes/OpenStack/GCP 및 명시적 SSH 읽기만 등록한다. 서비스 proxy/SQL probe와 mutation은 자동 재전송하지 않는다.
- `config/fresh-read-registry.json`: 원격 호출 AST와 파일 전체 SHA를 함께 등록한다. 새 호출뿐 아니라 변수·상수 변경도 preflight에서 막는다. legacy standalone 경로와 typed dispatcher도 명시하며, 이것이 legacy 평가 실행 권한을 추가하지 않는다.
- 원격 host/CPU/SQL integrity capture는 한 번만 생성한 고유 파일을 회수한다. 응답 유실 뒤 새 관측을 만들어 대체하지 않는다. mutation intent를 기록하고, 지원되는 소유 변경은 응답 유실 뒤 같은 UID/이름/ownership 상태를 읽어 확인한다.
- H 종료·필수 자료·identity·clock·strict 분석 가능성을 검증한 뒤 격리된 `measurement/` 사본과 해시를 fsync하여 봉인한다. 시각 설정 복원 뒤 cleanup을 진행하며 cleanup 증명은 별도로 필수다. cleanup 실패는 기존 strict verdict에서 계속 invalid다.
- 분석기의 H 누락 초기화/guard만 고치고, cleanup 전 봉인용 별도 검사 인자를 추가했다. 기본 strict 판정은 유지한다. 과거 main26 sidecar의 valid19 판정·지표가 동일하며 invalid7은 그대로 invalid다. S2-b03-P만 분석기 exception 대신 H 누락 등 구체적인 missing 사유를 얻는다. 이 사례의 execution/safety/fault_realized/provenance/metrics/missing/impact_realized가 달라졌으며 trial_valid는 계속 false다. 나머지 25건은 지표를 포함해 동일하다.

### H와 정상 읽기 경계

기존 성공한 읽기는 기존 호출의 완료 규칙을 유지해야 한다. 원래 loop가 H 직전 시작한 정상 읽기 또는 마지막 진행률 확인은 H 경계 뒤에 끝날 수 있었으며, 분석 구간은 항상 실제 주입 시각부터 고정된 H다. 이를 새 global hard cutoff로 바꾸면 정상 마지막 snapshot도 실패할 수 있다.

따라서 baseline의 원래 hard deadline은 모든 시도에 적용하고, H의 남은 예산은 **추가 재시도와 그 identity/backoff**에 적용한다. 최초 정상 호출도 명령 20초/원래 caller timeout을 넘을 수 없다. H 이후 실패를 재시도로 살리지 않으며, H·부하·요청 분모·분석 구간을 늘리지 않는다. 이 구분은 fake clock 회귀로 검증한다.

30분 live qualification은 scientific H를 설정하지 않는다. 이후 이 H 전용 분기와 calibration binding의 정확한 운영 patch가 반영되면, qualification 당시 소스를 별도 보존하고 literal reversal 검사를 통해 그 시험에서 실행된 경로가 바뀌지 않았음을 검증한다. 해당 H 분기를 live 시험했다고 주장하지 않으며 최종 소스의 오프라인 경계 시험으로 검증한다. 소스가 일반적으로 달라도 허용하는 우회는 없다.

### 시각 보호 운영

실제 설치물:

- `/Library/LaunchDaemons/dev.openstack-k8s.clock-guard.plist`
- `/Library/Application Support/openstack-k8s-clock-guard/service.py`
- root 상태·로그: `/var/db/openstack-k8s-clock-guard`
- UID 501 요청 디렉터리: `/var/run/openstack-k8s-clock-guard`

설치 전 원설정은 Network Time **On**, 서버 **time.asia.apple.com**이다. 서비스는 root 소유의 고정 프로그램이며, 요청에 임의 명령/경로를 허용하지 않는다. PID·UID·시작 시각·boot ID·고유 token을 확인하고 원설정을 fsync한 뒤 보정을 끈다. runner 종료, 만료, 서비스 crash/restart, clock step, 재부팅에서 원설정을 복원한다. clock step·lease 만료·daemon 재시작은 평가 부모에게 SIGTERM을 보내며 부모는 어댑터 process group을 중단하고 소유 정리로 전환한다.

35분/45분은 채택하지 않았다. 기존 전체 어댑터 상한 5,400초 안에서 마지막 90초를 봉인에 예약한다. 보호 요청부터 어댑터는 최대 5,310초보다 초기 arm 시간을 뺀 예산, 봉인은 최대 90초다. 보호 ceiling은 90분, 독립 daemon watchdog ceiling은 95분이다. 기존 전체 실행 예산을 늘리지 않는다.

| 구간 | 기존 과학적 시간 | 보호 예산에 포함되는 것 |
|---|---:|---|
| S1 | H 1,200초, 전체 부하 1,800초 | baseline, 전체 부하 종료, Job/로그·host/CPU 수집, 검증·봉인 |
| S2 | H 1,200초, uploader 1,800초 | baseline, 원래 tail, 원격 원자료·integrity 수집, 검증·봉인 |
| S3 | H 900초 | baseline, 원래 DB/volume·controller 증거, 검증·봉인 |
| S4 | H 1,200초 | baseline, 원래 capacity/identity 증거, 검증·봉인 |
| 공통 | 기존 어댑터 5,400초 | 위 작업 전부와 봉인을 합쳐 5,400초 이내; 초과 시 중단·invalid |

fixture 준비/worker 준비는 보호 시작 전이다. cleanup은 봉인 뒤 원설정 복원 후다. daemon이 idle/restored일 때는 NTP를 꺼두지 않는다. 정상 종료·소유 프로세스 SIGKILL·짧은 lease 만료·daemon SIGKILL 후 launchd 재시작은 실제 OS에서 검증했다. 실제 reboot cycle은 사용자가 수행하며, graceful shutdown 중 복원된 경우와 새 boot에서 복원된 경우를 구분하여 증거를 남긴다.

장애 때 임의 시계 step, 공유망 차단, VM 재생성, source 변경을 통한 gate 우회를 하지 않는다. 원설정 미복원 시 새 case를 시작하지 않는다. 설치 제거는 `sudo bash scripts/install-fresh-clock-guard.sh uninstall`이며 먼저 원설정 복원을 수행한다. 검증 후 남은 평가가 끝나면 이 설치물의 유지/제거와 원설정 상태를 최종 보고한다.

### 검증 및 재개 규칙

증거 루트: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-v7`.

- 원본 보존 대상 10,234파일의 SHA를 최초 저장했다. 기존 source/raw/verdict는 수정하지 않는다.
- 최종 전체 회귀 191개가 70.994초에 통과했다. H 경계·credit·binding 검사를 포함하며, 최종 소스 SHA와 로그를 `tests-final.json`에 기록했다.
- 표본 외 qualification은 1회, 45분 상한이다. 30분 clock 관찰과 20초 synthetic 읽기 장애를 겹치고, 고유 ConfigMap patch 응답 유실 readback 및 UID 조건부 cleanup을 검증했다. 실제 1,810.126초에 통과했고 보호 관찰은 1,800.005초, 장애 복구는 3회/44.620초다. offset bound 최대 2.5664초(<5초), local wall/monotonic 차이 최대 0.000240초다. 실제 서비스/VM fault는 없다.
- preparation10(유효8/무효2), main26(유효19/무효7), supplement0을 보존한다. 준비8 재실행 없이 기존 calibration 원자료와 preparation 계약을 검증해 재사용한다.
- calibration source 변경 허용은 baseline deadline wrapper, H 누락 guard, cleanup 전 검사 분리, 이 exact binding 분기만 역변환해 기존 SHA와 대조한다. SLO·부하·지표 계산을 바꾸면 거부한다.
- 새 profile: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261028-stability-v7.json`. 새 cohort: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-stability-v7`. 실제 실행 전 새 source/policy/freeze와 승인 증거가 일치해야 한다.
- 남은 순서: `s4-b02-off → s4-b03-off → s4-b03-on → s1-b02-a-supplement01 → s2-b03-p-supplement01 → s3-b02-m3600-supplement01 → s3-b03-m3600-supplement01`. 각각 최대1회다.
- 새 harness/clock invalid가 발생하면 소유 정리와 제한 readback 후 다음 case를 pause한다. 성공할 때까지 재측정하거나 원 invalid를 대체하지 않는다.

### 비용 계산

최신 사용자 표시 잔액은 136,983원이다(사용 298,540/총 435,523). 2026-10-28 20:45:40 KST 기록 이후 경과 비용과 앞으로의 비용만 차감한다. 과거 누적 원장 전체를 다시 차감하지 않는다. 원장은 감사용으로 그대로 유지한다.

기존 계획 rate 약 2,666.67원/시간, 정리 reserve 40,000원, 기타 불확실성 reserve 20,000원을 유지한다. billing cutoff는 미확인이다. admission은 추가로 미반영 12시간을 **확인되지 않은 보수적 가정**으로 잡고, 0/6/12시간 민감도와 손익분기 시간을 함께 기록한다. 유료 전환·현금 초과는 허용하지 않는다. 오래된 146,234원 필드는 역사적 profile 호환용으로 보존하지만 새 admission에서 최신 잔액 대신 사용하지 않는다.

### 실제 재부팅 이후 Astra가 할 일

1. `stability-v7/reboot-test`의 ready/heartbeat와 현재 boot ID, daemon 실행 상태·설치 SHA·NTP 원복 상태를 확인한다. qualification 및 재부팅 증거를 합쳐 `clock-restore-proof.json`을 만든다.
2. 기존 3VM/Cluster/MD/CA UID, worker 상태, 소유 fixture 부재, 실행 PID/lock을 읽기 전용으로 확인한다. 이전 tunnel keeper는 재부팅으로 사라지므로 로컬 tunnel만 재연결한다.
3. 최종 소스 회귀, 원본 SHA 및 sidecar 차이, credit·ETA를 갱신한다. 과거 증거를 소스 현재성 우회로 재기록하지 않는다.
4. 부팅 전 구현·검증 commit의 실제 HEAD/source SHA를 확인하고 그에 대응하는 v4 authorization과 S4 main3 freeze를 만든다. GO 전에는 active pointer나 pause marker를 바꾸지 않는다.
5. GO이면 사용자가 이미 승인한 새 `gpt-6.1-sol` High 로컬 세션을 만들고 정확한 commit, profile, authorization/freeze, 명령, clock 원복 책임, 원본 보존, 비용·ETA를 전달한다. 새 Sol이 단일 실행권을 인수한 뒤 원문을 보존하며 marker를 resolved 전환한다. 기존 PAUSED heartbeat는 재활성화하지 않는다.
6. 새 세션의 실제 착수를 한 번 확인한 뒤 Astra는 공유 소스/driver/인프라 수정을 멈춘다. 기존 두 세션은 보존한다.

---

## 연결 읽기 복원과 추가 A 1회: source 전환

_원래 파일: `docs/graduation/transport-continuation-and-supplement-2026-10-28.md`_


사용자는 연결 오류 읽기 재시도 보완과 무효 `s1-b02-a`의 추가 측정 1회를 승인하면서 진행 중인 실험 중단을 금지했다. `s1-b03-p`는 기존 source에서 자연 종료·정리·독립 판정·봉인을 마쳤으며, 2026-10-28 10:04:56 KST에 canonical driver가 다음 case 전 운영 handoff 지점에서 종료했다. 유효·안전·정리 통과 및 `impact_realized=false`를 모두 보존한다.

경계까지 preparation 10 attempt는 유효 8/무효 2, main 첫 attempt 9건은 유효 8/무효 1이다. 기존 230개 source와 모든 봉인 증거 hash는 동일하며 원판정 승격·원자료 보완·이전 결과 복사는 없다. 새 cohort는 미실행 main 20건을 원순서대로 실행하고, original main29가 모두 봉인된 뒤 `s1-b02-a-supplement01`을 별도 purpose/block에서 정확히 한 번 시도한다. 추가 A는 주분석 첫 29건이나 과거 동시 paired block을 대체하지 않는다.

허용된 kubectl wait/get/logs/rollout status의 일시 연결 오류만 최대 3회 읽기 재시도한다. reconnect·동일 Job UID 전후 확인·backoff·실제 명령이 원래 단일 누적 deadline을 공유한다. UID 변경, 영구 오류, deadline 실패와 관측 공백은 보존하고 mutation/fault/restart/delete를 재생하지 않는다. 기존 watcher와 읽기 복구는 live helper의 정확한 로컬 tunnel ensure 호출에 같은 단일 flock을 사용한다. 기존 calibration 파일은 원본 SHA로 유지한다. calibration/DEV의 앱·부하·분석·기준·계측 source 6개 binding을 모두 그대로 통과한다.

초기 미실행 승인 초안 15479fb/8d71078과 시작 전 검증 실패를 보존했다. 과거 calibration binding을 우회하는 방법 대신 실행 helper에서 reconnect를 조정하도록 확정했다. 전체 source 234개를 새로 동결하며 변경 9파일의 정확한 diff hash, 테스트, 최소 읽기 확인, 기존 frozen manifest와 준비 8건 재판정을 명시적 승인에 결합한다. source exemption은 없다. 프로필은 새 artifact_root 외에는 동일하며 workload·SG·H/SLO·안정창·표본수·분석 기준을 변경하지 않는다.

production Python 3.11.16 fresh 회귀 128건, 컴파일, 시나리오와 live adapter AST, 과거 calibration/DEV source 동일성, diff 검사를 통과했다. localhost 서버 바인딩이 sandbox에서 거부된 검사도 별도 보존한 뒤 같은 source/검사를 허용 환경에서 통과했다. 최소 읽기 확인은 고정 3회 API readyz, cluster/MD UID, Ready worker 1대, 실험 namespace 부재, 기존 GCP3 ID·종류·RUNNING의 7항목을 통과했다.

승인은 `transport-transition-authorization.json`, 원증거 전환 감사는 `transport-transition-final-audit.json`, 최소 확인과 테스트는 `transport-repair-minimal-readback.json`/`transport-repair-tests.json`에 기록한다. `transport-release-active.json`은 새 profile·승인 hash를 고정한다. 기존 단일 heartbeat의 완료 조건은 original main29, 추가 A 실제 1회, 최종 원자료 분석·소유정리·기존 3대 TERMINATED·공유 원장 종료 검증 모두다.

추가 A는 기존 최대 실측 약 46분에 20%를 포함한 약 55분·약 2,450원의 계획 비용을 반영한다. 신규작업 146,234원·정리 reserve 40,000원·기존 불확실성 20,000원 단1회 원칙을 유지한다. 중단 예측은 null, 재개 예측은 완료 작업을 제외하고 보충 1건을 포함한다. 부족 예상은 조기 알린다.

---

## S1 main API 터널 연결 유실과 소유 정리

_원래 파일: `docs/graduation/s1-main-api-tunnel-repair-2026-10-28.md`_


계측 수정 cohort의 `s1-b02-a/attempt-01`은 2026-10-28 07:37:19 KST에 loadgen Job 완료를 읽는 과정에서 실패했다. `kubectl wait`는 로컬 `127.0.0.1:16444` 연결 거부와 앞선 연결 reset을 보고했다. 원래 터널 로그에는 `Failed to send all data from [stdin]`, 원격 연결 종료, `Broken pipe`, SSH 종료 코드 255가 남아 있다. SSH/IAP 연결이 끊긴 직접 증거이며, 연결을 끊은 최초 네트워크 원인까지 확정한 것은 아니다.

이 시도는 이미 등록된 A 조치와 관측을 수행한 뒤였다. 실패한 Job 대기 명령, A 조치, 장애 주입을 다시 실행하지 않았다. 즉시 정리에서도 같은 터널 연결 거부로 Job 제거가 실패했고, runner는 `CLEANUP_FAILED`로 다음 case를 차단했다. 경쟁 VM 제거는 완료됐으나 전체 소유 정리 검증 전이므로 driver는 전체 down을 수행하지 않고 종료했다.

기존 cleanup transport watcher가 07:37:37 KST에 터널을 재연결했다. 이후 운영 점검에서 API `/readyz` 응답이 `ok`이고 원래 Job이 남아 있음을 확인했다. 단일 operator flock 아래 `resume-cleanup --case s1-b02-a`만 실행해 원래 Job의 가용 증거를 보존하고 소유 자원을 정리했다. 07:47:05 KST에 실험 namespace 4개 부재, worker 1대·auto, trial taint 부재, 경쟁 VM·flavor 부재의 8개 정리 검증이 모두 통과했다. 중단 중 완료 예측은 null로 기록했으며 공유 원장의 기존 세션은 계속 비용을 누적했다.

독립 분석은 이 첫 시도를 `trial_valid=false`, `execution=interrupted`, `recovered=null`, `safety=false`, `cleanup=true`로 봉인했다. 누락은 `execution_interrupted`, `request_arrivals_incomplete`, `s1_total_request_indexes`, `scenario_evidence_missing:'service_after'`다. 과학적 안전 확인용 시나리오 checks가 비어 있어 자동 `next_action`은 `safe_shutdown`을 반환한다. 이를 숨기거나 안전 판정을 true로 바꾸지 않았다. 운영 조사에서는 현재 소유 상태에 대한 별도 8개 정리 검증과 고정 3회 API 검사가 모두 통과하고 실제 위험 자원·미해결 소유권이 없음을 확인했다. 실제 안전·소유권 문제일 때 안전 처리하고 관측 유실만으로 무조건 전체 down하지 말라는 승인에 따라, 과학적 무효·false/null 필드를 보존하고 다음 등록 case로 진행한다. 이 판단과 자동 분류의 차이를 `s1-api-tunnel-repair-resolution.json`에 명시했다.

이 main case의 첫 시도는 원래 관측 유실을 포함한 판정을 그대로 주 분석에 남긴다. 두 번째 시도를 만들거나 첫 시도를 소급 통과시키지 않는다. 재개 전 source 230개 동일성, 현재 봉인된 전체 16개 attempt의 증거 해시, 원래 실패 `run.log` 보존을 확인했다. source/profile·판정 기준을 수정하지 않았으므로 새 source freeze가 필요하지 않으며 기존 freeze를 그대로 검증한다. 다음 등록 case는 `s1-b02-p`다. 앱, SLO, H, 안정창, 표본수와 source를 변경하지 않는다.

운영 증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`의 `s1-api-tunnel-*`에 기록한다. 실패 당시 터널 로그는 원래 attempt의 `cleanup-transport/transport-before-repair-1.log`, 실행 오류는 `run.log`, 최초 정리 오류는 `cleanup-error-*.json`에 보존한다. 정리 전 파일 해시는 별도 운영 감사에 기록하고 기존 완료 main 5건의 봉인 증거는 변경하지 않는다.

---

## S2 IAP 읽기 실패와 무효 봉인 복원

_원래 파일: `docs/graduation/s2-iap-judgement-closure-2026-10-28.md`_


`s2-b03-p/attempt-01`은 새 source c7804d9에서 실행했고, 2026-10-28 14:34 KST경 SSH/IAP `4047: Failed to lookup instance`로 업로드 진행률 읽기가 중단됐다. probe stop-file 요청도 같은 오류로 실패했으므로 변경 명령을 반복하지 않았다. 기존 probe는 자연 종료했고 15:02:36 KST부터 canonical 실행자가 정리했다. 15:09:14 KST에 소유 정리 10항목이 모두 참으로 확인됐다. VM 3대의 원 ID·종류는 그대로다. Mac 잠자기가 원인이라는 증거는 없다.

중단 원자료에는 horizon_end가 없으며 기존 분석기는 이 경로에서 start 변수를 참조하다 UnboundLocalError를 냈다. 실행자는 정리 후 종료됐고, events의 VERIFIED 표시는 판정·hash 봉인 완료를 뜻하지 않았고 campaign 디스크 상태는 CLEANUP에 남았다. 운영 감사에서 이를 무효 미봉인으로 분리한다.

분석기 fresh_analysis.py와 앱·부하·fault·정책·H/SLO·안정창·표본수·calibration의 원 SHA를 유지한다. 실행 관리의 순수 wrapper는 기존 분석기를 그대로 호출하고 정상 결과를 그대로 반환한다. 분석기 예외만 명시적 trial_valid=false, fault/impact/recovered/safety=null, execution=judgement_failed로 보존한다. cleanup은 실제 기존 소유 정리 검사로만 확인한다. 성공 승격·추정 metrics·관측 보완·raw 변경은 없다. 보고 재계산도 원자료에 쓰지 않는다. 분석 실패의 과학적 safety=null은 그대로 보존하고, 실제 정리 통과·예산 충족이면 조사 대기한다. 실제 정리 실패나 비용 부족의 안전 gate는 유지한다.

판정 실패 건은 재정리나 fault 재주입 없이 원자료 preclosure hash와 오류 기록, 실제 cleanup을 확인한 뒤 무효 결과로 닫는다. 기존 원자료 파일은 그대로이고 판정 실패 설명·무효 판정·봉인만 추가한다. 이전 봉인 25 attempt는 불변이다. main 첫 시도는 16건 중 유효14/무효2이며, preparation은 10 attempt 유효8/무효2다. 미실행 main13만 원순서로 새 cohort에서 이어가고 승인된 S1 A 보충1은 original main29 뒤에 그대로 분리한다. S2 추가 시도는 하지 않는다.

production Python3.11 회귀 133건 통과. 정상 판정 동일성, 분석 예외의 unknown 결과, cleanup 누락/실패의 비승격, KeyboardInterrupt 전파, 봉인 raw 비수정 검사를 포함한다. 새 freeze는 전체 source234와 이전 source에서 추가된 정확한 3파일 diff를 기록하고, 최초 230 source 대비 전체 diff와 원 preparation 재사용 감사도 함께 고정한다. 새 profile은 artifact_root만 다르다. 완료된 시나리오는 재등록하지 않는다.

실패/중단 중 forecast는 null이다. 같은 공유 비용 원장·신규작업146234원·정리 reserve40000원·불확실성20000원 단1회를 유지하고, 미실행13건+보충1을 포함한 재개 예측을 다시 산출한다. 모든 raw, 이번 분석기 예외, source 경계 및 원무효를 최종 보고에 공개한다.

---

## S3 본시험 M 정리 중 API 터널 유실과 cleanup-only 복구

_원래 파일: `docs/graduation/s3-cleanup-api-tunnel-repair-2026-10-28.md`_


`s3-b02-m3600/attempt-01`은 source `f445b9e`에서 2026-10-28 18:07:56 KST에 원래 관측을 끝냈다. 요청 원자료는 예정 900개/관측 900개, 관측 공백 0초를 남겼다. 이는 무효 시도의 설명 자료이며 유효 주분석으로 승격하는 근거로 사용하지 않는다.

S3 소유 fault·namespace·volume·controller 설정을 정리한 뒤 worker를 2대에서 원래 1대로 되돌리는 운영 과정에서 실패했다. worker는 실제 1대로 수렴했지만, 18:13:40 KST의 후속 probe가 workload API `127.0.0.1:16444` 연결 거부로 실패했다. 같은 시각 SSH/IAP 로그에는 Broken pipe/255가 기록됐다. 기존 cleanup watcher가 18:13:49 KST에 터널 복구를 확인했다. 연결 유실의 최초 네트워크 원인은 확정하지 않는다. fault, worker 축소, probe 실행을 자동 재생하지 않았다. canonical PID97877은 실패 진단을 마치고 18:16:43 KST에 자연 종료했으며 다음 case는 시작하지 않았다.

실제 PID 종료·operator flock 해제 이후 단일 operator 잠금 아래 동일 cluster/MD/CA UID와 worker 1대 안정 상태, CA 0/fixed, `manual from=2 target=1 ca_before=0` journal을 확인했다. S3 원실험 상태는 이미 `cleaned`였고 현재 attempt의 environment run과 fresh_attempt 소유권이 일치했다. 기존 worker recovery는 이미 반영된 worker 축소를 재전송하지 않고 journal만 해소했다. 이어 원래 `resume-cleanup --case s3-b02-m3600`을 정확히 한 번 실행해 auto 모드를 복원하고 소유 정리 10항목을 모두 통과했다. 18:22:10 KST에 cleanup-only가 끝났다. 완료된 S3 정리 명령과 worker scale은 재실행하지 않았다.

정식 원판정은 기존 분석기와 cleanup-only 경로가 생성한 그대로 보존한다: `trial_valid=false`, `fault_realized=true`, `impact_realized=true`, `recovered=null`, `safety=true`, `execution=interrupted`, `cleanup=true`, `missing=[execution_interrupted]`. M의 관측창 내 무복구 원자료는 남지만 유효 비교 표본에는 포함하지 않는다. 추가 S3 retry·보충은 승인되지 않았으므로 새 시도를 만들지 않는다. S1 A/S2 P 보충 각1회만 원래 main29 뒤에 수행한다.

이번 복구는 실행 source/profile/정책/분석기 변경 없이 기존 소유 복구 경로를 사용했다. source234와 과학/calibration source6, 기존30봉인, frozen manifest를 검증한다. `next_action=investigate_before_next_case`에 따라 운영 조사·소유 복구·고정 읽기 검증을 마친 후 기존 freeze의 미실행 case부터 이어간다. source가 동일하므로 새 freeze나 준비8 재주입은 하지 않는다. worker ownership/중단 전환 회귀12건을 통과했다. 원래 오류·재연결·cleanup 실패·cleanup-only 이력과 원자료 hash는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s3-cleanup-transport-repair/`에 보존한다.

같은 공유 원장 세션을 유지하고 신규작업146234원·정리 reserve40000원·불확실성20000원 한도를 변경하지 않는다. 중단 중 forecasts는 null이며 재개 후 완료 case를 제외하고 미실행 main8+S1 A/S2 P 보충2+최종 정리만 포함해 다시 계산한다. 이는 실시간 Billing이 아닌 계획 추정이다.

---

## S3 실제 OS 시계 보정과 명시적 retry

_원래 파일: `docs/graduation/s3-os-clock-step-repair-2026-10-28.md`_


계측 수정 cohort의 S3 P `attempt-01`은 H 내 요청 900건을 모두 수집했고 안전·소유 정리를 통과했지만 `clock_step_between_requests`, `wall_monotonic_duration_disagreement`로 무효 판정됐다. 해당 원판정과 증거 해시를 보존하고 다음 주입을 차단했다. `fresh_failure_policy.next_action`은 `pause_for_measurement_repair`로 분류해 호스트를 일괄 종료하지 않았다.

원자료 index893의 요청은 2026-10-28 01:55:34.546205 KST에 시작해 01:55:37.166613에 완료됐다. wall duration은 2.620408초, monotonic duration은 0.609614초로 차이는 2.010794초였다. 다음 요청의 wall-minus-monotonic offset은 2.010851383초 전진했다.

동일 시각 macOS `timed` 로그는 NTP 응답과 `settimeofday`, `adjust,2.010851145,success,1`을 기록했다. 원자료 변화와 1μs보다 작은 차이로 일치하므로 실제 OS NTP 시계 보정이 직접 원인이다. 이전 조기 요청 대기 오류와 다르며, 도착 대기 코드를 수정한다고 없앨 수 있는 현상이 아니다. OS가 시계를 바로잡은 것이 로그로 확인됐으며, 시스템 시간 설정을 바꾸거나 UTC를 합성하거나 분석 임계값을 완화하지 않았다.

OS 보정 후 읽기 전용 NTP 질의에서 유효 응답 offset -0.001004 ±0.002160초를 확인했다. 다른 endpoint의 timeout은 질의 실패로 보존했다. 고정 120.167초 동안 wall/monotonic을 읽은 결과 offset range는 0.008650초, 인접 최대 변화는 0.000139초였다. 이 점검은 미래 NTP 보정이 없다는 보장이 아니며 원래 시계 유효성 검사는 계속 적용한다.

등록된 `max_attempts=2`와 사용자의 계측 오류 조사·복구·허용 retry 승인에 따라 동일 source/profile의 `attempt-02`를 명시적으로 실행한다. 원 attempt의 실제 장애와 무효 결과는 그대로 보존하고 소급 통과시키지 않는다. 성공할 때까지 반복하는 자동 재생은 없다. 두 번째 attempt도 무효면 추가 자동 retry를 하지 않고 원인과 남은 범위를 다시 조사한다. main의 첫 attempt만 주 분석에 포함하는 원칙은 유지한다.

증거: 새 root의 `s3-clock-step-audit.json`, `s3-system-time-log.txt`, `s3-post-ntp-clock-stability.json`, `s3-readonly-ntp-offset.txt`, `s3-clock-retry-authorization.json`. 실제 단일 실행자는 `resume-s3-clock-retry.py`가 기록한 PID와 flock으로 확인하고, 유효 종료 후 canonical driver를 exec해 나머지 preparation/main을 이어간다. 실험 source 및 profile·H·SLO·안정창·표본 수는 변경하지 않았다.

---

## S4 첫 off 본시험의 주입 전 OS 시각 보정 무효

_원래 파일: `docs/graduation/s4-pre-injection-clock-invalid-2026-10-28.md`_


`s3-b03-p3600`의 앞선 OS NTP 무효 뒤 새 source234 `7b72f67`로 진행한 `s4-b01-off/attempt-01`은 2026-10-28 19:46:04 KST에 고정 첫 60개 기준선 요청을 시작했다. 19:46:59 KST에 macOS `timed`가 `settimeofday`로 +2.042650342초를 보정했다. 원자료 index53→54의 wall-minus-monotonic 변화 +2.042640448초와 약9.9μs 차이로 일치한다. 주입 전 clock gate가 `baseline_clock_disagreement`, `baseline_unhealthy`를 거부했다. 기준선 세 구간은 각20개이며 마지막 구간 bad6/p95=2322.22985ms, 앞 두 구간 bad0/p95=303.34425/319.04035ms였다. 60개 응답 자체는 모두 ok/correct였다. 이는 시각 영향을 설명하는 원자료이며 정상 기준선이나 유효 결과로 재분류하지 않는다.

장애 주입·MHC fault 변경 전에 중단됐다. 자연 cleanup이 trial namespace 부재·worker1/auto·trial taint 부재의 6항목을 모두 확인했고 19:51:57 KST에 판정·봉인이 끝났다. canonical PID21223과 CLI21237은 자연 종료했으며 단일 operator flock 해제를 실제 확인했다. 원판정은 `trial_valid=false`, `fault_realized=false`, `impact_realized=false`, `recovered=null`, `safety=false`, `execution=interrupted`, `cleanup=true`와 원 missing 목록 그대로다. 자동 분류 `safe_shutdown`은 과학 안전성 실패를 포함하지만, 실제 소유 환경 정리·예산 통과에 근거해 운영 조사 후 미실행 다음 case로 진행하는 판단과 구분한다. 원판정·원자료·표본수를 변경하지 않는다. S4 off 추가 retry 또는 보충은 승인되지 않았으며 생성하지 않는다.

실행 종료 후 실제 같은 cluster/MD UID·worker1/노드 Ready·네 trial namespace 부재·기존3VM ID/type/RUNNING·읽기 IAP의 고정8항목을 독립 재확인했다. 실제 자연 cleanup probe의 `read-guard.json`은 enabled=true, target1, worker FD 상속 및 같은 cluster/MD/CA를 기록했고 mutation 반복·ensure는 false였다. 정상 읽기만 진행돼 `read-attempts.jsonl`은 생성되지 않았다. 이를 실패 기록 누락으로 해석하지 않는다. 완료 cleanup·scale·probe를 재실행하지 않았다. 기존33봉인과 이번1건, 전체34봉인/frozen/raw 및 source234 해시가 그대로다.

추가 읽기 NTP 질의는 두 exchange timeout을 보존하고 최종 +0.012106±0.001949초를 반환했다. 실패 exchange의 offset 필드는 측정값으로 사용하지 않는다. OS 시각 설정·NTP 서비스·UTC 생성·분석기·clock 기준선을 수정하지 않는다. 고정120.463초 wall/monotonic 안정성은 range0.000938892초·인접최대0.000009060초로 한 번 통과했으며 향후 OS 보정 부재를 보장하지 않는다. 이번도 원 clock gate가 무효를 올바르게 차단한 경우라 실행 source 수정·새 freeze·준비8 재주입·회귀 재실행은 하지 않는다. 원 source234에 봉인된188회귀 증거를 유지한다. 조사 중 환경변수 누락으로 첫 읽기 봉인 검증이 중단된 기록도 남기며 고정 환경 경로를 명시해 같은 읽기 검증을 완료했다. 실제 실험 시도는 추가되지 않았다.

같은 profile/승인/freeze와 열린 공유 원장을 유지해 `s4-b01-on`부터 남은 main5만 원순서로 재개한다. 이후 승인된 S1 A→S2 P→S3 b02 M→S3 b03 M 보충 각1회, 총4회를 독립 block에서 측정한다. 첫 main29 및 무효들은 그대로이고 보충을 원 paired block에 대입하지 않는다. 중단 중 forecasts=null이며, 완료 case 제외+남은 main5+보충4+최종 정리25분 단1회를 포함한 19:54 KST 계획은 10월29일03:32/약144075원, 신규146234원 대비 약2159원 여유다. 재개 실측 시각으로 다시 갱신한다. 실시간 Billing이 아니며 정리 reserve40000·불확실성20000·무료체험 현금초과 금지는 유지한다.

조사와 원증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s4-baseline-clock-repair/`에 보존한다. 원무효 총8건(prep2+main6), 과거V7/HOLD 별도와 모든 source 경계·비동시 보충 한계를 최종 보고한다. main29+보충4 실제 측정·최종 분석/보고·소유정리·기존3VM TERMINATED·공유 원장 종료 전 heartbeat를 삭제하지 않는다.

---

## SSH/IAP 명시 읽기 재시도와 S2 P 보충 1회

_원래 파일: `docs/graduation/ssh-read-and-s2-supplement-2026-10-28.md`_


사용자는 진행 중인 실험을 중단하지 않고 SSH/IAP 읽기 오류 복구를 보완하고 무효 S2 P를 별도로 1회 더 측정하도록 명시 승인했다. 기존 S1 A 보충 1회도 유지한다. 본시험 original main29의 순서와 첫 시도 주분석은 유지하며, 이후 S1 A와 S2 P를 각각 독립 supplemental block에서 정확히 한 번 측정한다. 두 보충은 원무효를 대체하거나 이전 동시 paired block으로 합치지 않는다.

지시 수신 때 s3-b01-p3600은 이미 정리·판정·봉인됐고 s3-b02-p3600이 시작됐다. 기존 source694bd67/PID64387을 바꾸거나 중단하지 않고, 현재 case의 자연 종료·소유 정리·독립 판정·봉인 다음 기존 driver의 next-case gate에서 handoff하도록 REPAIR-REQUIRED.json을 설정했다. 수정은 별도 staging에서 준비했다. 실제 적용은 PID 종료와 단일 operator flock 해제 뒤에만 한다.

재시도 경계는 S2의 고정 curl /progress, qdisc show, 호스트 통계, receiver clock, 지정 port/QoS rule show 및 extension list, 현재 run_id의 지정 원자료 파일/준비 파일 확인 호출이다. S3의 최종 source hypervisor domstate도 기존 source instance_name·host에 묶인 명시 읽기만 허용한다. 임의 remote shell이나 원자료 경로를 허용하지 않는다. 기존 remote(), fault, workload/probe 실행, QoS 변경, patch/restart/delete를 통째로 재실행하지 않는다. 진행 중인 원격 probe는 읽기 복구 중 계속 동작한다. probe stop-file 응답 유실은 touch를 다시 보내지 않고 동일 파일의 존재부터 읽어 확인한다. 적용 여부가 확인되지 않으면 원오류를 보존한다.

각 명시 읽기는 원 timeout 안 최대3회, backoff1/2초다. identity 조회·실제 읽기·backoff가 같은 누적 deadline을 공유한다. raw 다운로드의 외부 collection loop는 1회만 두고 내부 SSH 읽기 최대3회를 사용하여 3x3 재시도를 막는다. 기존 kubectl 재시도와 겹치는 identity kubectl은 재시도 없는 직접 읽기이며 동일 remaining 시간에 제한한다. 기존 단계 전체 deadline도 유지한다.

IAP4047 Failed to lookup instance는 단독으로 일시 오류라고 판단하지 않는다. 재시도 전과 성공 후 GCP describe로 기존 프로젝트·zone·VM name·ID·RUNNING을 확인하고, 현재 environment run과 실험 namespace UID/소유 label을 직접 읽어 확인한다. 권한·설정·인증서·NotFound 등 영구 오류나 identity 불일치는 즉시 반환한다. 반복 실패·deadline 초과는 TimeoutError로 남기며 오류·시각·실제 duration·관측 공백을 기록한다. 성공한 재조회는 그 시점의 실제 값이며 빈 구간을 정상값으로 보간하지 않는다.

분석기·calibration/DEV 계측 source6개·앱·부하·fault·정책·SLO/H·안정창·표본수는 원 SHA/계약 그대로다. AST 검사는 명시 읽기 adapter와 bounded collection 선택만 제거하면 원 시나리오/정책 본문이 동일함을 검증한다. source exemption, 옛 manifest/hash 변경, 완료 측정 복사, 준비8 기계적 재실행은 없다. 준비8의 원판정/원자료/source·계약 동일성과 AST·회귀로 재사용 근거를 남긴다. 모든 새 source와 정확한 diff·영향 검토·검증 증거를 새 freeze에 결합한다.

s1-b02-a 및 s2-b03-p 원무효와 cleanup 판정/원자료는 불변이다. S2 원무효의 분석기 UnboundLocalError도 별도 행정 무효 봉인 그대로 유지한다. 보충 id는 s1-b02-a-supplement01, s2-b03-p-supplement01이며 purpose=supplemental, 독립 block, 각 max_attempts=1이다. 본시험29 봉인 전 보충 admission을 거부하고 S1 보충 봉인 전 S2 보충을 거부한다. 두 보충이 실제 끝나기 전 driver/heartbeat 완료·down·삭제를 금지한다.

신규작업146234원·정리reserve40000원·불확실성20000원은 같은 공유원장에 단1회 유지하며 실시간 Billing으로 표현하지 않는다. 현재 case와 staging을 병행하고 전환10분·약444원, 추가 S2 P는 유효 완료 실측 최대에20%를 더한 약46분·약2051원을 보수적으로 잡았다. 기존 S1 보충·미완 main·정리를 포함한 잠정 전체 ETA는 10월29일02:42KST·약141851원이며, 실제 경계 종료 뒤 완료 작업을 제외하여 다시 갱신한다. 중단 중 확정 forecast는 null이다. 시간 목표는 advisory이고 실제 비용 부족은 조기 알린다.

최종 보고는 모든 raw/invalid/분석기 예외·source 경계와 두 보충의 비동시성 한계를 공개한다. paired 원자료 차이·중앙값·범위, latency/upload tradeoff, S2 API 영향과 정상유지/복구의 구분, S3 timer/H, S4 기존 MHC 역할을 포함한다. final main29+보충2 실제 측정·분석/보고·소유정리·기존3VM TERMINATED·공유원장 종료를 모두 확인한 뒤 단일 heartbeat를 삭제한다.

실제 handoff는 17:36:02 KST에 끝났다. s3-b02-p3600은 원 source에서 trial_valid/fault/impact/recovered/safety/cleanup 모두 참, missing=[]로 봉인됐고 PID64387과 단일 flock이 해제됐다. 경계 원자료는 preparation10(유효8/무효2)+main20(유효18/무효2)=총30봉인이며 보충0이다. 8개 추가 source 파일을 적용하기 전에 모든 봉인과 frozen manifest/hash를 별도 감사로 보존했다. 새 cohort에는 미실행 main9만 남고, 본시험 뒤 S1 A 및 S2 P 보충 각1회가 뒤따른다.

---

## S3 소유 binding 읽기와 controller 변경 전 정리 검증

_원래 파일: `docs/graduation/s3-binding-read-and-precontroller-closure-2026-10-28.md`_


`s3-b03-m3600/attempt-01`은 source f445b9e에서 준비 worker2/probe를 마친 뒤, 2026-10-28 18:32:47 KST에 control-plane Node의 OpenStack port show 읽기가 SSH/IAP4047 Failed to lookup instance로 실패했다. controller 정책 설정·DB 생성·fault 주입 전이었다. 실제 기존3VM은 동일 프로젝트·zone·ID로 RUNNING이었다. 최초 네트워크 원인은 확정하지 않는다. source/profile을 실행 중 바꾸거나 binding/fault/시나리오 전체를 재실행하지 않았다.

원래 정리는 namespace 부재·worker1/auto 복원을 완료했지만, 아직 controller 변경 의도에 도달하지 않아 생성되지 않은 controller-manager-before.yaml을 공통 정리 검증기가 요구해 18:37:20 KST에 차단됐다. PID6718 자연 종료와 단일 operator flock 해제 후 원 attempt 전체를 별도 보존했다. 동일 Node/Machine/Nova identity의 실제 controller manifest를 읽어 직전 복원 원자료 SHA와 일치함을 확인했다. 이번 record에는 controller_original/configured SHA·control_plane·source·volume·fault 의도가 없고 phase=cleaned였다. 독립 소유 정리10·고정 최소읽기8을 확인한 뒤 정리 명령이나 fault를 다시 보내지 않고 행정 봉인했다. 기존31봉인과 기존 attempt 파일은 events append 외 모두 동일하다. 존재하지 않았던 controller 복원 파일이나 H/요청 관측을 소급 생성하지 않았다.

원 분석기는 변경하지 않았다. 원판정은 valid=false, fault/impact=false, recovered=null, safety=false, execution=interrupted, cleanup=true다. baseline_clock_origin_invalid, baseline_first_arrivals_incomplete_or_duplicate, baseline_unhealthy, execution_interrupted, horizon_missing, phase_sequence_incomplete, scenario_evidence_missing:'statefulset', semantic_event_missing_or_duplicate를 보존한다. 과학적 safety=false와 독립적으로 확인한 실제 환경 안전/소유 정리를 구분한다. 자동 next_action의 safe_shutdown 분류를 숨기지 않으며, 관측 유실만으로 무조건 down하지 말라는 기존 승인과 독립 정리·비용 검증에 따라 운영 조사 후 미실행 case로 진행한다. 추가 S3 retry/보충은 승인되지 않았으므로 만들지 않는다.

별도 staging에서 보완한 S3 binding adapter는 고정 Node/Machine에 대한 server show, port list --server, 그 결과의 지정 port show만 읽는다. 시나리오·임의 remote shell·mutation 전체를 재시도하지 않는다. 각 실패한 명령만 최대3회, backoff1/2초로 재조회하고, mapping·명령·GCP/namespace/Node/Machine identity·backoff 전체가 보수적인 동일60초 누적 상한을 공유한다. 이는 기존 각 명령60초보다 넓히지 않는 준비 단계 제한이며 H/SLO/관측·fault·정책을 바꾸지 않는다. 재시도 전/후 동일 기존 VM RUNNING/프로젝트/zone/ID·environment/fresh_attempt·namespace UID/소유 label·Node/Machine UID/providerID를 확인한다. 영구 권한/identity 오류는 즉시 반환하고, deadline·실패·관측 공백을 보존한다. 정상 binding 값은 원 구현과 동일함을 회귀로 검증했다.

정리 검증은 durable controller_original SHA가 있으면 기존 원파일/복원파일의 일치에 더해 원 SHA를 확인한다. 의도·파일이 없는 실패는 controller_configuration_not_started로 구분한다. 의도 뒤 복원 파일 누락, SHA 불일치, orphan configured SHA/파일은 통과시키지 않는다. controller-policy-restored를 무조건 true로 바꾸지 않는다. AST 검증은 정확한 binding 읽기 adapter와 이 정리 검증 분기 외 시나리오/공통 helper 변경을 거부한다.

이번 추가 source 변경은 6파일이며 전체 source234를 새 freeze에 묶고 최초230 대비 정확한 전체12파일 diff·영향검토를 보존한다. 과학/calibration source6, 앱/부하/fault/정책/SLO/H/안정창/표본수/분석기는 원 SHA/계약 그대로다. 기존 preparation8은 원판정 재계산·계약·AST·회귀·raw hash로 재사용하고 재주입하지 않는다. 기존 frozen/source/raw를 고치거나 source exemption을 쓰지 않는다. 경계는 총32봉인=prep10(유효8/무효2)+original main22(유효18/무효4), 보충0이다. 새 cohort에는 미실행 main7만 원순서로 넣고, 그 뒤 S1 A/S2 P 보충 각1회를 별도 독립 block에서 측정한다.

공유 원장 세션은 유지하고 ensure·완료된 repair wrapper는 다시 실행하지 않는다. 신규146234원·정리reserve40000원·불확실성20000원은 단1회다. 수정 중 forecasts=null이며 실제 전환 후 완료 작업을 제외한 main7+보충2+정리로 갱신한다. 모든 원무효6건과 source 경계·보충의 비동시성·이번 fault 미주입을 최종 보고에 공개한다. 근거는 artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s3-binding-read-repair/에 둔다.

---

## 보충4회 승인과 worker 축소 후 probe 읽기 보완

_원래 파일: `docs/graduation/four-supplement-and-owned-probe-reads-2026-10-28.md`_


사용자는 무효 s3-b02-m3600 및 s3-b03-m3600도 각각 별도 supplemental 정확히1회 측정하도록 추가 승인했다. 기존 S1 A/S2 P 각1회와 합쳐 main29 뒤 순서대로 보충 총4회다. 원래 첫29 주분석과 모든 원무효·raw·판정은 불변이며, 원 block 동시 paired 결과로 대체하거나 성공까지 반복하지 않는다. 각 보충은 독립 block/최대1회이며 네 건 모두 실제 종료하기 전에 완료/down/heartbeat 삭제하지 않는다. 실제 안전·소유권·비용 한도는 계속 지킨다.

승인 수신 당시 source4708e66/PID11319의 s3-b03-p3600이 실행 중이었다. source를 바꾸거나 중단하지 않고 현재 case의 자연 종료·cleanup·판정·봉인 다음 경계에서 멈추는 운영 marker를 예약했다. 추가 작업은 별도 staging에서 준비했다. 이 marker는 새 승인된 handoff이며 완료된 wrapper 재실행을 의미하지 않는다.

원인을 구분한다. b03 M의 고정 binding SSH/IAP 읽기 및 controller 변경 전 정리 검증은4708에서 보완됐다. b02 M은900/900 관측 후 worker 축소 후속 probe의 workload API nodes 읽기 연결 실패를 cleanup-only로 복구한 것이며 당시 재발 방지 source 수정은 없었다. 이번 보완은 이 후속 읽기 경로에 해당한다. 최초 연결 유실의 네트워크 원인은 여전히 미확정이다.

소유 worker 수동 scale의 기존 journal과 상속된 실제 worker lock FD/inode가 있는 probe만 읽기 guard를 사용한다. 고정 workload nodes/readyz, 생성된 동일 probe Pod UID의 상태/events/logs/delete-wait만 원래30초 읽기 상한 및 기존360초 probe 단계 안 최대3회/backoff1,2초로 재조회한다. 기존 watcher/공유 reconnect lock이 연결을 복원하기를 수동으로 기다리며 ensure나 worker scale을 다시 보내지 않는다. 재시도 전/후 journal·kubeconfig SHA·cluster/MD/CA UID·실제 target replica 안정 수렴·CA0을 확인하고, Pod/run/Node UID를 확인한다. 권한/identity 오류와 deadline 초과는 즉시 보존한다. delete-wait 응답 유실은 실제 동일 Pod 이름의 부재부터 읽어 확인하며 delete를 반복하지 않는다. management-plane 읽기는 기존 단일 호출을 유지한다. probe 생성·부하·scale·patch·delete 명령과 실험 정책·앱·SLO/H는 바꾸지 않는다. 정상 읽기 값은 그대로 반환하고 오류·시각·관측 공백을 probe evidence에 남긴다.

보충 등록은 S3 동일 scenario의 두 origin을 명시적으로 구별하고 각각 다른 freeze 경로/독립 block을 사용한다. main29 전 보충 admission을 거부하고, 앞 보충이 봉인되기 전에 뒤 보충을 허용하지 않는다. 네 번째 실제 시도 전 down하지 않으며 supplemental max_attempts=1을 유지한다. 계획 비용이 신규작업 한도를 넘으면 pending 범위를 그대로 두고 fault admission 전에 조사를 위해 멈춘다. 과학적 safety=false이더라도 실제 소유 정리가 검증되고 비용이 충분하면 조사 대기하며 그 값만으로 전체 down하지 않는다. 실제 비용/정리 안전 gate와 원 next_action 분류는 유지한다.

현재 P는 정리10을 모두 통과했으나 clock_step_between_requests로 무효 봉인되고19:23:31KST에 PID11319가 자연 종료했다. raw index914→915의 wall-minus-monotonic 변화는+3.980372초였고,19:15:01KST macOS timed의 settimeofday adjust+3.980385065초와 약13μs 차이로 일치한다. 관측 전18:58:59KST에는-3.951622128초 보정도 있었다. 원판정 valid=false/fault·impact=true/recovered=null/safety=true/cleanup=true/missing=[clock_step_between_requests]를 보존하며 P 재측정은 추가 승인되지 않았다. 시스템 시각·설정·분석 임계값·UTC 생성은 바꾸지 않았다. 읽기 전용 NTP는+0.047248±0.002284초,120.870초 wall/monotonic 점검의 offset range0.000934초·인접최대0.000008822초였다. 이후 보정이 없다는 보장은 아니며 원 clock 유효성 gate를 계속 적용한다.

경계의 원 봉인은 총33=prep10(유효8/무효2)+main23(유효18/무효5), 보충0이다. 원무효 총7건 및 과거V7의 별도 무효/HOLD를 모두 공개한다. 현재 원자료/frozen hash를 보존한 뒤 수정6파일, 전체source234와 최초230 대비 정확14파일 diff·영향·AST를 새 freeze에 묶는다. 과학/calibration source6·분석기·앱·fault·정책·부하·SLO/H·안정창·표본수는 원 SHA/계약 그대로다. 원 준비8은 원판정 재계산·계약·AST·회귀·hash로 재사용하며 재주입하지 않는다. source exemption이나 옛 manifest 변경은 없다. 미실행 main6만 원순서로 남고 이후 보충4회를 실행한다.

추가 S3 각 약48분(실측 최대와 정리복구 포함 duration x1.2), 전환15분과 기존 최종정리25분을 단1회 포함한 잠정 계획은10월29일04:09:37KST·약145748원이었다. 신규146234원 대비 여유약486원으로 좁아 조기 알렸다. 실제 경계·전환 뒤 완료작업을 제외해 다시 갱신한다. 이는 실시간Billing이 아닌 계획 추정이다. 같은 열린 공유원장을 유지하고 정리reserve40000원·불확실성20000원은 단1회이며 무료체험 현금초과 금지를 지킨다. 초과 예상 시 부족액과 선택지를 보고하고 범위를 임의 삭제하지 않는다. 중단 중 forecasts=null이다.

검증은 staging/실제 fresh 및 worker/probe 회귀188건, 최소읽기8, clock 안정성, source234/기존33봉인/원 calibration binding·시나리오/helper/probe AST에 결합한다. 근거는 artifacts/fresh-evaluation-measurement-repaired-2026-10-27/four-supplement-cleanup-read-repair/에 둔다. 모든 원무효·source 경계·후속 보충의 비동시성·clock 한계를 최종 분석에 공개한다.

---

## 장애 주입 전 DNS 통신 장애 복구

_원래 파일: `docs/graduation/pre-injection-dns-repair-2026-10-28.md`_


계측 수정 cohort의 S2 P `attempt-01`은 2026-10-28 00:02:47 KST에 공통 worker 준비에서 실패했다. 새 worker의 DNS active probe가 실패했고, 원상 복구를 위한 worker 1대 정리 후에도 남은 worker의 DNS probe가 실패했다. S2 adapter와 장애 주입은 시작하지 않았다. 해당 attempt와 cleanup 실패 증거를 보존하고 후속 주입을 차단했다. 이 실패를 시간 계측 오류나 실험 조건의 미복구와 혼동하지 않는다.

동일 DNS 질의는 control-plane에서 성공했지만 worker에서는 kube-dns 서비스 IP 및 두 CoreDNS Pod IP 모두 시간 초과됐다. Calico BGP peering, PodCIDR route, IPIP 터널은 정상 상태였다. Nova/Neutron에서 현재 worker `e44c1008-6493-4487-a680-4a102e74fa61`, IP `10.6.0.235`, 포트 `999bfbda-ae18-4b3e-8ac4-8a6ff5afb109`의 소유·배치·보안그룹을 확인했다.

control-plane이 있는 `osk8s-compute01`의 Neutron hybrid 방화벽에서 IPIP 허용 규칙은 worker 보안그룹의 ipset `NIPv4803bc172-4953-464f-bd7f-`를 참조했으나 실제 멤버 수가 0이었다. 등록된 worker 포트가 있는데도 동적 주소 집합이 비어 있었던 것이 확인된 직접 차단 원인이다. 주소 집합이 비게 된 최초 이벤트까지는 확정하지 않았다.

2026-10-28 00:13:34 KST에 기존 `neutron_openvswitch_agent` 하나를 재시작하여 등록 상태를 재동기화했다. 기존 SG 규칙·허용 범위·Calico 설정·workload·실험 source/profile은 변경하지 않았다. 이후 ipset에 `10.6.0.235`가 복원됐고, 같은 worker의 동일한 DNS 서비스 IP 및 두 직접 Pod IP 질의가 모두 성공했다. 진단 Pod는 제한시간·명시 소유 라벨로 생성했고 UID를 확인해 증거 보존 후 제거한다.

증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`의 `dns-*`, `repair-dns-*-final.*`에 보존한다. 원래 실패 attempt는 소유 정리만 재개해 무효 결과로 봉인하며 소급 통과시키지 않는다. 이후 허용된 최대 2 attempt와 첫 attempt 보존 정책에 따라 장애 주입 전 실패에 대한 재시도를 명시적으로 기록한다. main은 여전히 각 case의 첫 attempt만 주 분석에 포함한다. 새 준비 cohort를 성공할 때까지 반복하거나 기존 4건을 다른 source의 유효성 증거로 복사하지 않는다.

---

## 안정화 재개 후 첫 case 준비 실패와 소유 정리

_원래 파일: `docs/graduation/evaluation-stability-execution-pause-2026-10-29.md`_


2026-10-29 KST. 결과는 **일시중지**다. 전체 평가·최종 보고는 완료되지 않았다. 기존 06:47 완료 예상은 철회한다.

### 실제 수행과 판정

`3375f9069022055ceca3b09e789729704be956ec`의 source249와 stability-v7 authorization/profile/freeze를 검증하고 00:20에 단일 driver를 시작했다. 기존 pause 세 파일과 active pointer 원문·SHA는 [인수 기록](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/takeover.json)에 보존했다. 준비실험은 재실행하지 않았다.

첫 `s4-b02-off`는 worker 준비 단계가 00:50:54에 1,800초 상한으로 종료됐다. 장애 주입, baseline 부하 및 H 관측은 시작하지 않았다. 최초 정리는 lock 경합으로 00:51:06에 실패했다. 이를 새 하네스 실패로 처리하고 다음 case를 중지했다. 시각 보호 lease를 arm하는 단계에 도달하지 않았다.

01:06~01:07에 저장된 original-worker와 worker-operation journal, Cluster/MD/CA UID를 대조한 뒤 소유 정리만 수행했다. worker 2/fixed를 원래 1/auto로 복원했고 mutation을 무조건 재전송하지 않았다. 이후 동결된 `resume-cleanup --case s4-b02-off`로 정리를 검증하고 attempt를 닫았다. strict 판정은 **invalid**, cleanup은 **true**다. 무효를 성공으로 변경하거나 같은 case를 재측정하지 않았다.

| 구분 | 닫힌 attempt | 유효 | 무효 | 미실행 |
|---|---:|---:|---:|---:|
| preparation | 10 | 8 | 2 | 0 |
| 원래 main first-attempt | 27 / 계획 29 | 19 | 8 | 2 |
| 별도 보충 | 0 / 승인 4 | 0 | 0 | 4 |

남은 순서는 `s4-b03-off → s4-b03-on → s1-b02-a-supplement01 → s2-b03-p-supplement01 → s3-b02-m3600-supplement01 → s3-b03-m3600-supplement01`다. 현재 모두 pause 상태다. `s4-b02-off`의 추가 attempt는 승인 범위에 없다.

### 관측한 원인과 한계

준비 단계의 `openstack-workload-inventory` 읽기는 16개 호출 묶음, 총 48개 시도가 모두 timeout이었다. 20초 명령 상한과 90초 작업 예산을 소진했고 성공한 inventory capture는 0개다. `workload_state.snapshot()`은 이 예외를 `nova` unavailable로 수집하여 readiness loop를 계속했다. 결과적으로 과학적 측정 전에 준비 단계 전체 예산을 소진했다.

`scripts/workload-inventory.sh`는 한 SSH 호출 안에서 여러 OpenStack CLI 조회를 순차 실행한다. 이 복합 호출 전체가 새 외부 20초 상한을 받는다. 따라서 **등록 단위와 timeout 적용 단위가 실제 작업의 크기에 맞는지 검증이 부족했다.** 개별 API 지연과 네트워크 최초 원인은 이번 기록만으로 확정하지 않는다. 복합 조회 구조를 이유로 timeout을 임의 확장하거나 측정 조건을 바꾸지 않았다.

최초 cleanup은 `BlockingIOError: Resource temporarily unavailable`로 실패했다. 이후 평가 자식 프로세스가 없고 관련 lock이 가용함을 확인한 뒤 소유 정리를 완료했다. 종료 시점 자식 정리와 lock 해제 경계도 회귀 검토 대상이다.

기존 qualification은 ConfigMap fixture와 synthetic read 장애·시각 복원 검증을 통과했지만, 이 복합 inventory를 사용하는 실제 worker 준비 lifecycle의 성공을 입증하지 못했다. H 전용 retry 분기는 오프라인 검증이며 live qualification에서 실행했다고 주장하지 않는다.

분석기에 표시되는 baseline/clock-origin/H 누락 사유는 **해당 측정자료가 생성되지 않았기 때문**이다. 이번 실패에서 실제 clock step을 관측했다는 뜻이 아니다.

### 자료 보존과 분석

기존 10,234개 파일의 SHA 불변을 다시 검증했다. 기존 main26의 유효19·무효7은 유지된다. S2-b03-P의 분석기 예외가 구체적인 H 누락 사유로 바뀌는 기존 sidecar 차이를 유지한다.

[별도 집계](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/interim-analysis/report.md)는 원래 strict first-attempt 판정과 보충 표를 구분한다. [전건 사후감사](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/interim-analysis/posthoc-measurement-audit.json)는 원자료·identity·hash와 동일한 규칙을 적용한다. 모든 execution error가 독립적으로 관측된 H 종료 뒤에 있고 다른 원자료·baseline·시각·시나리오 결측이 없는 경우만 측정완전성을 별도로 표시한다. 과거 측정봉인을 만들어 넣거나 strict invalid를 승격하지 않는다. S3-b02-M3600과 S4-b02-on은 이 사후 완전성 조건을 충족하지만 주분석에서는 계속 무효다. 새 s4-b02-off는 H 미실행으로 이 조건도 충족하지 않는다.

조건별 표본 수와 완전한 paired block이 부족하고 transport·clock 운영 버전이 혼합되어 있다. 유효 표본만의 성능을 전체 계획 29건의 무조건적 효과로 해석하지 않는다. 이번 중간 집계는 최종 효과 보고서가 아니다.

### 종료 상태와 재개 전 검토

[정리 readback](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/readiness-failure/closure-readback.json)은 동일 3VM RUNNING·관리 UID 동일·worker 1/auto·fixture namespace 부재·trial taint 부재·평가 프로세스 부재·lock 가용·source249 불변을 확인했다. 중간 pause 지시에 따라 VM을 정지하거나 공유원장을 종료하지 않았다.

clock guard 서비스는 설치된 상태로 유지되며 daemon 상태는 `restored`, 원설정은 On / time.asia.apple.com이다. 실패한 attempt는 clock lease를 arm하지 않았다. 이번 closure에서 직접 `systemsetup` readback을 시도했으나 `sudo -n`이 비밀번호를 요구해 현재 설정을 독립적으로 다시 읽지는 못했다. 기존 실제 재부팅 후 직접 확인한 복원 증거와 변경되지 않은 daemon 상태를 구분한다.

비용은 최신 표시 잔액 136,983원을 기준으로 보고 이후 경과·남은 범위 추정, cleanup 40,000원·기타 20,000원·미반영 12시간이라는 보수적 미확인 가정을 사용한다. 과거 원장을 새 잔액에서 다시 차감하지 않는다. [closure 비용 checkpoint](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/readiness-failure/closure.json)의 여유는 청구서 잔액이 아니며, pause 중에도 3VM 유지 비용이 계속 발생한다. 현금초과·유료전환은 승인되지 않았다.

재개 전에는 복합 inventory의 명령·작업 예산 단위와 종료/lock 해제 경계를 검토하고, 수정한다면 새 source·회귀·실제 준비 경로 검증·freeze와 이번 실패 후의 재개 조건을 다시 확정해야 한다. 현재 소스나 deadline을 고치거나 driver를 다시 시작하지 않았다. 이 pause는 새 하네스 무효가 생기면 정리 후 다음 case를 멈추라는 사용자 지시에 따른다.

---

## Inventory 준비 실패 수정 및 재개 검증

_원래 파일: `docs/graduation/evaluation-inventory-repair-2026-10-29.md`_


2026-10-29 KST. 이 문서는 `3375f90` 이후의 운영 수정과 별도 재개 cohort를 설명한다. 기존 본 실험 first-attempt와 strict 무효 판정을 보존한다.

### 원인과 수정

`workload_state.snapshot()`의 inventory는 7개 종류의 목록, port별 상세, quota/limits를 한 SSH 세션에서 순차 수집한다. 공통 read wrapper가 이 묶음 전체에 개별 명령 상한 20초를 적용한 것이 준비 실패 원인이었다. 실패 당시 16개 호출 묶음의 48개 시도가 모두 timeout이었다. 수정 전 원본을 읽기 전용으로 단독 실행했을 때 45.86999초에 정상 종료됐다.

새 compound 경로는 수집 전체에 기존 작업 예산 90초를 적용하고, 원격 OpenStack CLI 각각에는 20초를 적용한다. 재시도·identity·backoff도 같은 90초에 포함한다. 각 child를 재시도하는 중첩 retry는 없으며, 완성된 JSON만 반환한다. 개별 조회·identity는 기존 20초 제한을 유지하고 baseline/H 및 전체 준비 단계의 원래 제한을 늘리지 않는다. 원격 수집 자체에도 deadline을 두어 연결이 끊겨도 무기한 남지 않는다.

`LiveBackend.cleanup`은 interrupted worker supervisor가 ownership lock을 해제할 때까지 최대 30초 기다린다. 이 시간은 기존 cleanup phase 예산 안에 포함된다. 여전히 다른 owner가 있으면 mutation을 실행하지 않고 실패한다. lock을 강제로 해제하거나 다른 owner의 작업을 취소하지 않는다.

### 검증과 증거 범위

[inventory-repair-v8](../../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/inventory-repair-v8/)에 테스트, 실제 준비 경로, 원본 보존, 비용, transition 검토를 보존한다. 테스트는 46초 정상 복합 조회, remote child별 20초 제한, shared retry/phase 예산, 실제 별도 프로세스 lock 해제 대기/거부, 재개 범위 및 과학적 소스 변경 거부를 포함한다. 전체 `test_fresh*.py` 197개가 통과했다. 첫 sandbox 실행에서 HTTP 테스트의 localhost bind가 거부된 기록은 별도 보존하고, 동일 테스트를 localhost bind가 가능한 환경에서 통과시켰다.

실제 준비 검증은 새 과학적 attempt를 생성하지 않고 동일 함수 `Campaign.verify_ready_environment`와 `Campaign.prepare_workers`로 auto/1 → fixed/2를 준비한 후 `LiveBackend.cleanup`으로 auto/1을 복원한다. 실제 서비스/VM fault, baseline 부하, H 측정은 실행하지 않는다. 그 상태에서 변경 없는 clock guard의 arm/release도 확인한다. 최종 재검증은 source253에서 준비 434.94초, 전체 691.75초에 통과했다. inventory 완전 수집 5회, worker 2대 준비·배치, 정상 clock release, cleanup, worker auto/1, 동일 identity를 확인했다. scale-down 도중 삭제된 port에 대한 한 snapshot은 NotFound로 거부됐고, 원래 readiness loop가 다음 완전한 snapshot으로 수렴했다. 부분 관측을 채우거나 deadline을 늘리지 않았다. 최종 증거와 소스 SHA는 `readiness.json`, `go-review.json`을 따른다.

첫 실제 준비 검증은 worker 준비를 통과했지만 operator 검증 스크립트가 clock-smoke 증거 폴더를 만들지 않아 arm 기록 저장에 실패했다. 이 스크립트 오류로 lease가 만료되어 owner가 정리 중 종료됐다. 기존 정리 자식이 scale-down을 마친 뒤 ownership을 확인해 `LiveBackend.cleanup`으로 auto/1 복원을 완료했다. 이 실패 자료는 `readiness/`와 `initial-readiness-failure.json`에 보존하고, 폴더 생성을 수정한 전체 검증을 `readiness-final/`에 별도로 수행한다. 실제 평가에서는 이미 생성된 Evidence 디렉터리를 전달하므로 이 오류는 operator 검증 스크립트에 한정된다.

기존 30분 clock qualification과 실제 reboot 증거는 그 당시 동결 소스의 증거로 유지한다. 현 소스가 새 30분 qualification을 실행했다고 주장하지 않는다. clock guard 소스는 동일하며, 새 inventory/cleanup 경로는 별도 현재 소스 검증으로 입증한다. 원래 10,234개 파일과 이번에 닫힌 무효 attempt 21개 파일의 불변도 확인한다.

### 사용자 지시와 남은 범위

사용자는 수정·검증 완료 후 기존 Sol 채팅에 재개를 전달하도록 승인했다. 이어 Astra가 30분마다 진행을 확인하고 운영 문제를 수정·검증·재개하여 평가를 완료하며, 이러한 무효 본 실험은 마지막에 다시 돌리도록 승인했다. 따라서 이전 4개 보충 한도는 현재 확인된 무효 본 실험 8개에 대한 별도 보충으로 확장된다. 유효하지만 미복구인 결과를 성공으로 바꾸려고 반복하지 않는다. 의도된 negative preparation의 무효는 이 보충 범위에 포함하지 않는다.

먼저 `s4-b03-off`, `s4-b03-on`의 원래 first-attempt를 실행한다. 그 뒤 다음 원본의 `-supplement01`을 순서대로 실행한다.

1. `s1-b02-a`
2. `s2-b03-p`
3. `s3-b02-m3600`
4. `s3-b03-m3600`
5. `s3-b03-p3600`
6. `s4-b01-off`
7. `s4-b02-on`
8. `s4-b02-off`

기존 본 실험 27건은 유효19·무효8이며 이전 attempt를 덮어쓰거나 primary에 대체 삽입하지 않는다. 재개는 새 `bed-inventory-v8` cohort와 hash-bound v5 authorization을 사용한다. 정책/H/SLO/load/판정/phase·비용 여유는 유지한다. 이후 운영상 무효는 원인 수정·검증과 새 별도 회차의 source/freeze를 거쳐 관리하며, 이 release가 동일 ID의 무제한 재시도를 자동 허용하지 않는다.

### 실행권과 정기 확인

실험 실행 담당은 Sol 채팅 `01a18317-e6fb-7ef0-8e7e-bb80dd3c5fa5`이며, Astra가 수정·검증을 수행하는 동안 대기한다. 재개 전달 전까지 기존 HOLD/REPAIR 및 active pointer를 유지한다. 인계 시 원문과 SHA를 보존한 뒤 새 authorization으로 해소한다. 단일 driver와 실행권을 유지하고 실행 중 소스를 편집하지 않는다.

기존 heartbeat `automation`을 Astra 채팅 `01a1829e-502e-7792-ab6c-ddbbd3f2fe91`의 30분 진행 점검·복구 일정으로 변경했다. 정상 진행의 반복 확인은 조용히 유지하고 의미 있는 진행·실패·수정·필요 조치·완료에 알린다. 전체 평가와 보충, 최종 분석·보고, 소유 자원 정리, VM 정지·원장 종료, 시각 원설정 복원을 확인한 뒤 일정을 종료한다.

비용은 최신 표시 잔액 136,983원에서 보고 이후 경과 및 앞으로 남은 작업을 추정한다. 과거 원장을 새 잔액에서 중복 차감하지 않는다. 정리 40,000원, 기타 20,000원 및 미확인 청구 지연 12시간의 보수적 가정을 유지한다. 확대된 10건의 초안 추정은 약9.21시간, 이 예비비를 제외한 여유는 점검 당시 약7,678원이며 실측 청구 잔액이 아니다. 매 재개와 정기 확인 시 다시 계산한다. 현금 초과·유료 전환·새 GCP 호스트 VM은 승인되지 않았다.
## Execution update

The two remaining main cases completed. S1 supplement01 then encountered a
CPU capture/root-filesystem issue and a local tunnel read/cleanup failure.
Its invalid attempt is now closed and preserved. Continue from
the S1 read repair handoff (`evaluation-s1-read-repair-2026-10-29.md`, 본 통합본에 포함) and
`s1-read-repair-v9/go-review.json` once its GO handoff is recorded.

---

## S1 supplemental operational read repair — 2026-10-29

_원래 파일: `docs/graduation/evaluation-s1-read-repair-2026-10-29.md`_


This supersedes the execution handoff in `evaluation-inventory-repair-2026-10-29.md`.
The active proof directory is
`artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s1-read-repair-v9`.
Use its `go-review.json`, `transition-authorization.json`, and `sol-handoff.json`
for the exact source commit, profile, freeze and current execution owner.

### Preserved boundary

All original main29 attempts are closed: valid21 (recovered18, not recovered3),
invalid8. Do not rerun the three valid unrecovered outcomes. The first S1
supplement (`s1-b02-a-supplement01/attempt-01`) failed during measurement and
then failed its initial cleanup. Sol closed it under unchanged inventory-v8
source253: strict invalid, cleanup true, with a separate before-cleanup copy
and sealed invalid copy. Original 10234 files, the preceding invalid21 files,
and the two newly completed main results remained unchanged. Worker 1/auto,
same three existing GCP VM identities, clean fixtures, and original clock
configuration were verified. Closure evidence is in
`inventory-execution-2026-10-29/s1-supplement01-failure/closure.json`.

### Cause and repair

1. kubectl actually reported `The connection to the server 127.0.0.1:16444 was
   refused`. The transient classifier only matched `connection refused`, so
   the S1 reconnect callback was never invoked. Match the canonical sentence
   while retaining permanent-error precedence, identity checks, command caps,
   cumulative deadline and original H.
2. CPU capture used `/tmp` although the registered application explicitly has
   `readOnlyRootFilesystem: true`. The capture intent recorded `Errno 30`, and
   subsequent reads could not find the file. Capture once into the existing
   `/dev/shm` tmpfs instead. Preserve the same `/sys/fs/cgroup/cpu.stat` input,
   capture/readback protocol and original CPU interpretation. No image,
   Pod security context, workload, load, trigger, SLO or judgement changes.
3. The cleanup transport watcher repaired the missing tunnel only after the
   first cleanup command had already failed. After checking ownership, run
   the existing coordinated local tunnel ensure synchronously before cleanup.
   Do not replay cleanup mutations or measurement actions.

The new continuation gate compares these three mixed modules against the
frozen predecessor AST, allowing only the exact changes above. Other source
changes are the explicit supplement plan, release checks, registry hashes and
regression tests. The old clock, calibration, inventory and worker preparation
code remains byte-identical; its prior evidence retains its original source.

### Verification

- Full `test_fresh*.py` suite: 203 passed. A draft test expected one identity
  check, but the existing contract checks before retry and after readback;
  that assertion was corrected and the draft failure preserved separately.
- The actual registered image and security context were used in an owned,
  out-of-sample Job in `default`. CPU capture succeeded once in `/dev/shm`.
- The managed local tunnel was stopped. The actual S1 read adapter received
  the canonical refusal, restored the tunnel, and read the same Job's logs
  with stable UID in 19.366 seconds within its original 60-second budget.
  Only the adapter's in-process namespace was bound to the fixture namespace.
- The fixture was deleted with its UID precondition and absence verified.
  A second local tunnel stop exercised actual `LiveBackend.cleanup`; its
  synchronous preflight restored transport and all cleanup checks passed.
- Qualification source stayed unchanged. The initial operator-only YAML
  conversion parser failed before fixture creation; its directory/log and
  script were preserved, then the JSON stream parser was corrected. It was
  never an experiment attempt.

### Execution plan and ownership

New cohort: `bed-s1-read-v9`. No main or preparation measurements are repeated.
Execute in this order, one driver and one attempt at a time:

1. s2-b03-p-supplement01
2. s3-b02-m3600-supplement01
3. s3-b03-m3600-supplement01
4. s3-b03-p3600-supplement01
5. s4-b01-off-supplement01
6. s4-b02-on-supplement01
7. s4-b02-off-supplement01
8. s1-b02-a-supplement02

The original invalid S1 supplement01 remains a separate excluded result.
The new plan reserves supplement02 even though supplement01 is already
finished. All current-cohort completed work is excluded from subsequent
forward reservations only after its immutable evidence is checked.

Astra owns repair until explicit GO handoff. Sol chat
`01a18317-e6fb-7ef0-8e7e-bb80dd3c5fa5` then owns sequential execution.
Astra retains the existing 30-minute heartbeat; do not create a duplicate.
On a new operational failure, stop the next fault, preserve evidence, close
owned cleanup, review the cause, qualify a new source and create a separate
later supplement if warranted. Do not overwrite or promote invalid attempts.

The full remaining eight-case estimate plus lifecycle is approximately
26999 seconds. Recompute credit with the latest displayed balance, elapsed
time, remaining work, 40000 KRW cleanup reserve, 20000 KRW other reserve and
the explicitly unconfirmed 12-hour posting-lag assumption. The historical
ledger must not be subtracted again. Admission remains within credit only;
no paid conversion, cash overage or new GCP host VM is authorized.

After all supplements: complete separate primary/supplement/operational
analysis and report, owned cleanup, VM stop, ledger closure, and original
clock restoration. Then disable/delete Astra's heartbeat. Do not archive
the prior chats.

---

## S3 process capture continuation, 2026-10-29

_원래 파일: `docs/graduation/evaluation-s3-capture-repair-2026-10-29.md`_


The v9 S2 supplement completed valid/recovered/safe/clean. The next
`s3-b02-m3600-supplement01` stopped at JSON decoding before injection acceptance;
its attempt remains invalid, sealed and cleanup=true. Main29 remain valid21 /
invalid8, including three valid unrecovered outcomes that must not be replayed.
There are three closed supplemental attempts: one valid and two invalid.

### Reproduced cause and change

On the actual surviving worker, `crictl ps --name db -o json` wrote valid JSON.
Successful `iptables -C` checks printed their matched rules to stdout before
`cat` printed that file. The original chained expression therefore failed at
JSON character zero. The original failed response was not saved, so the new
reproduction is evidence of the same failing code path, not a recovered copy of
that historical response.

`fresh_s3_capture.read_s3_capture` redirects only the two successful rule-check
stdout streams to `/dev/null`, preserves their exit statuses and stderr, and
checkpoints the raw capture response before JSON decoding. It never repeats
fault injection or recreates a bad capture. Fault commands, ownership checks,
container/Pod UID matching, H, SLO, load and judgement remain unchanged; an AST
comparison against frozen v9 enforces that scenario boundary.

210 tests passed. Live qualification uses the pinned database image in an owned
Pod and empty owned iptables chains, with no DROP rule, data volume or experiment
attempt. It reproduces the old parser failure, validates the exact production
reader against the same running container/Pod UID and confirms owned cleanup.
The first qualification's deletion wait expired after the fixed reader passed;
its actual resource absence was independently confirmed and its evidence was
preserved. A new fixture with one-second termination grace verifies the complete
qualification and cleanup. This setting belongs only to the temporary fixture.

### Separate continuation

New cohort: `bed-s3-capture-v10`. Execute these seven cases in this order:

1. s3-b03-m3600-supplement01
2. s3-b03-p3600-supplement01
3. s4-b01-off-supplement01
4. s4-b02-on-supplement01
5. s4-b02-off-supplement01
6. s1-b02-a-supplement02
7. s3-b02-m3600-supplement02

Preserve all original attempts and both invalid supplemental attempts. Preserve
valid S2 supplement01 and all valid unrecovered outcomes. The new authorization
is `user-authorized-s3-capture-continuation-v7`; its audit binds the full source,
profile, historical freezes, tests, actual qualification and forward budget.
Only the artifact cohort, latest credit reference and environment run ID change
in the profile. The same three host VM IDs and management cluster UIDs are
verified after the intervening safety stop/restart.

The user reported used314551 / total435523 KRW at receipt
2026-10-28T22:43:37Z, giving remaining120972 KRW. Billing cutoff is unknown.
Reserve all remaining work (about6.73h including final lifecycle25min),
subsequent elapsed usage, cleanup40000, other20000, and unconfirmed12h posting
lag32000. Recalculate at admission; never subtract old ledger totals again.
No cash overage, paid conversion or new GCP host VM is authorized.

### Evidence and ownership

Authoritative directory under
`artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`:
`s3-process-read-investigation-v10/`, particularly `reproduction.json`,
`tests.json`, `qualification.json`, `admission-readback.json`,
`remaining-budget.json`, `transition-authorization.json`, `go-review.json` and
`sol-handoff.json`. Read these actual records for current status and commit.
Until GO and handoff, Astra holds sole source/infra ownership and HOLD remains.
After handoff, Sol owns sequential execution; Astra only monitors every30min.
Do not launch a duplicate driver or edit source during an active attempt.

---

## DNS 준비 검사 복구 및 마지막 보충 인계

_원래 파일: `docs/graduation/evaluation-dns-readiness-repair-2026-10-29.md`_


2026-10-29. 기준 경로: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-probe-investigation-v11`.

### 결과 보존과 남은 범위

- 원본 main 29: 유효 21, 무효 8, 전부 종료·정리 완료.
- 이전 보충 10: 유효 7, 무효 3, 전부 종료·정리 완료. 원본 무효 8개 중 7개의 보충이 유효하게 완료됐다.
- 마지막 원본은 `s3-b02-m3600`. 다음 별도 ID는 `s3-b02-m3600-supplement03`, 순서 48이다. 다른 원본·보충·유효 미복구는 재실행하지 않는다.
- `closed-progress.json`은 전체 과거 campaign 및 attempt 해시를 검증한 집계다. 원본 유효 미복구 3개와 보충 유효 미복구 3개를 그대로 유지한다.

### 확인된 운영 원인과 복구

`s3-b02-m3600-supplement02`는 fixture 준비 중 DNS 검사에서 실패했다. 실험 adapter나 장애 주입에 진입하지 않았고, 워커 2→1 정리의 DNS 검사도 실패했다. 이미지 두 종류 모두 같은 경로에서 실패했으므로 이미지 차이는 원인으로 판정하지 않는다.

제어 노드가 있는 `osk8s-compute01`의 Neutron worker security-group IP set에는 삭제된 워커 `10.6.0.179`만 남고 현재 워커 `10.6.0.47`이 없었다. Neutron API와 compute02의 집합에는 현재 주소가 존재했다. 실제 패킷 관찰은 워커에서 IPIP DNS 요청 8개가 나갔지만 CP 게스트에는 도착하지 않았음을 보였다. 해당 ingress 규칙은 worker remote-group 집합을 참조한다. 캐시 불일치와 실제 차단 경로는 확인했지만, 최초 이벤트 누락/순서 뒤바뀜의 내부 RPC 원인은 확정하지 않는다.

compute01의 기존 `neutron_openvswitch_agent`만 재시작했다. 동일 컨테이너 ID, 동일 Neutron 보안 규칙을 확인했고 캐시는 현재 포트와 일치했다. 원래 DNS 준비 검사가 통과하고 해당 probe 소유 자원도 제거됐다(`agent-reconcile/result.json`). GCP 호스트·보안 정책·실험 장애·부하·H·SLO·판정은 바꾸지 않았다.

실패 당시 18개 파일은 `failed-attempt-initial-copy/`와 해시로 보존했다. 기존 실패 probe Pod를 증거 보존 후 소유권 검사로 정리하고 worker-control recover를 수행했다. 원래 attempt에 `resume-cleanup`만 실행하여 `VERIFIED`, `trial_valid=false`, `cleanup=true`로 봉인했다. 최종 24개 파일의 해시는 `closed-attempt-sha256.json`, 사본 보존과 주입 부재 확인은 `closure.json`이다. 실패를 성공으로 승격하지 않았다.

### 소스와 재검증

v10 source259 대비 과학·계측·장애·판정 코드와 설정은 byte 단위 동일하다. 새 source263은 마지막 보충03 게이트와 dispatch, 준비 probe 직전의 Neutron 캐시 가드, 원격 호출 등록부, 회귀 및 예산 추정만 변경한다. 기존 probe 본문은 선행 hook을 제거한 AST 비교로 불변이며, 기존 343개 원격 호출 정책도 유지한다(새 등록부 348개). 이전 main29 및 보충10의 판정/정리/증거 해시를 보존하고 마지막 원본 하나만 허용한다.

221개 fresh 회귀가 통과했다(`tests.json`, `tests.log`). 초기 신규 테스트는 보충 block 이름까지 원본과 같다고 잘못 가정하여 실패했고, 시나리오/모드의 동일성만 검사하도록 바로잡았다. 초기 실패 로그도 별도로 보존했다. 추가 worker-control/lifecycle 50개 테스트에서는 48개가 통과했고, 2개 오류는 수정 전 v10 frozen source의 임시 복사에서도 같은 테스트·같은 예외로 재현됐다. 하나는 옛 OwnedProbeReads AST 템플릿, 하나는 get/k mock 가정이다. 이번 변경의 새 회귀로 판정하지 않으며 `related-tests-baseline.json`과 양쪽 로그를 보존한다.

첫 1→2→1의 원래 DNS probe는 모두 통과했지만 삭제된 새 워커 `10.6.0.237`이 compute01 캐시에 남아 엄격 정합 검증이 실패했다. 수 분 뒤에도 남음을 확인하고 첫 검증 파일과 로그를 보존했다. 단회 재시작만으로 충분하다고 판정하지 않았다.

`scripts/lib/neutron_members.py`는 fresh 준비 probe 이전에 Kubernetes node/Nova host/Neutron SG 포트를 묶어 확인하고, 불일치가 있는 기존 agent만 한 번 재시작한다. 보안 규칙은 바꾸지 않는다. 측정 token 또는 미복원 clock guard가 있으면 차단한다. 재시작은 durable journal을 먼저 기록하고, 응답이 불명확하면 다시 보내지 않는다. 다음 호출은 실제 캐시·동일 컨테이너를 읽어 완료만 확인하거나 수동 복구를 요구한다. 전체 450초와 호출별 최대 45초 안에서 수행하며 기존 준비/정리 phase 한도를 늘리지 않는다.

새 실제 검증(`live-qualification-02`)은 UTC 04:13:17에 통과했다. 실제 잔류 캐시를 production hook으로 복구했고, 건강한 증설 단계는 재시작 없이 통과했으며, 축소 후 다시 남은 주소도 필요한 compute01 agent만 재시작하여 정리했다. 동일 보안정책에서 기존 워커 1→2→1 명령과 각 단계 원래 DNS probe, 양쪽 호스트의 worker/CP SG 멤버 정합, 최종 auto/1·소유 정리·동일 인프라 identity를 확인한다. 이 검증에는 실험 장애를 주입하지 않았다. `qualification.json`에 source263, runner 해시, 양쪽 SG 정합, 원래 probe 통과, auto/1 소유 정리 및 동일 환경 ID를 기록했다.

### 재개 상태

실제 증감 검증과 live admission이 완료되고 새 authorization/profile/freeze 및 인계가 기록되기 전에는 실행하지 않는다. 수정·검증 중에는 Astra가, 인계 수락 뒤에는 Sol이 단독 소유권을 갖는다. 최신 확정 상태는 `qualification.json`, `admission-readback.json`, `go-review.json`, `sol-handoff.json` 및 이후 실행 progress를 따른다.

### 비용과 종료

최신 사용자 표시 잔액 120,972원(수신 UTC 2026-10-28 22:43:37, 청구 cutoff 미확인)에서 이후 경과와 앞으로의 전체 작업만 차감한다. 기존 원장 비용을 중복 차감하지 않는다. 마지막 실험+종료 예약은 4,979초(약 83분; 새 캐시 검사 여유 600초 포함); 실제 준비/재검증 시간은 이후 경과로 갱신한다. 정리 40,000원, 기타 20,000원, 미확인 12시간 청구 지연 32,000원을 유지한다. 최신 수치는 `remaining-budget.json`이다. 현금·유료 전환·새 GCP 호스트는 승인되지 않았다.

Sol은 한 driver로 마지막 별도 회차를 실행하고 최종 증거·분석·보고, 소유 자원 정리, 동일 3개 VM 정지, 원장 종료, 시각 원설정 복원을 검증한다. 무효 원본/보충과 운영 버전을 분리 보고한다. 이 30분 heartbeat는 Astra만 관리하며, 모든 종료 조건 확인 후 삭제/비활성화한다. 이전 채팅은 archive하지 않는다.

---

## S2 extension 사전 준비 및 실행자 인계 — 2026-10-29

_원래 파일: `docs/graduation/fresh-extension-preparation-2026-10-29.md`_


이번 작업은 사전 수정·오프라인 검증·커밋·읽기 전용 preflight까지만 수행한다. 실제 environment-ensure, live freeze, case 실행, 장애 주입, VM 조작은 수행하지 않았다. 원래 main29·보충·준비 자료와 manifest, release/authorization 체인은 수정하지 않았다.

### 고정 cohort와 구현

순서는 `s2-x01-s`, `s2-x02-s`, `s2-x03-s`, `s2-x04-p`다. purpose/stage는 별도 `extension`, 각 case 최대 1 attempt이며 기존 primary와 합치지 않는다. `freeze-extension`은 깨끗한 커밋과 새 전용 디렉터리를 요구하고 커밋/source가 freeze 도중 변하면 거부한다. 이번에는 synthetic freeze/run만 시험했다.

`FreshS2.finish`의 진단식, 연속 2회 진단, 다음 관측 시각, `now+420 < H end` 분리 진입 조건을 P/S가 공유한다. `split_if_enabled`의 `b['node']` 이동, Ready/readback, `action_requested`/`action_applied`의 대상과 actor도 같다. 차이는 P만 `set_rate`와 후속 QoS rate ladder를 수행하는 것이다. 따라서 QoS 처리 자체의 시간과 QoS 조정 이벤트는 S에서 발생하지 않으며, 실제 실행의 절대 시각까지 동일하다는 뜻은 아니다.

미부착 QoS policy/rule은 fixture에서 그대로 생성한다. `FreshOwnedLab.create_owned`는 해당 policy의 rule을 읽어 `max_kbps == 6000`과 `direction == egress`를 확인하며 포트 부착을 요구하지 않는다. 기존 `S2.cleanup`은 포트가 무정책이면 unset을 건너뛰고 소유 policy를 삭제한다. 이후 `Campaign.verify_cleanup`이 해당 policy 부재를 확인한다. 미부착 삭제, 6000 rule 소유 확인, 다른 rate 거부를 오프라인 테스트했다. 이 경로를 이번에 클라우드에서 실행했다고 주장하지 않는다.

초안의 `fresh_analysis.py`에 있던 두 줄의 S 분기는 live calibration 소스 동등성 검사를 실패시켰다. 기존 release 검사를 넓히는 대신 해당 파일을 원본 그대로 유지했다. 새 `fresh_extension.judge_split_only`가 기존 `_judge`의 결과에서 S2/S extension에 한해 `split_and_qos`를 `split_only`로 바꾸고 safety 및 이에 종속된 safe_recovered만 계산한다. 캠페인과 측정봉인에서 이 경로를 선택한다. P/M은 기존 경로를 그대로 사용한다. UTC 지연, request/bin 계산, 회복 정의, contract_valid, 조치 요청/적용의 H 범위 검사, uploader의 H 전체 제공 조건은 변경하지 않았다.

### v12와 credit

- profile: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v12.json`
- profile SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`
- credit: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/extension-prep-2026-10-29/latest-credit-20261029T144000KST.json`
- credit SHA-256: `efe664e0d83dbce98c1eb3c667c582db99d7e814775dfea293b910bd647e3e23`

v11 대비 변경은 `operations.artifact_root`의 `bed-extension-v12`와 `operations.stability.credit_reference`의 경로/SHA뿐이다. profile의 모든 과학적 값과 host identity가 동일함을 재귀 비교했다. profile 및 credit은 기존 `.state/`·`artifacts/` 정책대로 로컬 증거이며 Git에 강제로 포함하지 않았다.

credit 사용자 원문은 `₩320,850 / ₩435,523 크레딧 사용됨`이다. 보고 시각은 사용자 지시에 따라 2026-10-29 14:40 KST 무렵으로 기록했고 정확한 청구 cutoff로 취급하지 않는다. total 435523, used 320850, displayed_remaining 114673, cleanup reserve 40000, 기타 reserve 20000이다. 과거 원장을 새 표시잔액에서 다시 차감하지 않는다. 기존 12시간 미반영 청구 가정과 비용률을 유지한다.

`fresh_campaign.py validate --profile <v12>`는 통과했다. 예약은 요청된 `4*37*72+1500 = 12156`초다. forward margin은 시간에 따라 감소하므로 최종 값은 커밋 후 생성되는 `extension-prep-2026-10-29/preflight-final.json`의 `checks.credit.forward_credit.margin_krw`를 기준으로 한다.

### 검증과 사후 분석

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

### preflight와 실행자 조건

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

---

## S2 extension 실행 결과 — 2026-10-29

_원래 파일: `docs/graduation/s2-extension-results-2026-10-29.md`_


환경 재기동은 **16:08:28 KST에 성공**했지만, S2 extension 네 case는 각 1 attempt 모두 **장애 주입 전 준비 실패로 무효**가 됐다. 고정 profile의 `read_identity.environment_run_id=env-8093c4a92ee7`과 새 환경 `env-aef5b165ff9f`가 달라 Neutron 준비 검사에 앞선 하네스 identity guard가 준비·정리를 거부했다. 각 case에 `resume-cleanup`을 1회씩 수행해 모두 `VERIFIED`, `cleanup=true`로 봉인했고 **17:15:49 KST에 기존 VM 3대 TERMINATED 및 원장 종료를 확인**했다. S/P 성능 측정값은 없으며 QoS 필요성에 관한 새 근거를 얻지 못했다.

### 고정 조건과 직전 시도

- 브랜치: `codex/fresh-evaluation-execution-20261026`. 이번 실행 시작 HEAD는 `6a99d5591be27e2f62baad59504812c09f189c23`이며 작업 트리는 깨끗했다.
- 기존 freeze의 HEAD는 `81164c3a9cf08d218f494acd7e47485441b11209`다. 두 HEAD 사이 변경은 직전 결과 문서뿐이며 frozen/current source·profile·override 검사를 통과했다. **다시 freeze하지 않았다.** 기존 frozen manifest SHA는 시작 전후 동일하다.
- PROFILE: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-extension-v12.json`.
- SHA-256: `25c05d55fe3d553d0f001ec3f75c3d14c41441595c4af9b2eac4b5aa800bae39`.
- ROOT: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v12`.
- 모든 harness action은 `export ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env` 후 `bash evaluation/graduation-evaluation.sh --fresh <action>`으로 호출했다. preflight와 분석은 지정된 Python 진입점을 사용했다.
- 코드·profile·SG 규칙·OpenStack 설정을 수정하지 않았다. 새 GCP VM 생성, 사양 변경, 유료 전환, case 재실행, 실험 mutation 재전송은 없었다. 기존 하네스가 수행한 소유 워커 준비·정리만 실행했다.
- 직전 시도(15:23:11–15:48:07)는 ensure Ready timeout으로 attempt 0이었다. 해당 기록과 분석 파일, 문서 커밋 `6a99d55`를 보존했다. 사용자가 별도로 승인한 이번 환경 재기동은 case 재시도가 아니다.
- 직전 시도 종료 뒤 생성된 pending 4건의 manifest를 그대로 사용했다. 이번 시작 시 순서 `s2-x01-s → s2-x02-s → s2-x03-s → s2-x04-p`, 모두 pending·attempt 0을 확인했다.

### 이번 실행 시간과 admission gate

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

### Case별 판정과 원인

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

### 연결 진단과 복구 여부

이번 ensure는 성공했으므로 사용자 절차 4의 **ensure 실패 시에만 수행하는** VM RUNNING 상태 네트워크 진단 분기에 들어가지 않았다.

| 구간 | 이번에 확인한 범위 |
|---|---|
| Mac → controller / workload API | ensure의 management/workload Kubernetes Ready 검사가 통과했고, case 준비 중 워커 2대 Ready도 기록됐다. readiness 경로의 응답은 확인 |
| controller → floating IP | 별도 nc/ping/route 진단 미수행. 이번에 이 구간의 지속 timeout은 확인되지 않음 |
| router namespace → CP fixed IP | 별도 ping/nc 미수행 |
| CP VM 게스트·Neutron agent/ipset | 실패 분기의 console/agent/ipset 진단 미수행. guest 고장 또는 agent dead/cache 불일치로 이번 실패를 판정하지 않음 |

직전 controller→endpoint:6443 timeout의 **근본 원인과 이번 재기동으로 정상화된 경위는 확정하지 못했다**. 이번 case의 차단 지점은 네트워크 hop으로 관측된 장애가 아니라 로컬 하네스의 고정 read identity 검사다.

명확한 Neutron agent down/dead 또는 ipset 불일치 증거가 없으므로 수동 `docker restart`는 **0회**, 허용 복구 뒤 추가 ensure도 **0회**다. 이번 재기동의 ensure 1회와 네 case의 cleanup-only 재개만 수행했다. 읽기 전용 원인 증거는 `operations/ensure-retry-20261029T070229Z/`에 보존했다.

### 사후 분석 지표

`fresh_extension_analysis.py`가 원래 유효 main 첫 attempt와 별도 보충 결과를 읽었다. `all-case-disposition-ensure-retry-20261029T070229Z.json`은 같은 입력의 무효·미실행 행도 campaign 경로와 함께 보존한다. extension을 main29 또는 보충과 합치지 않았고 새로운 pooled estimate를 만들지 않았다.

조치 후 위반율은 첫 `action_applied`부터 H 끝까지이며, 조치가 없는 M은 `diagnosis`부터의 비율이다. 따라서 M의 열은 실제 조치 효과를 뜻하지 않는다. p95는 H 전체에서 성공·내용 일치·deadline 내 요청에 조건부인 지연이며, 조치 후 p95가 아니다. 실패율도 H 전체 기준이다. strict 표기는 **V/F/I/R/S/C = trial_valid / fault_realized / impact_realized / recovered / safety / cleanup** 이다. 원 strict를 사후 지표로 승격하지 않는다.

#### S2 P / S / M

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

#### S1 P / M / A

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

#### 기존 무효·미실행 보존

| Case / 원 campaign | 판정 또는 제외 사유 |
|---|---|
| s1-b02-a / bed-a/s1-main-v1 | 무효 첫 attempt: execution interrupted, request arrivals incomplete, total request indexes 부족, `service_after` 증거 없음. cleanup=T, recovered=null |
| s2-b03-p / bed-transport-v2/s2-main-transport-v2 | 무효 첫 attempt: `judgement_error:UnboundLocalError` (`start` 미할당), cleanup=T. 후속 보충으로 대체하지 않음 |
| s1-b03-m, s1-b03-a / bed-a/s1-main-v1 | 원 manifest의 미실행 슬롯. 위 유효 행은 bed-transport-v2의 별도 기록 |
| s2-b03-m / bed-transport-v2/s2-main-transport-v2 | 원 manifest의 미실행 슬롯. 위 유효 행은 bed-judgement-closure-v3의 별도 기록 |

무효 S1 A 행의 높은 위반·실패율은 불완전한 요청과 결측을 포함한 저장 지표이며, 관측된 서비스 성능의 유효 추정치로 비교하지 않는다. 유효 main 및 보충의 `missing=[]`이고 cleanup=T다. 이번 extension 네 무효 행은 위 8개 missing을 유지하며 모든 성능 지표가 null이다. 무효 행의 원 missing 목록·attempt 오류·campaign 경로는 `all-case-disposition-ensure-retry-20261029T070229Z.json`에 보존했다. S1 V1은 SLO가 달라 P/M/A 분석에서 제외한다.

### 비교와 해석

- **S 대 P, S 대 M:** S의 유효 실측이 없어 API 위반율·지연 및 upload goodput의 차이를 계산할 수 없다. x04도 무효여서 같은 날짜 P anchor가 없다.
- 기존 S2 main P는 조치 후 API 위반율 0%, H 위반율 0.208–0.292%, 조건부 p95 352.23–358.17 ms였다. main M은 진단 후 위반율 1.721–2.339%, H 위반율 1.667–2.250%, p95 441.85–448.71 ms였다. 이는 기존 날짜의 기술 통계다.
- 기존 main P의 upload goodput은 623,029–628,272 B/s, M은 1,806,172–1,821,027 B/s였다. case 평균은 각각 약 625,650 및 1,815,493 B/s로 P가 약 65.5% 낮았다. 결합 정책 P의 API 지표 개선과 upload 처리량 감소가 함께 관측됐지만, 분리와 QoS 각각의 기여는 이 비교로 분해할 수 없다.
- 기존 main P 2건은 impact_realized=F이고 recovered=T다. 이 결과를 뚜렷한 장애 영향에서 회복한 두 건으로 해석하지 않는다. 별도 보충 P는 impact_realized=T지만 main에 합치지 않는다.
- **이번 실행으로 “K8s 분리만으로는 부족하고 Neutron QoS가 필요하다”는 주장을 뒷받침하거나 반박할 수 없다.** S가 API를 보호하지 못한 유효 결과라면 해당 조건의 QoS 필요성 근거가 되고, 보호했다면 주장을 축소해야 하지만, 이번에는 어느 조건도 유효하게 측정되지 않았다.
- S1 P의 조치 후 위반율은 0.078–0.136%, M의 진단 후 위반율은 2.444–2.633%, A는 2.243–2.804%다. 이 역시 기존 결과의 사후 기술 비교이며 본 extension의 신규 결과가 아니다.

### 비용과 종료 검증

- 이번 실제 bed 세션은 **4362.545초 = 1시간 12분 42.545초** (16:03:07.303547–17:15:49.848191 KST)다. ensure·준비·실패·cleanup·down 및 사이 대기를 모두 포함한다.
- 고정 계획 비용률 2,500원/bed-hour로 **약 3,030원**. calendar-day 4,000원/일을 같은 구간에 비례 배분하면 **약 3,232원**이다. 실제 Billing 청구액이 아니며 VM별 청구시간 합계도 아니다.
- 직전 ensure 실패 세션 24분 56.093초를 포함한 두 세션 합계는 **5858.638초 = 1시간 37분 38.638초**, 동일 비례 비용 모델로 **약 4,340원**이다. 보존 디스크 등의 종료 후 비용은 계속 남는다.
- 종료 후 preflight의 전체 예약 12,156초 기준 forward margin은 6,723.73원으로 양수였다. 실제 청구 cutoff 미상, 12시간 미반영 청구 가정 및 정리 40,000원·기타 20,000원 reserve를 유지했다. 과거 원장을 표시 잔액에서 재차 차감하지 않았다.
- 기존 ID/type의 controller(e2-standard-4), compute01(n2-standard-8), compute02(n2-standard-4) 모두 TERMINATED. 공유 원장 최신 세션 stopped, 열린 세션 0. 종료 후 평가 프로세스·점유 advisory lock 0. 비점유 lock 파일은 보존했다.
- clock guard는 시작 전후 state가 같은 `restored`, active lease/pending request 없음이다. 네 case 모두 lease 획득 전 실패해 이번에는 network time Off나 시계 변경이 없었다.
- 17:10 KST macOS UI에서 자동 시간 **On**을 직접 재확인했고 `/etc/ntp.conf`는 `server time.asia.apple.com`이다. UI의 `Apple (time.apple.com.)` 표기는 남아 있다. 관리자 `systemsetup` 현재 서버 직접 조회가 불가능했던 직전 검증 한계는 해소했다고 주장하지 않는다. 이번 작업에서는 시간 설정을 변경하지 않았다.
- 분석기가 저장된 첫 attempt 해시를 확인했고 네 case 모두 attempt=1, VERIFIED, cleanup=true, 동일 frozen manifest/source/profile를 재확인했다. 코드 변경이 없어 회귀 테스트를 다시 실행하지 않았다.

### 한계 및 남은 위험

- S는 계획·시도 n=3이지만 유효 n=0, P anchor도 무효다. 단일 날짜의 소규모 사후 분석이며 main29·보충을 합치거나 원 strict를 바꾸지 않는다.
- S1 목적지 compute01(n2-standard-8)은 compute02(n2-standard-4)보다 크다. [ADR-0017](../../adr/0017-increase-recovery-target-compute-capacity.md)에 따른 용량·배치 차이가 있어 자동 대응 효과만의 인과 비교로 볼 수 없다.
- p95는 성공 요청에 조건부다. M은 진단 시각, P/S는 조치 시각을 anchor로 써 조치 후 구간이 동일하지 않다.
- **고정 v12 read identity와 재기동 environment run ID의 불일치가 해결되지 않았다.** code/profile 변경 금지에 따라 수정하지 않았다. 네 case의 1-attempt cap은 소진됐으므로 기존 cohort를 다시 실행할 수 없다.
- 직전 네트워크 timeout의 근본 원인, 시간 서버 UI/daemon 일치, 실제 청구액·보존 자원 비용은 별도 확인이 필요하다.

### 산출물과 증거

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
