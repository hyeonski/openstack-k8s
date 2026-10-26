# 새 세션용 — S1 정상 baseline 진단·보정·검증

워크스페이스 `/Users/hyeonseungkim/workspace/openstack-k8s`에서 **S1의 정상 상태 지연을 진단하고, 실측에 근거한 평가 기준을 확정·별도 검증해 다음 평가 세션에 인계**해 줘. 계획 제안에서 끝내지 말고 아래 범위의 구현·정상 부하 측정·분석·정리까지 수행해라.

사용자는 “장애 없는 정상 상태를 여러 번 측정해 현실적인 기준을 정하고, 이후 모든 비교군에 같은 기준을 고정 적용한다”는 방향을 승인했다. 관련 통상 작업마다 재승인을 묻지 않는다. 정상 상태 진단에 필요한 기존 bed 기동·fixture 준비·계측 보완·정상 요청 발생·소유 자원 정리는 허용된다. **이번 작업에서는 경쟁 VM·장애 주입·복구 조치·DEV A 재시작·pilot·main을 실행하지 않는다.** 다음 단계는 별도 인계한다. 이전 전체 평가 프롬프트의 자동 실행 범위보다 이 제한이 우선한다.

## 1. 먼저 읽고 현재 상태를 확인할 자료

- `artifacts/fresh-evaluation-2026-10-26/dev-failure-analysis.md`, `dev-failure-analysis.json`, `release-summary.json`, `progress.json`, `bed-uptime-cost-ledger.json`.
- `artifacts/fresh-evaluation-development-2026-10-26/dev-v1/`: 실패한 DEV의 frozen source/profile, 두 attempt의 `baseline-gate-requests.jsonl`, `baseline-gate.json`, `raw/http.jsonl` 등. 읽기 전용 이력으로 보존한다.
- `docs/graduation/fresh-execution-settings-2026-10-26.md`, `fresh-evaluation-execution-prompt-2026-10-26.md`, `fresh-evaluation-build-plan-2026-10-26.md`, `fresh-evaluation-run-plan-2026-10-26.md`, `consensus-research-plan-2026-10-26.md`.
- `evaluation/fresh_baseline.py`, `fresh_analysis.py`, `fresh_scenarios.py`, `fresh_campaign.py`, `fresh_contract.py`, `fresh_live.py`, `kubernetes/graduation-s1/loadgen.py`, `app.py`와 관련 실행기·tests.
- 저장소 지침, 현재 branch/status, `git log -5 --format=full`. 기존 작업을 덮어쓰거나 checkout을 강제로 되돌리지 않는다.

마지막 확인된 구현은 `a412611`, branch는 `codex/fresh-evaluation-execution-20261026`이다. 이전 프롬프트에 있는 “네 가지 사전 보완 미구현”은 과거 시점의 설명이다. 현재 코드와 증거를 확인하고 이미 구현한 작업을 다시 만들지 않는다. 모델 설정은 사용자 선택을 따르며, 이전 Sonnet 5.5 지정은 과거 검토 작업 한정이다. Claude 세션 재검토는 이번 작업에 필요하지 않다.

## 2. 이미 확인한 실패와 해석

- DEV 2 attempts 모두 **장애 주입 전** 고정 baseline 실패. preparation 0/8, main 0/29, primary 0.
- S1 기존 조건: 5 rps, PBKDF2 100000 rounds, warmup 0, deadline 5초, SLO 200ms, bin 20초, bad 허용 비율 5%. 등록 stream의 index 0부터 첫 300개를 100개씩 나눈 세 구간이 모두 healthy여야 주입 가능.
- 첫 시도 마지막 bin: p95 205.6995ms, bad 5/100. 두 번째 시도 가운데 bin: p95 220.4454ms, bad 6/100.
- 600개 요청은 모두 HTTP/정확성 성공·deadline 이내, generator rejection 0. 60초 전체 p95는 각각 약154.1ms/138.8ms지만 이를 기존 계약의 통과 근거로 바꾸지 않는다.
- 생성기 queue p95는 대략 1~2ms이며 지연의 대부분은 HTTP 호출 구간에 있다. 이는 서버 처리시간만이 아니라 DNS·연결·네트워크·스케줄링을 포함한다.
- 두 시도 모두 index124 부근(시작 약25초)에 지연이 모였다. 초기화·주기적 작업을 확인할 단서일 뿐 원인이 증명된 것은 아니다. Pod의 throttled 카운터 0과 약90초 host 평균만으로 짧은 CPU 경합을 배제할 수 없다.
- p95는 현재 선형 보간으로 계산한다. 100개 중 5개가200ms를 넘으면 bad 비율은 통과하면서 p95는 실패할 수 있다. 이 차이를 버그로 단정하거나 분위수 정의만 바꿔 기존 결과를 통과시키지 않는다.
- 마지막 종료 기록상 2026-10-26 18:01 KST에 호스트3대 TERMINATED, 소유 임시 자원 정리 완료, worker auto/1 복원. 이는 현재 상태의 보장이 아니므로 기동 전 readback한다.

## 3. 운영 범위·예산

기존 환경 `cloud-gcp-amd64-greenfield`, GCP 프로젝트 `openstack-k8s`, zone `asia-northeast3-a`, override `/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env`를 사용한다. 같은 bed의 다른 실행 프로세스·환경 잠금을 먼저 확인하고 병행하지 않는다. 기존 운영 진입점과 ownership cleanup을 재사용한다.

- controller e2-standard-4, source compute02 n2-standard-4, target/control-plane compute01 n2-standard-8의 사양을 유지한다. 새 프로젝트/bed·유료 전환·현금 초과 지출은 하지 않는다.
- 이번 작업은 **기동·준비·측정·정리·정지 확인 합계 약1~2시간**을 목표로 하고, 기동 요청부터 누적 **120분을 작업 예산**으로 등록한다. cleanup30분+down/정지검증30분을 예약하고, 새로운 측정이 남은 시간과 이 예약에 들어오지 않으면 시작하지 않는다. 로컬 구현·분석은 호스트가 꺼진 상태에서 최대한 끝낸다. 기존 whole-phase timeout은 이 예산을 새로 늘리는 권한이 아니며 더 이른 deadline을 적용한다.
- 안전 정리나 정지 확인에 예상보다 오래 걸리면 신규 작업을 중지하고 정리를 끝내며 초과 원인을 보고한다. 시간에 맞추려고 미정리 자원을 방치하지 않는다. 예산이 부족하면 검증 생략이나 자동 연장 대신 미완료 사항과 필요한 추가 시간을 보고한다.
- 전체 평가 마감은 **2026-10-29 00:00 KST**, 누적 bed-hours48h/신규 작업 중단44h와 기존 운영 gate도 유지한다. 이번 측정도 전체 가동 원장에 포함한다.
- 마지막 사용자 제공 크레딧은 186234원(10/26 17:10 KST), 만료일11/19였다. 기존 신규 작업 한도146234원/정리 reserve40000원과 원장을 읽고 이미 쓴 비용·잔여 과금을 고려한다. 사용자 제공 잔액을 실시간 조회값으로 부르지 않는다. 원장의 약22135원은 20000원 예비비를 포함한 보수적 계획액이며 실제 청구액이 아니다. 예비비를 세션마다 다시 더하거나 실제 잔액에서 중복 차감하지 않는다.

## 4. 측정 전에 진단·보정 프로토콜을 등록한다

새 artifact root `artifacts/baseline-calibration-2026-10-26/` 아래 고유한 실행 디렉터리를 사용한다. 이미 있으면 덮어쓰지 않는다. purpose는 calibration/validation으로 명확히 나누고 primary 입력 경로 밖에 둔다. 기존 frozen DEV/profile/raw/judgement는 수정하지 않는다.

첫 새 측정 전에 다음 내용을 문서·JSON·source hash로 고정한다. 문서를 먼저 쓰고 실제로 그 계약을 소비하는 실행 경로를 준비한다.

1. **측정 묶음:** 필요한 원인 분리용 짧은 진단은 최대2회×120초, 기준 산출용 정상 부하는3회×300초, 확정 기준의 별도 검증은2회×300초로 한다. 모두 장애 없는 부하다. 계획된25분의 보정·검증 관측과 최대4분 진단 외에 fixture 준비·clock·증거·정리 시간이 든다. 예산에 맞지 않으면 호스트 기동 전 알려야 하며 검증을 임의 축소하지 않는다.
2. **동일 조건:** 기준 산출과 검증에서는 본시험 예정 경로·source placement·5rps·100000rounds·5초 deadline을 유지한다. 매 회 고정된 fixture reset/준비 절차와 새 probe stream을 사용하고, 그 범위를 기록한다. worker VM을 매번 재생성할 필요는 없지만 동일 host session의 반복을 독립된 여러 환경이라고 표현하지 않는다.
3. **선택 규칙:** 새 자료를 보기 전에 어떤 통계로 SLO 후보를 고를지, 사용할 분위수·반올림·여유 계수의 정확한 수치, 허용할 상한과 그 공학적 이유를 정한다. “측정 후 적당한 값”으로 비워두지 않는다. 실제 외부 SLA가 없는 합성 workload의 실험 목표라는 점을 명시한다. 기존200ms를 유지할 조건도 포함한다. 이미 본 두 DEV를 설계 참고로 공개하되 새 validation 자료로 재사용하지 않는다.
4. **우선 유지할 판정:** bin20초, bad5%, 선형보간 p95, 고정 첫60초 baseline, 최종 안정120초를 우선 유지한다. 정상 지연 변동에 대한 근거 없이 여러 기준을 동시에 느슨하게 하지 않는다. SLO의 변경은 정상 측정에 근거해 가능하지만 전체 primary/회복 판정에도 같은 값이 적용되어야 한다. 진입 gate만 통과시키고 회복 목표는 별개로 남기는 변경은 하지 않는다.
5. **준비 절차:** 기본 warmup0을 유지한다. 초기화가 원인이라는 근거로 고정 settle/warmup을 추가할 필요가 있으면 변경 이유·고정 길이·새 index0의 시작 정의를 먼저 등록하고 같은 조건의 기준 산출·검증을 새로 한다. “정상이 될 때까지 대기”나 좋은60초 창 탐색은 금지한다. 정책 자체의 기존90초 대기/마지막60초 판단 창과 연구 baseline의 차이도 기록한다. 부하 총길이와 이후 H 확보 조건을 깨뜨리지 않는다.
6. **검증 수용 조건:** 후보를 동결한 뒤 두 validation run의 첫60초 baseline을 각각 판정하고, 300초 전체의 모든20초 bin·bad비율·p95와 재악화를 함께 공개한다. baseline 정상이라는 주장과 지속적으로 안정적이라는 주장을 구분해 각각의 수용 조건을 미리 정한다. 검증 실패 후 같은 validation으로 새 임계값을 맞추거나 통과할 때까지 재시도하지 않는다.

현재600개 자료는 짧은 burst가 있다는 증거다. 그것만으로 새250ms/300ms 목표가 타당하다고 정하지 않는다. 기준 산출은 정상 부하로만 하며, 장애군이 실패하거나 자동화군이 성공하도록 값을 선택하지 않는다. S2~S4와 별도 workload인 V1의100ms 목표는 이번 S1 자료로 함께 변경하지 않는다.

## 5. 진단·구현·측정

먼저 오프라인에서 실패 raw와 판정 코드를 독립 재계산한다. 정상 요청 생성·관측만 하고 주입 함수에 도달하지 않는 명시적인 calibration 경로를 만든다. 기존 A DEV 실행을 중간에 죽이거나 fault 함수를 몰래 무력화해 calibration으로 위장하지 않는다. worker 배치·ownership·clock·시간/비용 gate·cleanup은 기존 구현을 재사용한다.

HTTP 구간을 가능한 범위에서 DNS/연결/응답·서버 처리와 대조하고, host/guest CPU·steal·PSI 등은 burst를 볼 수 있는 해상도로 수집한다. 서버 처리시간이 없으면 client HTTP시간을 서버시간으로 부르지 않는다. DNS 우회나 health endpoint 등은 진단용 비교이며 실제 평가 URL을 조용히 바꾸지 않는다. 수집 자체의 부하와 원래 경로 변경 여부를 기록한다. 과도한 관측 도구 구축에 시간을 쓰지 않는다.

측정 결함·의도치 않은 백그라운드 작업을 발견하면 좁게 수정하고 변경 증거를 남긴다. 정상 인프라 부하나 실제 서비스 지연을 계측 오류로 취급해 지우지 않는다. source/fixture가 바뀌면 서로 다른 조건의 보정 자료를 하나로 섞지 않고 필요한 새 snapshot을 만든다. 결함 수정으로 계획된 측정 세트가 무효화되어 예산 안에 다시 완료할 수 없으면 부분 결과와 남은 작업을 인계한다.

보정 자료를 수집한 뒤 등록한 규칙으로 후보를 산출하고 **값·근거·profile·판정 코드·source를 동결한 다음에** 별도 validation2회를 수행한다. 보정3회만으로 통과 선언하거나 validation 결과를 후보 선택에 되먹이지 않는다. validation 실패는 실패로 보고하며 이번 작업에서 임계값 탐색을 반복하지 않는다.

## 6. 분석·계약 변경·인계

각 run의 raw 요청, 예정/시작/완료 시각, clock, 실제 배치, 전체300초와 고정 첫60초의 지표, 모든20초 bin, 오류·timeout·누락·queue, CPU/네트워크 관련 관측을 남긴다. 지연 burst와 사건의 동시성은 원인 증명과 구분한다. 요청이나 인접 bin을 독립 실험으로 세어 신뢰도를 부풀리지 않는다.

기존200ms 판정과 새 후보 판정을 같은 정상 자료에 나란히 표시해 변경의 영향을 공개한다. 이 표는 정상 상태의 기술적 민감도 분석이며 복구 효과 증거가 아니다. 큰 목표값을 택하면 향후 작은 성능 저하를 정상으로 보게 된다는 연구상 대가도 설명한다.

원인·기준·검증이 충분하면 `docs/graduation/`에 새 amendment와 calibration 보고서, 다음 평가 세션의 재개 프롬프트를 작성한다. 기존 승인 문서와 frozen 이력을 덮어쓰지 않는다. 새 immutable profile을 `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/`에 별도 버전으로 만들고, 보정 통과와 live DEV/pilot 성공을 혼동하지 않는다. 새 amendment·설정의 SHA/복사본을 후속 freeze가 검증하도록 연결한다. baseline/분석 validator·consumer·pilot 계약을 일치시키고 하드코딩된 옛 값과 불일치가 없는지 확인한다.

다음 세션은 **새 snapshot의 DEV → 필요한 preparation8개 → main29개** 순서를 따른다. 이번 작업에서 실제로 재개하지 않는다. S1 A 실제 restart, V1 조건, S2~S4 효과는 여전히 미검증이라고 명시한다. 후속 정상·장애 측정에서 미리 정한 SLO를 다시 유리하게 바꾸지 않는다. 남은 총 일정은 완료된 calibration 시간을 미래 작업으로 다시 더하지 말고, 실제 잔여 작업과 가동 원장으로 다시 계산한다.

최소 산출물:

- 사전 등록 프로토콜·source/config hash, calibration/validation별 raw·환경 identity·지표·모든 시도 원장.
- 원인 확정/추정/미확정 구분, 이전 기준 대비 새 기준의 변경·선정 근거·trade-off, 별도 validation 결과.
- 통과한 경우 새 profile/amendment/재개 프롬프트. 실패·시간 부족이면 무엇을 확인했고 무엇이 남았는지와 다음에 필요한 시간·조치를 구체적으로 기록.
- cleanup 증거, 실제 host 가동 원장·비용 추정, 최종 호스트 정지 readback.

코드를 바꾸면 관련 의미 있는 테스트와 저장소 필수 검증을 수행한다. calibration의 primary 유입 금지, 주입 경로 접근 차단, 고정 index/누락·deadline 판정, 후보 동결·문서/설정 일치, 예외 cleanup을 검증한다. 종료 시 소유 fixture를 정리하고 worker 제어를 복원한 뒤 기존 down 절차로 호스트3대의 TERMINATED를 확인한다. persistent 디스크와 무관한 자원은 보존한다.

비밀정보·raw 대량 자료는 커밋하지 않는다. 코드·문서 변경은 기존 컨벤션인 `type: 한국어 제목`과 변경 bullet·검증 본문을 포함해 커밋한다. 최종 보고에는 정상 기준이 어떻게 정해졌고 별도 검증이 통과했는지, 정확히 어떤 파일로 평가를 재개할지, 아직 검증하지 못한 사항을 짧게 설명한다.
