# S1 정상 기준 확인 amendment — 2026-10-26

기존 승인 문서와 실패한 DEV·run-v1은 보존한다. 이 부록은 정상 보정 결과를 후속 새 snapshot과 연구 release에 연결한다. 정상 보정 통과는 DEV·pilot·main 성공을 뜻하지 않는다.

## 확정한 기준

**S1 SLO는 200ms를 유지한다.** Calibration 3회 × 300초의 45개 bin에서 최대 선형보간 p95는 **113.9381ms**였다. 사전 등록한 `max(200, 10 × ceil(1.20 × T / 10))`를 적용하면 여유·올림 중간값은 140ms이며, 최소값 규칙에 따라 200ms다. 상한 500ms는 사용하지 않았다. 후보·전체 profile·판정/실행 source는 **2026-10-26 20:50:41 KST**에 동결했다. Validation 자료는 후보 선정에 사용하지 않았다.

| 항목 | 유지할 값 |
|---|---|
| S1 부하 | 5rps, PBKDF2 100000 rounds, deadline 5초, max inflight 50 |
| 준비 | 매 회 HTTP fixture 재생성·새 stream, warmup 0 |
| 경로·배치 | 기존 Service DNS URL, source compute02, target/control-plane compute01 |
| 연구 baseline | 새 stream의 index 0–299, 고정 첫 60초 |
| healthy bin | index 100개씩 20초, 완전성·bad≤5/100·성공 p95≤200ms 모두 충족 |
| p95 | rank=(n−1)×0.95의 선형보간 |
| 본시험 | 총 1800초, 주입 뒤 H=1200초+30초 확보, 최종 안정 120초 |

200ms는 진입 gate와 S1 P/M/A의 전체 primary·회복 판정에 동일하게 적용한다. 정책의 기존 90초 대기 후 마지막 60초 상대 baseline은 연구 첫 60초와 구분한다. S2의 500ms, S3/S4의 2000ms, V1의 전용 100ms·상대배율 1.5 및 각 H·bin·deadline·bad 허용률은 변경하지 않는다.

외부 SLA가 없는 합성 workload의 공학적 목표다. 최적 SLO나 일반 신뢰도 보장이 아니다. 목표를 높이면 작은 성능 저하를 정상으로 세는 대가가 있으나, 이번에는 값을 높이지 않았다.

## 별도 검증과 해석

동결 뒤 validation 2회 × 300초를 수행했다. 각 run의 고정 첫 60초 baseline과 전체 15개 bin이 각각 통과했고, 최종 120초 정상·재악화 없음도 확인했다. Calibration 4500개와 validation 3000개 요청, 모든 75개 bin이 완전·healthy다. HTTP/등록 정확성/deadline 실패·누락·중복·generator rejection은 0이다. 개별 200ms 초과 13개는 삭제하지 않고 bad에 포함했다. 모든 요청이 200ms 이내였다는 주장은 하지 않는다.

같은 host session·worker VM의 반복이며, 매 회 HTTP namespace/fixture와 probe stream을 새로 만들었다. 좋은 60초 창을 찾거나 warmup을 추가하지 않았다. 요청·인접 bin·5회를 독립 환경 표본으로 세지 않는다. 계측 source가 과거 DEV와 달라 과거 600개는 새 정상 표본으로 합치지 않았다. HTTP 이미지 digest는 과거 DEV와 이번 5회가 일치했다.

이번 초과 요청에는 긴 DNS+TCP 연결 구간이 동반됐다. DNS/TCP 개별 시간과 클라이언트 스케줄링은 미분리이며, 과거 DEV burst의 정확한 원인은 여전히 미확정이다. 1초 CPU·steal·PSI 관측으로 짧은 경합까지 배제하거나 동시성을 인과 증명으로 쓰지 않는다. 이후 baseline 실패도 보존하고 주입을 막으며, 유리한 SLO로 다시 맞추지 않는다.

## 후속 freeze 계약

새 immutable profile: `/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-v2.json`

`analysis.s1_calibration`은 이 문서 SHA와 candidate/registration/validation raw·metrics·summary의 SHA를 연결한다. Live validator는 validation raw를 재계산하고 S1 설정·측정 source 일치를 검사한다. `operations.preregistered_documents`에 원 설정/프롬프트, 두 보정 프로토콜, 이 amendment와 새 재개 프롬프트를 등록해 freeze가 SHA·복사본·변경을 확인한다. `pilot_contract()`의 analysis/measurement에도 같은 계약이 들어간다.

기존 200ms 실패를 소급 통과시키지 않는다. 새 profile의 confirmed는 정상 입력·보정 확인이다. 다음은 별도 평가 세션에서 **새 snapshot DEV → 필수 preparation 8개 → main 29개** 순서다. 실제 A restart, V1 조건, S2~S4 효과는 아직 미검증이다. 이번 세션에서는 실행하지 않았다.

원자료는 `artifacts/baseline-calibration-2026-10-26/run-v2/`, 전체 bin은 `all-20s-bins.csv`, 독립 재계산은 `independent-request-check.py`와 `independent-analysis.json`에 보존한다.
