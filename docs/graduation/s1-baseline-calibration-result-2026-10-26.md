# S1 정상 baseline 보정·별도 검증 결과 — 2026-10-26

**S1 기준 200ms 유지, calibration 3회와 별도 validation 2회 모두 통과했다.** 한 번 재시도해 정상 7500개 요청·75개 완전한 bin을 확보했다. 기준을 올리거나 첫 60초 창을 옮기지 않았다. 기존 DEV와 run-v1 실패는 보존했고, 장애·A 재시작·DEV·pilot·main은 이번에도 실행하지 않았다.

## 선정과 별도 검증

최초 프로토콜의 `max(200, 10 × ceil(1.20 × T / 10))`를 적용했다. T는 calibration 45개 bin의 최대 선형 p95인 **113.9381ms**다. 20% 여유·10ms 올림의 중간값은 140ms이고 최소값 규칙에 따라 200ms다. **2026-10-26 20:50:41 KST**에 후보·전체 profile·판정/실행 source를 동결한 뒤 validation 2회를 수행했다. Validation을 보고 값을 맞추지 않았다.

| run | 요청 | 전체 p95 ms | 최대 bin p95 ms | 200ms 초과 bad | healthy bin | 고정 첫 60초 | 지속 300초 |
|---|---:|---:|---:|---:|---:|---|---|
|calibration-01|1500|103.074|113.938|6|15/15|통과|통과|
|calibration-02|1500|99.267|108.332|1|15/15|통과|통과|
|calibration-03|1500|98.991|107.069|2|15/15|통과|통과|
|validation-01|1500|96.915|104.778|3|15/15|통과|통과|
|validation-02|1500|101.487|105.771|1|15/15|통과|통과|

두 validation 각각 첫 3개 bin과 전체 15개 bin이 모두 통과했고, 최종 120초가 정상이며 재악화는 0이다. 각 bin의 예정 index100개가 모두 존재한다. Request/clock/schedule/deadline 검증 오류·누락·중복·generator rejection·HTTP/등록 정확성/deadline 실패는 0이다. 개별 200ms 초과13개는 bad에 포함했으며 deadline5초 이내였다. 모든 요청이200ms 이내였다는 주장은 하지 않는다.

기존200ms와 새 후보200ms 판정은 모든75개 bin에서 동일하다. 전체 표는 `artifacts/baseline-calibration-2026-10-26/run-v2/all-20s-bins.csv`, 독립 재계산은 `independent-request-check.py`와 `independent-analysis.json`에 있다. 판정 모듈을 import하지 않고 raw에서 재계산해 bin p95·bad·완전성·판정이 모두 일치했다. 정상 상태의 기술적 확인이며 복구 효과 증거가 아니다.

Bin20초·bad5%·선형 p95·index0 첫60초·최종120초·warmup0, 같은 URL·source 배치와5rps/100000rounds/deadline5초를 유지했다. 5회는 같은 host session·worker VM의 반복이며, 매 회 HTTP fixture와 stream을 새로 만들었다. 요청·인접 bin을 독립 환경 표본으로 세지 않는다. 이처럼 한정된 정상 관측은 일반 신뢰도나 장기 무장애 보장이 아니다.

## 원인 진단의 확인 수준

- **확인:** 이전19:28 snapshot은 worker2개 Available/Ready, Nova 모두 ACTIVE였다. Node·Pod·Calico는 local API16444 조회 거절이었다. 앞선 준비 실패를 VM 자체 실패로 단정하지 않는다. 이번 retry는 실제 readiness·배치를 통과했고 터널 재연결은0회였다. 보완의 실환경 수리 효과를 주장하지 않는다.
- **확인:** 이번200ms 초과13개에는 DNS+TCP 연결 경과130.509–169.993ms가 동반됐고, 서버 handler는56.235–65.555ms였다. 전체 run의 handler p95는63.722–66.027ms, 연결 합계 p95는6.432–7.803ms, headers 뒤 body 구간 p95는0.297–0.423ms였다. Generator monotonic 기준 queue p95는약0.89–3.63ms다. HTTP 전체를 서버 처리시간으로 부르지 않는다.
- **미확정:** DNS와 TCP 개별 시간, 연결 중 client 스케줄링을 분리하지 못했다. 과거 DEV index124 부근 burst와 이번 outlier가 같은 원인인지는 모른다. 계측 source가 달라 과거 자료와 합치지 않는다. 실제 HTTP 이미지 digest는 과거 DEV와 이번5회가 일치했다.
- **관측 한계:** 두 compute와 source guest의 CPU·steal·PSI를1초 간격331개씩 수집했다. Guest의 최대 실제 간격은약1.0094초다. 일부 physical host 수집은 stream보다약1초 늦고, client control-plane guest의 steal은 직접 수집하지 않았다. UTC 정렬의 clock 불확실성과1초 평균으로 subsecond 경합을 배제하거나 동시성을 인과 증명으로 쓰지 않는다. Source guest 최대1초 CPU PSI약17.56%, steal약0.52%도 원인 확정 증거가 아니다.

정상 변동은 존재하지만 이번75개 bin은 등록 기준을 충족했다. SLO를 높이지 않아 목표 완화의 추가 trade-off는 없다. 후속 DEV에서 baseline 실패가 다시 나오면 보존하고 주입을 막으며 유리한 값으로 재조정하지 않는다.

## 새 계약과 평가 재개 입력

[기준 amendment](s1-baseline-amendment-2026-10-26.md)와 [평가 재개 프롬프트](fresh-evaluation-resume-after-calibration-2026-10-26.md)를 사용한다.

- 새 profile: `/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-v2.json`
- Profile SHA-256: `7328bdd130dbc1c962fa0e637a4faec57a1a7c1f88dd054e335cce411d21adfe`
- Amendment SHA-256: `c766daad6343a0725ed20fa797adbb8ae8493e2feeb4c8d54b15edcbe6bc9d55`
- 등록 source commit: `32188ca`
- Candidate freeze SHA-256: `e80fd14cc70ad84c88c563a6dff6b811f5e8a7bf84abfa7217da5e2a25c799cc`

실제 Kubernetes v1.35.7, host ID/type/platform·flavor, MHC 실제0개, HTTP 이미지 digest와 증거 SHA를 새 profile에 연결했다. 과거 image catalog 참조와 이번 readback을 구분했다. Live profile 검증과 SLO210ms 변경 거절도 확인했다. 후속 freeze는 문서 SHA·복사본·profile/source·validation raw와 같은 pilot 계약을 검증한다.

새 profile의 confirmed는 정상 입력·보정 확인이며 DEV·pilot·main 성공이 아니다. 다음은 별도 세션에서 **새 snapshot DEV → 필수 preparation8개 → main29개** 순서다. A 실제 restart·V1 조건·S2~S4 효과는 여전히 미검증이다.

## 정리·가동·비용

소유 cleanup은 **2026-10-26 21:09:40 KST**에 통과했다. Worker auto/1·S1~S4 namespace 부재·시험 taint 부재를 검증한 뒤 기존 down을 수행했다. 새로 만든 worker VM도 삭제돼 기존 worker와 control-plane VM만 남았음을 확인했다. 3대 호스트 모두 TERMINATED의 최종 확인은 **2026-10-26 21:15:32 KST**다. 기존320GiB 디스크와 snapshot은 보존한다.

이번 원장 session은 **59.54분**, 최종 별도 readback 종료까지는 약 **59.56분**이며, 이전 실패·DEV 포함 누적 **2.3716 bed-hours**다. 새120분 예산을 초과하지 않았다. 누적 계획 비용 **26602원**에는 기존20000원 reserve가 한 번 포함돼 있다. 실제 청구액·실시간 크레딧이 아니며 사용자 제공186234원에서 중복 차감하지 않았다. 기존 가동 원장을 이어 썼다.

완료한 정상25분 관측과 이번 가동을 미래 시간에 다시 더하지 않는다. 남은 DEV122분+preparation372.8분+main1508.8분=2003.6분(33시간23.6분)은 기존 계획값이다. 44h 신규 중단까지 41.6284시간,48h까지 45.6284시간이며 새 실행 전 현재 달력·원장·예약으로 다시 판단한다. DEV와 전체 pilot 뒤에는 미실행분만 재산정한다.

검증은 make lint306개 테스트+static shell, 집중10개 테스트, 새 profile live 검증·SLO drift 거절,75개 bin 독립 재계산, 기존 DEV/run-v1/source/profile/protocol hash 일치다. Raw·모든 시도 원장·metrics·환경/clock·cleanup·host readback은 `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/baseline-calibration-2026-10-26/run-v2`에 보존한다. 비밀정보와 raw는 Git에 추가하지 않는다.
