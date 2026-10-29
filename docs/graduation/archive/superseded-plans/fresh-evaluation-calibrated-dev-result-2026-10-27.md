# 정상 보정 후 S1 A DEV 결과와 후속 평가 보류 — 2026-10-27

사용자는 현재 DEV와 정리까지만 마치고 다음 실험 진입을 보류하도록 지시했다. 새 S1 A DEV의 두 번째 attempt는 독립 판정에서 유효성·장애/영향 실현·안전·회복·cleanup을 통과했다. 첫 번째 attempt의 인프라 실패는 그대로 보존했다. **preparation 0/8, main 0/29이며 DEV primary 표본은 0개다.** 다음 실험은 사용자의 명시적 재개 전 시작하지 않는다.

## 실행 계약과 범위

- 동결 source commit: `6730ecfa68a0628b83b0f9e5924fffcbf72a95ae`.
- immutable profile: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-controller-x86-v3.json`.
- profile SHA-256: `363d546937a229cbc3429fc589100c6d22e8cf6e34819dd4986d6476b810e33b`.
- policy SHA-256: `e7d220fcbde36be49059f726944aadd774e233e8733806b0e1c9a25cfeeab46c`.
- DEV campaign: `artifacts/fresh-evaluation-development-calibrated-2026-10-26/dev-v1`, case `dev-s1-a`.
- 운영·분석·보류 증거: `artifacts/fresh-evaluation-calibrated-2026-10-26`.

기존 [정상 보정 3회와 별도 validation 2회](../../s1-baseline-calibration-result-2026-10-26.md)는 완료한 정상25분이며 DEV·pilot·main으로 세지 않는다. 당시 source와 모든 frozen profile/raw/judgement를 보존했다. 정상 측정에 등록한 여섯 source 파일은 변경하지 않았다. 이번 controller 계약은 [controller architecture amendment](../../controller-platform-amendment-2026-10-26.md)에 따라 동일 E2 ID/type에서 실제 `uname -m=x86_64`를 확인하고 provider-selected Intel/AMD 모델을 별도 기록한다. 실제 controller는 AMD Rome, 두 N2 compute는 Intel Cascade Lake였다. 같은 architecture가 성능 동등성을 보장한다고 주장하지 않는다.

S1 SLO200ms, rate5, 100000rounds, warmup0, index0–299 고정 첫60초 baseline, 총1800초 stream, 주입 후 H1200초와 30초 여유, bin20초·bad≤.05·선형 p95·stable120초를 유지했다. V1의100ms/ratio1.5와 S2~S4는 실행하지 않았으며 설정을 변경하지 않았다. 코드·정책 변경은 DEV 전 완료했고 312개 테스트와 정적 shell 검증을 통과했다. 이후 운영용 artifact script와 결과 문서는 실험 source/policy 변경이 아니다.

## 두 attempt의 독립 결과

| attempt | 유효성 | 안전 | 회복 | cleanup | 해석 |
|---|---|---|---|---|---|
| 01 | false | false 출력 | null | true | H 이후 최종 host-stat의 IAP TLS 오류로 표준 증거 생성 중단 |
| 02 | true | true | true | true | 장애/영향 실현, 실제 같은 worker 재시작과 identity·clock·H 검증 통과 |

attempt-01은 고정 baseline과 실제 재시작·H 관측을 거쳤으나 최종 `completion-start` host-stat에서 compute02 SSH255 / `SSL: UNEXPECTED_EOF_WHILE_READING`가 발생했다. 실패 수집 경로가 원본 HTTP9000행과 run/decision/host 자료를 남겼지만, 예외가 `FreshS1.finish()`의 표준 `requests.jsonl`·`observations/contract.json` 생성 전에 전파됐다. 독립 판정의 false 값은 그 자료 부재를 포함한 결과이므로 실제 안전 침해나 장애 미실현을 관측했다고 해석하지 않는다. 원자료를 사후 보충해 통과로 바꾸지 않았다.

소유 정리가 모두 통과한 후 두 compute의 동일 read-only 조회가 성공했으며, source/profile·시각·누적 가동·비용과 max_attempts2를 검토해 추가 1회만 명시적으로 선택했다. 이유와 예산은 `dev-infra-retry-decision.json`, `post-dev-infra-retry-budget.json`, 실패 분석은 `dev-attempt-01-failure-analysis.md`다. 이 연결 재확인은 TLS EOF의 근본 원인 해결 증거가 아니다. 첫 실패를 재시도로 교체하거나 baseline 창·후보·SLO를 탐색하지 않았다.

## attempt-02에서 확인한 사실

- 고정 baseline300개가 모두 존재했다. 세 bin의 성공 p95는104.33/101.97/109.70ms, bad는1/1/0으로 200ms 진입 기준을 통과했다.
- 전체 stream9000행의 index0–8999가 중복·누락 없이 존재했다. completion 순서가 arrival 순서와 같다는 가정은 하지 않았다. H의 기대·관측 요청은 각각6000개, unobserved_seconds는0이었다.
- 10/27 00:18:24 KST에 주입 적용, 00:20:47에 A 조치 적용, 00:38:24에 H 종료를 기록했다. 주입 오프셋은 약167.4초로570초 제한 안이었다.
- 실제 조치1회와 Pod UID 교체를 확인했다. Node·Machine UID·Nova VM·compute02·application image가 유지됐고, 경쟁은 조치 후와 완료 시점에도 지속됐다. image ID는 `docker.io/library/python@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d`다.
- 주입 후180초 지점부터 stable120초 회복 기준을 충족했다. 이는20초 bin 기반 판정이며 정밀한 실제 회복 시각이나 인과 효과의 추정으로 해석하지 않는다. H 전체에서 요청 실패0, SLO 위반 비율 약2.27%, 성공 요청에 조건부인 scheduled latency p95 약182.55ms였다.
- clock 진단 round trip은 주입 전 약0.575초, H 종료 약0.617초였다. 동결된5초 bound를 통과했다. 이것을 회복 시각 ±5초 오차 보장으로 해석하지 않는다.

이 결과는 DEV 한 실행의 경로와 관측 기준 확인이다. M/P 대조군, V1, S2~S4 또는 본시험 효과·일반화를 검증한 것이 아니다. 자동 restart가 항상 효과적이라고 주장하지 않는다.

## 정리와 보류

attempt-02의 등록 cleanup은10/27 00:51:24 KST에 완료됐다. 추가 read-only audit에서 worker auto/1, 원래 cluster/MD UID, 소유 namespace 부재, trial taint 부재, MHC 원상태, trial Machine annotation 부재, 경쟁 VM/flavor 부재, QoS·Cinder volume·PV의 원래 empty 상태와 S2 egress 부재까지13개 검증이 통과했다. 증거는 `restoration-before-down-v2/summary.json`이다. 앞선 audit 초안은 조회 전에 ledger schema 참조 오류로 종료됐고, 불변 `case-contract.json`을 참조하도록 운영 script를 바로잡아 검증했다. frozen source나 실험 판정에는 영향이 없다.

`HOLD-NEXT-EXPERIMENTS.json`에 사용자 지시를 저장했고 미실행 operator driver도 이 파일이 있으면 시작 전에 거절하도록 했다. preparation/main campaign은 생성하지 않았다. 해당 경계는 이후 재개 여부와 독립적으로 보존한다.

## 최종 확인

- 10/27 00:57:35 KST에 정상 down을 시작했고01:03:19에 native 상태가 stopped가 됐다.01:03:58의 별도 GCP readback에서 controller·compute01·compute02 모두 **TERMINATED**를 확인했다. down은1800초 전체 상한 안에 끝났다.
- 기존 persistent disk3개 합계320GiB의 이름·용량과 snapshot14개의 ID·이름이 기존 preflight 목록과 일치했다. 삭제하거나 새 bed를 만들지 않았다. 증거는 `final-cloud-readback/summary.json`과 원본 목록이다.
- 마지막 bed session은01:03:20에 닫혔다. 과거 준비·실패·정리까지 합친 누적 가동은16179.84초, 약4시간29분40초다.01:03:58 기준 원장 산식 추정은 약32544원이며 reserve20000원은 한 번만 포함한다. 실시간 Billing·실제 청구액이나 실제 크레딧 잔액으로 표시하지 않는다. 정지 후 저장 자원의 달력 비용 산식도 포함한 시점별 추정이다.
- DEV2 attempts(유효1/infra-invalid1), preparation0/8, main0/29, primary0을 유지한다. 기존 정상 보정25분·과거 DEV·합성·retry를 본시험 n에 넣지 않는다.
- 결과 문서만 후속 커밋하며 동결 source/profile/raw/judgement는 그대로다. 재개 시 현재 환경·시각·누적 원장·미실행 범위와 기존 hard-stop을 다시 확인해야 한다. 사용자 지시 전에는 추가 attempt·preparation·main에 진입하지 않는다.

최종 재검증은 동결 source/profile/문서/증거 hash, 독립 report의 두 attempt 판정, 실제 재시작 identity·전체 arrival index와 H·clock, 등록 cleanup과13개 추가 복원 점검, GCP 정지·원장 종료·보존 자원 비교 및 문서 diff 검사로 수행했다.312개 테스트는 DEV 전 source 검증 결과이며 결과 문서 변경 때문에 반복 실행하지 않았다. 이 문서의 결과를 본시험 완료나 대조군 대비 효과 검증으로 해석하지 않는다.
