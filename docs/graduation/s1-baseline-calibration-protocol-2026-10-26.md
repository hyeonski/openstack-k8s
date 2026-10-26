# S1 정상 baseline 보정 사전 등록 v1

2026-10-26. 새 정상 자료 수집 전에 등록한다. 기존 200ms에서 실패한 DEV 두 attempt(600개 요청, 모두 HTTP 성공)는 설계 참고이며 calibration·validation·primary에 재사용하지 않는다. 외부 SLA가 없는 합성 PBKDF2 workload의 실험 목표다. 장애군의 실패나 자동화군의 성공을 목표로 값을 고르지 않는다.

## 범위와 순서

기존 bed `cloud-gcp-amd64-greenfield`, project `openstack-k8s`, zone `asia-northeast3-a`를 그대로 사용한다. source compute02 n2-standard-4, target/control-plane compute01 n2-standard-8, controller e2-standard-4다. 전용 실행기는 fixture 준비, 정상 HTTP Job, 읽기 관측, ownership cleanup, down만 수행한다. 경쟁 VM·주입·복구·A 재시작·DEV·preparation·main 실행은 없다. calibration/validation artifact는 primary root 밖에 두며 campaign schema가 아니다.

측정 계획은 calibration 3회×300초와 후보 동결 뒤 validation 2회×300초다. 선택적 원인 분리 진단은 최대 2회×120초까지이나 v1에서는 추가 요청을 만들지 않고 본 stream의 관측을 사용한다(진단 0회). 실패한 측정은 보존하고 임의 추가 재시도·관측 축소·validation 재튜닝을 하지 않는다.

매 회 namespace·HTTP Deployment·Service·ConfigMap을 소유권 검증 후 제거/재생성하고 source worker에 고정한다. worker 2개와 VM은 같은 host session에서 유지한다. 준비 시작→rollout Ready→identity/배치·관측 준비→새 Job의 예정 index 0이 연구 stream 시작이다. warmup=0이며 정상화될 때까지 기다리는 절차는 없다. 관측기 준비 시간은 기록한다. 이 반복은 독립된 환경 5개가 아니다. 이후 DEV도 같은 fixture 재생성·source 고정·warmup0을 사용한다.

부하 URL `http://http.graduation-s1.svc.cluster.local:8080/work?rounds=100000`, workload control-plane Pod, rate5/s, timeout/deadline5초, max inflight50, rounds100000을 유지한다. DNS 우회·healthz 대체 측정은 하지 않는다. 기존 정책의 90초 대기 후 마지막60초 창은 정책 진단의 상대 baseline이다. 연구 진입 baseline은 index0–299의 고정 첫60초다. 두 창을 혼동하지 않는다. 본시험 총1800초·주입 뒤 H1200+30초 확보 조건은 변경하지 않는다.

## 후보 선정 규칙

각 calibration의 index0–1499를 100개씩 나눈 15개 bin, 총45개의 성공·정확·예정→완료 지연의 선형보간 p95를 사용한다. 분위수는 rank=(n−1)×0.95, 양옆 값의 선형보간이다. 선정 통계 T는 45개 bin p95의 최대값이다. 후보는 `max(200, 10 * ceil(1.20 * T / 10))` ms다. 전 구간의 index·clock·deadline 계약이 완전하고 HTTP/정확성/deadline 실패 및 generator rejection이 0이어야 선정 가능하다. 후보로도 모든 calibration bin의 p95와 bad≤5/100이 만족되어야 한다.

200ms 유지 조건은 위 산식이 200ms이고 세 run 모두 200ms에서 완전·healthy인 경우다. 상한은 500ms이며 이를 넘으면 보정 no-go다. 500ms로 잘라 통과시키지 않는다. 20%는 짧은 정상 반복의 변동에 대한 고정 공학적 여유이며 확률적 보장이나 신뢰구간이 아니다. 상한500ms는 원래 목표의2.5배·deadline의10%로, 그 이상은 목표 완화보다 workload/환경 설계 재검토가 필요하다는 연구상 한계다. 높은 목표일수록 200ms와 새 값 사이의 작은 성능 저하를 정상으로 세는 대가가 있다.

SLO 외에는 bin20초, bad.05, 선형보간p95, index0 첫60초, 최종 안정120초를 유지한다. 후보는 진입 gate와 모든 S1 P/M/A primary·회복 판정에 같은 값으로 적용한다. S2~S4·V1의100ms·정책 상대배율1.5는 변경하지 않는다.

## 동결과 별도 검증

calibration3회를 마치면 후보값·45개 bin·근거·profile 전체·판정/실행 source SHA와 복사본·이 문서 SHA를 candidate-freeze.json 및 별도 candidate-profile.json에 고정한다. validation은 두 파일과 최초 source/config/doc hash를 검사한 뒤에만 시작한다. validation 실패로 후보를 다시 고르지 않는다.

각 validation run의 첫 index0–299의 3개20초 bin이 모두 완전·healthy여야 **진입 baseline 검증 통과**다. 두 run에서 각각 충족해야 한다. 별도로 각 run 전체15개 bin 모두 완전·healthy, HTTP/정확성/deadline 실패·누락·중복·generator rejection0, clock/배치/Pod·image identity 보존, final120초 정상이어야 **지속 정상 검증 통과**다. 2/2 run의 두 조건을 모두 만족할 때만 새 profile을 confirmed로 물질화한다. baseline만 통과하면 지속 안정으로 주장하지 않는다. 재악화는 처음 healthy 뒤 unhealthy가 된 bin 목록으로 공개한다. 모든 bin의 bad비율·p95 및 기존200ms 판정을 병기한다.

## 관측·한계

동일 urllib HTTP 경로에 HTTPConnection.connect 경과(DNS+TCP 합계), 응답 headers까지의 경과, 전체 HTTP 실행·예정→완료·queue를 기록한다. Server-Timing의 handler;dur는 Handler 진입→응답 구성 직전이며 스레드 dispatch 전 대기·socket write를 포함하지 않는다. client HTTP를 서버시간이라고 부르지 않는다. DNS와 TCP의 개별 분해는 불가하고 연결 합계로 표시한다. 서버 헤더/계측 코드가 추가되므로 기존 DEV와 다른 snapshot이다. 정상 부하5회는 동일 계측을 사용한다.

source/target compute와 HTTP Pod 내부(guest CPU·steal/PSI·cgroup cpu.stat)의 /proc 카운터를1초 간격 읽는다. 원격 시작/종료 UTC·monotonic과 실제 간격·누락을 남긴다. Pod /proc은 guest VM 관측이며 물리 host가 아니다. 서버 handler에는 스케줄링 지연도 포함된다. 1초 평균으로 subsecond burst 원인을 확정하지 않으며 동시성은 인과 증명이 아니다. 관측 자체의 Python 프로세스·SSH/kubectl exec 오버헤드는 존재하고 모든5회에 동일 적용한다. 과거90초 평균과 새1초 자료는 같은 해상도로 취급하지 않는다.

## 운영 예산과 중단

기동 요청부터7200초를 전체 예산으로 등록하고 cleanup1800+down/readback1800초를 예약한다. 따라서 준비·관측·동결은 최초3600초 안에 마쳐야 한다. 관측1500초 외에 ensure/초기준비 예상900초, 매 회 reset/관측/증거와 동결 합계900초, 여유300초를 둔다. 실제 지연으로 남은 모든 예정 관측과 준비가3600초 내에 들어오지 않으면 새 측정을 시작하지 않고 부분 결과를 인계한다. 기존 whole-phase 상한보다 이 deadline이 우선한다. 정리가 길어지면 신규작업을 멈추고 안전 정리를 끝내며 초과 원인을 기록한다.

전체10/29 00:00 KST 마감·48h/44h bed 가동 gate·신규146234원/정리40000원·기존 가동 원장을 유지한다. 사용자 제공186234원(10/26 17:10 KST)은 실시간 잔액이 아니다. 원장 estimate의20000원 reserve는 한 번만 적용하고 실제 청구액처럼 잔액에서 중복 차감하지 않는다. 디스크 보관료는 정지 중에도 calendar day로 센다. 종료 시 worker auto/1·소유 namespace/임시자원 부재 후 기존 down과3대 TERMINATED readback을 남긴다. 기존320GiB 디스크·snapshot은 보존한다.
