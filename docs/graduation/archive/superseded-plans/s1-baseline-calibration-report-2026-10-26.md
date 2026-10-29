# S1 정상 baseline 보정 실행 보고 — 2026-10-26

**보정 미완료다. 정상 측정은 0/3, 별도 validation은 0/2이며 새 SLO·confirmed profile·SLO amendment를 만들지 않았다.** 기존 200ms와 두 DEV의 실패 판정은 유지한다. 준비 실패를 정상 부하 실패 또는 validation 실패로 세지 않는다. 이번 작업에서 경쟁 VM·장애 주입·정책 복구·A 재시작·DEV·pilot·main은 실행하지 않았다.

## 사전 등록과 구현

[사전 등록 프로토콜](../../s1-baseline-calibration-protocol-2026-10-26.md)을 새 측정 전에 작성했다. calibration3×300초→후보 동결→validation2×300초, 추가 진단0회다. 최대45개 bin의 선형보간p95에1.20을 곱해10ms 단위 올림, 최소200ms·상한500ms를 등록했다. 20초 bin·bad.05·고정 index0 첫60초·최종120초·warmup0을 유지한다. 외부 SLA가 없는 합성 workload의 실험 목표이며, 높은 SLO는 작은 저하를 정상으로 보는 연구상 대가를 갖는다. 이번에는 이 규칙에 넣을 새 정상 자료가 없다.

정상 전용 진입점은 `evaluation/s1-baseline-calibration.sh`, 실행·판정은 `evaluation/fresh_calibration.py`다. 정상 Job factory만 호출하고 DEV/scenario 실행기·경쟁 VM·조치 함수를 dispatch하지 않는다. profile/source/doc/override SHA와 복사본을 등록하고, 후보와 validation raw·문서·source의 후속 live freeze 검증을 연결했다. calibration schema는 일반 campaign의 stage/purpose로 허용되지 않는다.

동일 실제 URL·source placement·5rps·100000rounds·deadline5초를 사용하도록 구현했다. HTTP DNS+TCP 합계·응답 headers·handler Server-Timing과 host/guest1초 CPU·steal·PSI 수집도 구현했다. **부하 Job과 이 관측기는 실환경에서 시작되지 않았다.** Server-Timing은 dispatch 전 대기와 socket write를 제외하며, DNS와 TCP 개별 분해는 제공하지 않는다. 새 계측은 과거 DEV와 다른 source snapshot이다.

## 오프라인 독립 재계산

판정 모듈을 import하지 않는 표준 라이브러리 코드로 기존 raw를 재계산했다. 모든 bin의 p95·bad가 원 판정과 일치했다.

| 기존 DEV | index0–99 p95 / bad | index100–199 p95 / bad | index200–299 p95 / bad |
|---|---:|---:|---:|
| attempt-01 |120.19955ms /1|154.5564ms /4|205.6995ms /5|
| attempt-02 |124.82645ms /1|220.4454ms /6|112.04695ms /0|

이600개는 설계 참고와 실패 재현에만 사용했다. 새 calibration·validation·primary가 아니다. 60초 전체p95나 분위수 정의를 바꿔 기존 결과를 통과시키지 않았다.

## 실행과 실패

가동 예산은19:16:48 KST부터120분이며 측정/동결 마감20:16:48, cleanup 예약20:46:48, down/정지검증21:16:48이다. 기존 bed·사양·instance ID·CPU platform은 등록 상태와 일치했다. 기동 요청 전3대 TERMINATED와 병행 평가 프로세스 부재를 확인했다.

| KST | 관측 |
|---|---|
|19:16:48|기존 원장에 가동 시작, cold ensure 시작|
|19:20 부근|workload VM 첫 시작의 ACTIVE 유지 실패 기록. 이후 기존 ensure가 Ready로 진행|
|19:22:53|환경 Ready, cold ensure364.5초|
|19:23–24|worker fixed 전환·2개 scale 요청, 원래 auto/1·UID를 소유 원장에 저장|
|준비 중|처음 Nova 미준비, 이후 Node/Pod/Calico 미준비 조회. 로컬 workload API 연결 거절과 SSH tunnel Broken pipe도 확인|
|19:32:45|기존 tunnel ensure로 local API 연결 재설정|
|19:32:53|worker 준비 whole-phase600초 상한 초과. 정상 부하 시작 전 중단|
|19:32:53|cleanup의 worker 잠금 충돌. 실행기 결함으로 cleanup 실패 후 down 진입|
|19:34:03|추가 down을 중단. controller는 이미 STOPPING, compute2대는 RUNNING|
|19:35:49 이후|같은 소유 기록·연속 가동 원장으로 cleanup 전용 reconcile/ensure 및 worker 복원 재개|

첫 worker 준비의600초 상한은 이 실행기의 추가 제한이다. 승인된 fixture 최대1800초를 모두 소진했다는 뜻이 아니다. 준비 중 연결 실패와 이 제한으로 사전 등록한 측정 세트를 시작하지 못했다. 남은 25분 관측을 줄이거나120분 예산을 새로 시작하지 않았다. 중간 down은 안전한 cleanup 완료가 아니며 명시적으로 실패로 보존했다.

실행기 결함을 수정해 잠금 종료를 최대30초간 하나의 cleanup deadline 안에서 기다리고, 소유 cleanup proof가 통과하지 않으면 down을 차단한다. 기존 v1 snapshot·등록 문서·실행 로그는 수정하지 않는다. 후속 측정은 수정된 source의 새 registration이 필요하다.

## 확인 수준과 남은 일

- **확인:** 과거200ms 실패 수치 재현, 준비 중 로컬 API 연결 거절·SSH Broken pipe, worker 준비 timeout, cleanup 잠금 충돌, cleanup 실패 후 down 진입 결함.
- **추정/미확정:** 앞선 모든 readiness 실패가 터널 때문인지는 불명이다. 첫 guest ACTIVE 실패와 터널 끊김의 근본 원인도 확정하지 못했다.
- **미확정:** S1 정상 HTTP 지연 burst의 원인, 현실적인 새 SLO, 별도 validation의 수용 여부. 새1초 CPU·HTTP 분해 실측이 없어 원인을 CPU·DNS·네트워크 중 하나로 귀속하지 않는다.

새 정상 요청·20초 bin이 없으므로 기존200ms와 새 후보의 민감도 표, 첫60초 baseline, 지속300초 안정, 재악화 비교는 모두 미산출이다. 빈 표본을0ms·정상으로 채우지 않는다. calibration 반복은 향후에도 같은 host session의 반복이며 독립 환경으로 세지 않는다.

기존 DEV2 attempts·preparation0/8·main0/29·primary0 상태다. A 실제 restart 전달, V1 조건, S2~S4 효과는 계속 미검증이다. 다음 작업은 정상 보정 재개 프롬프트(삭제됨, `evaluation-final-20261029` tag에 보존)를 따른다. 보정 통과 후 새 profile로 별도 DEV→필수preparation8→main29 순서이며 이번에는 실행하지 않는다.

## 증거와 검증

로컬 artifact root는 `artifacts/baseline-calibration-2026-10-26/run-v1/`다. 최초 source commit은 `53764a4`이며 source 복사본·SHA는 `registration.json`/`source/`, profile 복사본은 `registered-profile.json`, 문서 복사본은 `protocol.md`에 있다. 최초 history345파일의 SHA는 `historical-preservation.json`에 기록했다.

`execution.log`, `phases.jsonl`, `attempts.jsonl`, `startup-observations.jsonl`, `workload-tunnel-disconnect.log`, `workload-tunnel-reconnect.log`, `fixture/fixture-ledger.json`, `cleanup-error.json`, `environment-after-interrupted-down.json`은 실패 이력이다. 최종 정리는 `cleanup-resume-proof.json`, `cleanup-resume-final.json`, `hosts-final.json`, 연속 가동/비용은 기존 `artifacts/fresh-evaluation-2026-10-26/bed-uptime-cost-ledger.json`에 보존한다.

최종 source 검증은 `make lint`305 tests+static shell 통과, 집중9 tests 통과다. 고정 index·누락/중복·clock·deadline, 후보 선정·상한/동결·validation 되먹임 금지, primary 유입 금지, 문서/설정 drift, Job apply 응답 소실 cleanup, cleanup 실패 시 down 차단을 검증했다. 이 테스트 결과는 실환경 calibration/validation 성공을 뜻하지 않는다.

## 최종 정리·가동·비용

cleanup proof는19:45:38 KST에 통과했다. worker auto/1, S1~S4 namespace 부재, 시험 taint 부재를 확인한 뒤 기존 down을 수행했다.

- 최종3대 TERMINATED 확인: **2026-10-26 19:51:32 KST**.
- 이번 연속 bed session: **34.73분**. 부분 controller 정지/재기동 중 compute가 계속 켜져 있었으므로 같은 session으로 계속 계량했다.
- 기존 DEV 포함 누적 가동: **1.3792시간**. 44h 신규 중단까지 **42.6208시간**,48h까지 **46.6208시간**이다.
- 원장의 보수적 누적 비용 계획액: **23888원**. 기존20000원 reserve가 한 번 포함돼 있으며 실제 청구액·실시간 크레딧이 아니다. 사용자 제공186234원에서 이 금액을 다시 차감하지 않았다.
- 이번120분 예산 초과 없음. 이전 DEV345파일과 최초 registration/source/profile/protocol 복사본의 hash 일치를 확인했다. persistent320GiB 디스크·기존snapshot은 보존한다.

다음 정상 보정의 새120분 배정+미실행DEV122분+preparation372.8분+main1508.8분은 **2123.6분(35시간23.6분)**의 보수적 미래 계획이다. 이번에 이미 쓴 시간은 여기에 재가산하지 않았다. 정상 관측은0분 완료이므로 전체25분 관측이 여전히 남는다. 가동 원장·달력 시간상 여유와 실제 수행 가능성은 다르며, 다음 기동 전 터널/준비 문제와 전체 세트 예약을 다시 검증해야 한다.

최종 기계 판독 요약은 `artifacts/baseline-calibration-2026-10-26/run-v1/release-summary.json`, 누락 슬롯은 `missingness.json`/`all-attempts-ledger.json`이다. 새 기준이 검증되기 전 평가 재개용 새 confirmed profile은 없다.
