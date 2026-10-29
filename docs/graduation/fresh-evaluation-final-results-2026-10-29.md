# 계측 수정 후 신선 평가 최종 결과 — 2026-10-29

**평가·분석·소유 정리·인프라 종료를 완료한 결과다.**

## 분석 집합과 판정 보존

원래 main29의 strict first-attempt는 유효 21·무효 8다. 보충은 별도 11건이며 유효 8·무효 3다. 준비실험은 10 attempt(유효8·무효2)이며 main 분모에 넣지 않는다. 원래 무효를 보충으로 교체하거나 29/29 유효로 발표하지 않는다.

DEV·calibration·표본 외 qualification은 main/보충 표에서 제외한다. 그 준비·검증·대기 시간은 공유 운영 원장에 포함한다. 원본 main에는 S1 V1 정상 서비스 보류 검증 2건이 포함된다. 두 건의 `recovered=true`는 주입 후 서비스가 계속 정상이라는 계산 결과이며 장애 복구 성공 2건으로 해석하지 않는다. 조건이 다른 시나리오를 합친 일반 복구 성공률은 제시하지 않는다. 유효 미복구 결과는 그대로 보존하며 재실행하지 않았다.

| 집합 | attempt | 유효 | 무효 | 해석 |
|---|---|---|---|---|
| 원래 main first-attempt | 29 | 21 | 8 | 계획 분모29 유지 |
| preparation | 10 | 8 | 2 | 별도 준비 검증; 유효8 재사용 |
| 별도 보충 전체 | 11 | 8 | 3 | 운영 무효 포함 전건 공개 |

## 고정 테스트베드

기존 GCP 호스트3대 위 중첩 OpenStack/Kubernetes(v1.35.7) 환경이다. controller는 e2-standard-4, compute01은 n2-standard-8, compute02는 n2-standard-4다. workload control plane은 compute01에, 등록 source compute는 compute02·target은 compute01에 고정했다. 두 compute의 자원 구성이 다르므로 S1 재배치 결과를 동질 하드웨어에서의 보편적 알고리즘 효과로 일반화하지 않는다. 실제 VM ID·Cluster/MD/CA UID·runtime image binding은 원래 환경 증거와 각 attempt에 보존했다. 관측은 Mac의 로컬 API 터널을 사용했으며 그 시계·전송 실패를 서비스 실패와 분리한다.

## 측정 계약

기존 UTC 계약, 부하·H·SLO·안정창·요청 분모를 유지했다. 서비스 요청 재시도0, mutation blind resend0, raw 보간0이다. 운영 읽기 복구는 서비스 요청과 구별하여 기록했다. 연구 baseline은 등록 stream의 처음 60초이며 성공하는 창으로 이동하지 않았다. 회복은 H 끝까지 이어지는 최종 정상 tail의 시작이고 최소120초 정상 구간으로 확인한다. 미복구의 시간은 null이며 H로 대체하지 않는다.

| 시나리오 | H(s) | 요청률 | H 분모 | SLO(ms) | 주요 구분 |
|---|---|---|---|---|---|
| S1 | 1200 | 5/s | 6000 | 200 | 전체 부하1800초; M 무조치, A 동일 worker 1회 재시작, P 교차 계층 배치 |
| S2 | 1200 | 2/s | 2400 | 500 | API 지연/오류와 업로더 처리량을 함께 평가 |
| S3 | 900 | 1/s | 900 | 2000 | M3600/P3600; read 가용성·seed·fencing 순서 |
| S4 | 1200 | 1/s | 1200 | 2000 | off/on; 서비스와 usable capacity 분리 |

정리 단계의 worker 복원·fault 해제·agent 재시작은 H 내 회복으로 소급하지 않는다. 사건 시각은 최초 독립 확인 시각이며, 관측하지 못한 내부 시각은 unknown으로 유지한다. S1/S2의 원격 clock alignment bound는5초, 분석 bin은20초다. 정상 bin은 예정 도착 수 완전성, 성공 요청 p95 및 SLO 위반 비율≤5%를 함께 검사한다. 지연 p95는 성공·정확·deadline 이내 요청에 조건부인 보조지표다. 요청 실패율과 SLO 위반율은 다른 값이며 함께 제시한다. S1 V1의 SLO100ms 등 별도 조건은 일반 S1 표와 비교하지 않는다.

## 원래 main의 조건별 결과

아래 수치는 유효한 원래 first-attempt만 사용한 실행별 지표 중앙값이다. `회복/유효`는 S4에서 서비스와 용량의 결합 판정이다. 서비스 tail 시간은 유한한 값만 집계하므로 미복구 수를 반드시 함께 읽어야 한다.

| 조건 | 유효/시도 | 회복/유효 | 실패율(%) | SLO위반율(%) | 조건부p95(ms) | 서비스 tail(s) |
|---|---|---|---|---|---|---|
| S1/A | 2/3 | 2/2 | 0.000 | 2.625 | 188.7 | 990 [n=2] |
| S1/M | 3/3 | 2/3 | 0.000 | 2.733 | 186.6 | 490 [n=2] |
| S1/P | 3/3 | 3/3 | 0.000 | 0.650 | 155.3 | 140 [n=3] |
| S2/M | 3/3 | 3/3 | 0.000 | 1.917 | 447.6 | 240 [n=3] |
| S2/P | 2/3 | 2/2 | 0.000 | 0.250 | 355.2 | 0 [n=2] |
| S3/M3600 | 1/3 | 0/1 | 100.000 | 100.000 | — | — [n=0] |
| S3/P3600 | 2/3 | 2/2 | 12.556 | 12.667 | 611.2 | 290 [n=2] |
| S4/off | 1/3 | 0/1 | 1.083 | 1.083 | 294.6 | 20 [n=1] |
| S4/on | 2/3 | 2/2 | 0.542 | 0.542 | 315.8 | 20 [n=2] |

S1 V1은 원래 2/2 유효이고 모두 `held`다. 인프라 경합이 있어도 등록 서비스 영향 조건이 없을 때 조치하지 않은 검증이다.

S1에서는 P의 SLO 위반율과 조건부 p95가 M/A보다 낮았지만, A의 유효2건과 M의 유효3건 중2건도 H 내 서비스 정상 tail을 얻었다. 따라서 동일 worker 재시작이나 무조치가 언제나 회복 불가능하다고 결론 내리지 않는다. P의 b03은 지속적인 SLO 영향이 성립하지 않았고 서비스 tail 시작0초였다. 이는 순간 복구를 뜻하지 않는다.

S2에서 업로드 goodput 하한의 실행별 중앙값은 M 1.819 MB/s(n=3), P 0.626 MB/s(n=2)였다. P의 API 지연 개선에는 업로드 처리량 감소라는 절충이 있다. 두 arm의 API 요청 실패율 중앙값은 모두0%다. P의 원래 유효2건은 지속적인 SLO 영향이 성립하지 않아 tail 시작0초였으므로, 이를 장애 복구 시간 단축의 독립 증거로 세지 않는다.

S3 원래 주분석은 M3600 유효1건(미복구), P3600 유효2건(회복)뿐이다. P의 seed 보존과 순서 검사는 이 유효 자료에서 확인됐다. 이는 설정된3600초 타이머와900초 H에서의 결과이며, 모든 Kubernetes 설정에 대한 우월성이나 ACK-loss·쓰기 내구성 보장은 아니다.

### 사전 paired contrast의 실제 가용 수

| 시나리오 | contrast | 유효fault pair | block | 서비스 tail 차이(s; 유한값만) |
|---|---|---|---|---|
| S1 | P − A | 2/3 | b01, b03 | -910 [n=2] |
| S1 | P − M | 3/3 | b01, b02, b03 | -410 [n=2] |
| S2 | P − M | 2/3 | b01, b02 | -530 [n=2] |
| S3 | P3600 − M3600 | 1/3 | b01 | — |
| S4 | on − off | 1/3 | b03 | 0 [n=1] |

시간 차이는 두 arm 모두 유한한 서비스 tail 시간이 있을 때만 계산했다. 미복구를 H로 치환하지 않았다. 특히 P의0초는 지속적 SLO 영향 부재를 포함하므로 표의 차이를 곧바로 복구 알고리즘 속도 차이로 해석하지 않는다. 작은 표본·불완전 block·운영 버전 변경 때문에 일반 신뢰도나 유의성 주장은 하지 않는다.

### S4: 서비스 회복과 용량 복원

| case | 집합 | 서비스회복 | 서비스tail(s) | 용량복원 | 용량tail(s) | 결합회복 |
|---|---|---|---|---|---|---|
| s4-b01-on | 원래 | 예 | 20 | 예 | 216.9 | 예 |
| s4-b03-off | 원래 | 예 | 20 | 아니오 | — | 아니오 |
| s4-b03-on | 원래 | 예 | 20 | 예 | 207.4 | 예 |
| s4-b01-off-supplement01 | 보충 | 예 | 20 | 아니오 | — | 아니오 |
| s4-b02-off-supplement01 | 보충 | 예 | 20 | 아니오 | — | 아니오 |
| s4-b02-on-supplement01 | 보충 | 예 | 20 | 예 | 214.9 | 예 |

off에서도 서비스는 남은 worker를 통해 회복했지만 H 내 usable capacity 복원은 없었다. on의 용량 복원은 기존 MHC/CAPI/CAPO 경로다. 이 결과를 새 복구 알고리즘의 기여로 발표하지 않는다. 표의 서비스20초를 off의 결합 복구 시간으로 사용하지 않는다.

## 보충 전건 — 원본 대체 금지

운영상 무효로 끝난 원본의 보충을 별도 회차·별도 ID·새 source/freeze로 수행했다. 보충 중 무효3건도 제거하지 않았다. 현재 source의 마지막 회차는 기존 `s3-b02-m3600`에 대한 supplement03이다. 모든 결과를 원래 main29에 끼워 넣어 균형 표본처럼 비교하지 않는다.

| case | 유효 | fault | impact | 회복 | 정리 | 실패율(%) | SLO위반율(%) | cohort/source |
|---|---|---|---|---|---|---|---|---|
| s1-b02-a-supplement01 | 아니오 | 아니오 | 아니오 | 미확인 | 예 | — | — | bed-inventory-v8 / b46b0f80 |
| s1-b02-a-supplement02 | 예 | 예 | 예 | 예 | 예 | 0.000 | 3.483 | bed-s3-capture-v10 / db82c5ba |
| s2-b03-p-supplement01 | 예 | 예 | 예 | 예 | 예 | 0.000 | 0.500 | bed-s1-read-v9 / ccd8cb85 |
| s3-b02-m3600-supplement01 | 아니오 | 아니오 | 아니오 | 미확인 | 예 | — | — | bed-s1-read-v9 / ccd8cb85 |
| s3-b02-m3600-supplement02 | 아니오 | 아니오 | 아니오 | 미확인 | 예 | — | — | bed-s3-capture-v10 / db82c5ba |
| s3-b02-m3600-supplement03 | 예 | 예 | 예 | 아니오 | 예 | 100.000 | 100.000 | bed-dns-readiness-v11 / 647cf078 |
| s3-b03-m3600-supplement01 | 예 | 예 | 예 | 아니오 | 예 | 100.000 | 100.000 | bed-s3-capture-v10 / db82c5ba |
| s3-b03-p3600-supplement01 | 예 | 예 | 예 | 예 | 예 | 11.333 | 11.333 | bed-s3-capture-v10 / db82c5ba |
| s4-b01-off-supplement01 | 예 | 예 | 예 | 아니오 | 예 | 1.250 | 1.250 | bed-s3-capture-v10 / db82c5ba |
| s4-b02-off-supplement01 | 예 | 예 | 예 | 아니오 | 예 | 0.917 | 0.917 | bed-s3-capture-v10 / db82c5ba |
| s4-b02-on-supplement01 | 예 | 예 | 예 | 예 | 예 | 0.833 | 0.833 | bed-s3-capture-v10 / db82c5ba |

유효 보충의 미복구는 유효한 관측 결과다. 이를 성공시키기 위한 반복은 하지 않았다. 운영상 무효 뒤 별도 회차가 있다는 사실과 그 선택 규칙을 공개하며, 보충 유효 결과만 선택해 전체 운영 성공률로 발표하지 않는다.

### 무효 원본별 보충 이력

| 무효 원본 | 별도 회차 | 유효 보충 | 무효 보충 |
|---|---|---|---|
| s1-b02-a | s1-b02-a-supplement01, s1-b02-a-supplement02 | 1 | 1 |
| s2-b03-p | s2-b03-p-supplement01 | 1 | 0 |
| s3-b02-m3600 | s3-b02-m3600-supplement01, s3-b02-m3600-supplement02, s3-b02-m3600-supplement03 | 1 | 2 |
| s3-b03-m3600 | s3-b03-m3600-supplement01 | 1 | 0 |
| s3-b03-p3600 | s3-b03-p3600-supplement01 | 1 | 0 |
| s4-b01-off | s4-b01-off-supplement01 | 1 | 0 |
| s4-b02-off | s4-b02-off-supplement01 | 1 | 0 |
| s4-b02-on | s4-b02-on-supplement01 | 1 | 0 |

각 원본의 첫 strict invalid는 유지한다. 유효 보충을 얻었다는 것은 별도 관측의 완료이며 원래 main의 성공 승격이 아니다.

## 전건 동일 규칙의 사후 측정완전성 감사

과거에 없던 measurement seal을 소급 생성하지 않았다. 모든 attempt에 같은 규칙으로 identity·원자료 해시·baseline·H·요청 완전성·시각·시나리오 자료를 검사한다. cleanup 완결과 phase 후반 종료는 분리하며, 모든 execution error가 독립 관측된 H 종료 뒤에 있을 때만 실행 중단 표시를 완전성 판단에서 분리한다. 다른 결측은 유지한다. 이 감사는 strict 판정이나 안전·장애 실현 판정을 승격하지 않는다.

| 집합 | 감사attempt | 측정완전성입증 | 정리입증 |
|---|---|---|---|
| 원래 main | 29 | 23 | 29 |
| 보충 | 11 | 8 | 11 |
| pilot | 9 | 7 | 9 |
| smoke | 1 | 1 | 1 |

원래 S3-b02-M3600과 S4-b02-on은 사후 측정완전성을 입증했지만 strict invalid를 유지한다. 원래 시계 무효 자료는 monotonic 수치로 구제하지 않는다. 전체 감사와 사유는 `posthoc-measurement-audit.json`에 있다.

### 원래 strict 무효8건의 보존

| 원래 case | 저장된 strict 결측 사유 | 사후 측정완전성 | 정리 |
|---|---|---|---|
| s1-b02-a | execution_interrupted, request_arrivals_incomplete, s1_total_request_indexes, scenario_evidence_missing:'service_after' | 아니오 | 예 |
| s4-b01-off | baseline_clock_disagreement, baseline_unhealthy, execution_interrupted, horizon_missing, phase_sequence_incomplete, scenario_evidence_missing:'mhc_before', semantic_event_missing_or_duplicate | 아니오 | 예 |
| s4-b02-on | execution_interrupted | 예 | 예 |
| s3-b03-p3600 | clock_step_between_requests | 아니오 | 예 |
| s3-b02-m3600 | execution_interrupted | 예 | 예 |
| s3-b03-m3600 | baseline_clock_origin_invalid, baseline_first_arrivals_incomplete_or_duplicate, baseline_unhealthy, execution_interrupted, horizon_missing, phase_sequence_incomplete, scenario_evidence_missing:'statefulset', semantic_event_missing_or_duplicate | 아니오 | 예 |
| s4-b02-off | baseline_clock_origin_invalid, baseline_first_arrivals_incomplete_or_duplicate, baseline_unhealthy, execution_interrupted, horizon_missing, phase_sequence_incomplete, scenario_evidence_missing:'mhc_before', semantic_event_missing_or_duplicate | 아니오 | 예 |
| s2-b03-p | judgement_error:UnboundLocalError:cannot access local variable 'start' where it is not associated with a value | 아니오 | 예 |

준비 실패에서 baseline 자료가 생성되지 않아 나온 clock-origin/baseline 사유와 실제 clock step 증거는 구분한다. 결측 flag만으로 시계 보정이 다시 발생했다고 판정하지 않는다.

## 이 자료가 뒷받침하는 기여 범위

S1은 OpenStack의 배치·host 정보를 이용해 Kubernetes Deployment를 재배치한 사례다. OpenStack actuator가 반드시 필요하다는 증거는 아니다. S2는 구현된 P의 API 품질과 uploader 처리량 절충을 보여주며 모든 infrastructure-only 정책보다 우월함을 입증하지 않는다. S3는 Node NotReady와 기존 VM/DB 프로세스 생존을 구별하고 fencing→out-of-service→재연결 순서를 지킨 자료다. S4는 기존 계층의 복구가 작동하는 대조다. K/I의 모든 대안이나 사람 런북을 직접 비교한 실험은 없으므로, 구현된 패키지의 관측 효과와 각 요소의 일반적 필수성을 구분한다.

## 운영 변경·결측과 검증 범위

원래 무효8건은 측정 대상 서비스의 미복구8건이 아니다. 연결/자료 회수, 시계 보정, 준비·정리 경로 실패가 섞여 있다. 원래 S2-b03-P의 분석기 예외는 H 누락 guard 수정으로 구체적인 결측 사유를 얻었지만 계속 무효다. 기존 유효 결과의 판정·지표는 동일하다.

운영 변경은 기존 등록 읽기 경로의 기본 총3회/20초 명령/90초 작업 예산 및 identity 검사, durable capture, 측정봉인과 cleanup 분리, macOS 시각 보호, 복합 inventory의 개별20초/전체90초 구분, S1 canonical refused 재연결과 `/dev/shm` CPU capture, S3 rule-check stdout 제거와 parse 전 raw 보존, 준비 probe 전 Neutron SG 캐시 정합 검사다. 정책 판단에 쓰이는 읽기 지연과 agent 복구가 실행 시간·환경에 영향을 줄 수 있으므로 운영 보완이 무조건 측정 중립이라고 가정하지 않는다.

SG 캐시 불일치와 차단 경로는 확인했지만 최초 RPC 누락·이벤트 순서 문제의 내부 원인은 확정하지 않았다. 새 SG hook은 준비 probe 직전에만 별도 전체450초/호출45초 예산을 사용하며 기존 준비·정리 phase를 늘리지 않는다. 기존343개 원격 정책은 불변이고 새 등록부는348개다. 실제 node/Nova/port로 묶은 캐시 불일치에만 기존 agent를1회 재시작하고 durable intent journal을 남긴다. 응답이 불명확하면 재전송하지 않으며 측정 clock/token 활성 중에는 차단한다. 예산 추정의 추가600초는 이 준비 여유이며 H 연장이 아니다.

v7의 약30분 qualification과 실제 reboot 복원은 당시 소스의 증거다. H 전용 retry 경계는 최종 오프라인 시험으로 검증했으며 해당 분기를 live 시험했다고 주장하지 않는다. 이후 source253의 실제 준비 lifecycle, source255의 동일 read-only-root CPU/터널 경로, source259의 실제 S3 capture reader, source263의 실제 stale SG hook·원래 DNS probe·worker1→2→1 정합을 각각 검증했다. 기존 실패 응답이 없던 S3 JSON 오류는 같은 코드 경로의 실제 재현이며 과거 응답을 복구한 것이 아니다.

최신 fresh 회귀221개는 통과했다. 별도 legacy worker/lifecycle50개 중2개 오류는 수정 전 v10 동결 소스에서도 같은 예외로 재현됐다. 이를 이번 변경의 새 회귀로 세지 않되 미해결 테스트 한계로 공개한다. 첫 검증 실패·cleanup 지연·연산자 스크립트 오류 기록도 삭제하지 않았다.

| cohort | source | main | 보충 | 유효/전체 |
|---|---|---|---|---|
| bed-a | a909904d | 9 | 0 | 8/9 |
| bed-dns-readiness-v11 | 647cf078 | 0 | 1 | 1/1 |
| bed-four-supplement-v6 | 7b72f678 | 3 | 0 | 1/3 |
| bed-inventory-v8 | b46b0f80 | 2 | 1 | 2/3 |
| bed-judgement-closure-v3 | 694bd678 | 4 | 0 | 4/4 |
| bed-s1-read-v9 | ccd8cb85 | 0 | 2 | 1/2 |
| bed-s3-binding-v5 | 4708e662 | 1 | 0 | 0/1 |
| bed-s3-capture-v10 | db82c5ba | 0 | 7 | 6/7 |
| bed-ssh-read-v4 | f445b9ec | 2 | 0 | 0/2 |
| bed-stability-v7 | 3375f906 | 1 | 0 | 0/1 |
| bed-transport-v2 | c7804d9f | 7 | 0 | 6/7 |

고정 fixture·원래 main 조건별 n≤3(V1 n=2)의 기술적 사례 연구다. 사람 수행 비교, 일반 장애 신뢰도, 모든 인프라 단독 대응의 불가능성, ACK-loss 내구성은 검증하지 않았다. 여러 source·시각/전송 운영·환경 재기동과 무효 표본 선택이 있어 외적 타당성 및 결측 편향에 주의해야 한다.

## 원자료와 종료 증거

최초 보존 원본 10234개 파일 SHA 불변을 재확인했다. 각 attempt의 현재 파일 해시는 저장된 evidence manifest와 일치하며, invalid 원본·보충과 최초 실패 사본을 별도 보존했다. 이 보고서는 원자료를 고치지 않고 saved strict verdict와 별도 재계산을 사용한다.

동일 3개 GCP VM의 TERMINATED, 공유 원장의 종료, 소유 fixture 정리, 시각 원설정 복원 및 설치서비스 상태는 `final-closure.json`에 있다. 원장 종료: 2026-10-29T13:58:44.888809+09:00. 비용 추정은 실제 청구서가 아니며 최신 표시잔액120972원 이후 경과·미래 작업만 계산했고 과거 원장을 다시 차감하지 않았다. 정리40000원/기타20000원/미확인12시간 청구 지연32000원 가정을 유지했다. 정지된 VM의 부팅 디스크 등 잔존 리소스는 유지되며 해당 비용은 기타 예비액에서 별도로 관리해야 한다. 최종 청구 잔액을 새로 관측하지 않았으므로 미래 비용을 0원으로 간주하지 않는다.

| 호스트 | ID | 최종 상태 |
|---|---|---|
| osk8s-compute01 | 4452491138774596731 | TERMINATED |
| osk8s-compute02 | 190540613588614267 | TERMINATED |
| osk8s-controller | 8689617440184466555 | TERMINATED |

macOS 네트워크 시각 사용 원설정 On을 normal_release의 root readback으로 복원했다. 서버 설정은 time.asia.apple.com으로 유지되며 /etc/ntp.conf에서도 확인했다. clock guard LaunchDaemon과 설치 서비스는 제거하지 않고 running 상태로 유지했으며 활성 lease는 없다. read-only postboot keeper는 종료했고 실행 lock은 비어 있다.

| 보고 이후 비용 추정 | 원 |
|---|---|
| 표시잔액 | 120972 |
| 표시 보고 이후 경과 상한률 추정 | 16704.7 |
| 미확인12시간 가정 | 32000.0 |
| 정리 예비액 | 40000 |
| 기타 예비액 | 20000 |
| 위 항목 차감 후 추정 여유 | 12267.3 |

증거 루트: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/`. `final-analysis/summary.json`, `primary-first-attempts.json`, `supplemental.json`, `posthoc-measurement-audit.json`, `primary-cases.csv`, `supplemental-cases.csv`를 함께 보관한다. source263 및 전환 승인은 `dns-probe-investigation-v11/go-review.json`과 `transition-authorization.json`에 있다.

### 파일 링크

- [집계·paired contrast](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/summary.json)
- [원래 main 전건](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/primary-first-attempts.json)
- [보충 전건](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/supplemental.json)
- [무효 원본별 보충 이력](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/supplemental-origin-coverage.json)
- [동일규칙 사후감사](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/posthoc-measurement-audit.json)
- [main CSV](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/primary-cases.csv)
- [보충 CSV](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-analysis/supplemental-cases.csv)
- [최종 종료 증거](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-closure.json)
- [잔존 디스크와 시각 서버 확인](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-readiness-execution-2026-10-29/final-operations/retained-resources-and-clock-server.json)
- [v11 GO](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-probe-investigation-v11/go-review.json)
- [기존 테스트 오류 비교](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-probe-investigation-v11/related-tests-baseline.json)
