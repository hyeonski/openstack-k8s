# 원격 자료 수집과 실행 시간 재검토 — 2026-10-27

사용자의 새 세션 재개 승인은 과거 HOLD를 해제한다. 과거 HOLD와 DEV 원자료는 보존하며, 이번 승인과 고정 시계는 `artifacts/fresh-evaluation-24h-2026-10-27/resume-authorization.json`에 기록했다. 기준은 10/27 01:10:19 KST, 종료 목표는 **10/28 01:10:19 KST**다. 현재는 preparation 0/8, main 0/29다. 새 기한 결정을 받기 전 이보다 늦은 종료를 허용하지 않는다.

## 수집 계약

새 source는 앞으로의 모든 S1 arm에 같은 수집 경로를 적용한다. compute host counter/PSI의 산식·조건과 completion의 필수성은 유지한다. phase별 host 조회를 한 번의 원격 telemetry snapshot 생성과 그 파일의 다운로드로 나눈다. 기존 counter·PSI·memory 필드와 원격 UTC를 유지한다. 경로는 `/var/lib/openstack-k8s-graduation/fresh-evidence/<attempt 경로 SHA 앞24자>/<host>-<순번>.json`이다. telemetry 파일은 기존 디스크에 보존되며 새 VM·디스크를 만들지 않는다.

- 최초 생성 명령은 최대30초, **1회만** 실행한다. 응답 유실은 그 동일 파일의 조회로 확인한다. snapshot이 없으면 새 과거 표본을 만들지 않는다.
- 다운로드는 read-only `cat`으로 최대3회, 회당30초 이하·누적90초 이하로 제한한다. 호출 전체는 최초 생성30초+다운로드90초 이내이고 바깥 adapter/phase deadline도 계속 적용된다. sleep으로 예산을 늘리지 않는다.
- snapshot 원격 timestamp는 요청 UTC에서 −5초부터 +30초 범위여야 한다. 이는 기존5초 clock 진단을 대신하거나 ±5초 정확도를 보장하지 않는다. 원격 관측 시각과 요청·종료·오류·각 다운로드 시도를 보존한다. 최종30초 counter 간격은 기존 실행기대로 유지한다. 늦게 다운로드한 파일도 원래 timestamp만 사용한다.
- completion-start/end 중 하나라도 없거나 timestamp 조건을 벗어나면 필수 completion 증거가 없는 것이다. 그 결과를 정상·보조 자료로 재분류하지 않는다. 실행 오류와 결측은 기존 독립 판정에서 유효성을 막는다.
- 기존 S1 runner의 failure collector가 저장한 HTTP·결정 로그를 `finally`에서 표준 경로로 복사한다. `fresh_attempt`가 이번 시도 경로와 정확히 같을 때만 복사한다. 부분 contract에는 `collection_incomplete`와 오류를 남긴다. 원래 예외는 계속 전파되고 결측 필드를 추정하지 않는다.
- 기존 Job 로그 조회의 반환값을 추가 원격 조회 없이 atomic checkpoint/fsync로 보존한다. 실패 시 원본 HTTP가 없으면 이번 시도 checkpoint를 부분 requests로 남기되 실행 오류·결측 판정을 유지한다. checkpoint가 전체1800초 또는 H의 완전한 관측을 증명한다고 간주하지 않는다.

S2의 원격 stream/진행도 파일에도 같은 제한 다운로드와 원격 source manifest를 적용한다. 정책 조회에서 얻은 요청 파일은 별도 checkpoint에 보존하고, 최종 H의 완전한 요청 파일을 대신하지 않는다. 기존 remote probe 종료·cleanup·QoS 조치를 읽기 재시도로 감싸지 않는다.

`bash evaluation/fresh-collect.sh --attempt <원시도> --output <새 별도 디렉터리>`는 원시도의 `remote-files.jsonl`에 등록한 파일만 재다운로드한다. 기존 환경 override를 사용해야 하며, 호스트 기동·장애·probe·정책 조치는 수행하지 않는다. output은 기존 시도 바깥의 새 경로여야 한다. 원시도의 sealed evidence·판정·표본 수는 수정하지 않으며 재수집으로 과거 무효를 통과로 바꾸지 않는다. 호스트가 정지됐으면 새 기동 없이 자료를 읽을 수 없다는 한계는 그대로다.

## 시나리오별 증거와 실패 의미

| 시나리오 | 필수 증거와 내구 위치 | 최종 수집 실패 시 |
|---|---|---|
| S1 | Pod HTTP stream은 Job/원본 `http.jsonl`, 사건은 fsync events, host phase snapshot은 원격 파일과 local host-snapshots, 서비스·Node·VM·경쟁자 identity는 raw와 contract | 원본 보존·부분 표준화; completion host 누락은 invalid 유지. Job 삭제 전 failure collector도 유지 |
| S2 | 원격 fresh-api/progress 파일, 결정 JSONL·정책 checkpoint, 초기/최종 port·QoS·이미지·고유 chunk 무결성 | 종료 중에도 다운로드 시도와 source 보존. 최종 필수 파일/contract 누락은 invalid; snapshot을 완전한 H로 간주하지 않음 |
| S3 | OpenLoopProbe 요청은 매행 fsync, 사건·DB/attachment snapshot은 매 반복 저장, seed/fence/최종 volume·VM은 contract/raw | 기존 요청·관측은 남음. seed 수집 실패는 기존 unknown, 확인된 불일치는 unsafe. 누락된 identity를 추정하지 않음 |
| S4 | OpenLoopProbe·사건 fsync, capacity snapshot을 매 반복 저장, MHC ownership과 target identity를 주입 전 저장 | 기존 자료 보존. 관측 간격15초와 stable120초 계약 유지. 마지막 필수 snapshot이 없으면 성공으로 채우지 않음 |

소유 cleanup 재개는 기존 `--fresh resume-cleanup --campaign ... --case ...`를 그대로 사용한다. VM stop/start·fencing·detach·정책 mutation의 응답 유실에 무조건 재실행을 추가하지 않았다. 원래 ownership/identity/readback 및 미완료 attempt 차단을 유지한다.

준비·cleanup에서는 기존 `TransportWatch`를 사용한다. local workload API listener가 없을 때만 기존 tunnel ensure를 최대2회 시도하고, VM 장애로 판정하거나 worker scale 명령을 반복하지 않는다. 기존 whole-phase deadline을 재시작하지 않는다. 감시기는 adapter 시작 전에 종료·join하므로 계측 중 tunnel 재연결 정책을 추가하지 않는다. cleanup의 S4 rescue/Ready 확인/MHC 복원 순서도 유지한다.

## 변경 영향과 완료 증거 재사용

| 경로 | 변경/유지 | 재사용 및 후속 확인 |
|---|---|---|
| app.py·loadgen.py·fresh_baseline.py·fresh_analysis.py·fresh_contract.py·fresh_calibration.py | 여섯 정상 측정 source SHA 유지 | 정상3회+별도validation2회 binding과 raw 재계산 통과. 새 정상 보정 반복 없음 |
| fresh_scenarios.py·fresh_collection.py | telemetry 저장/전송과 부분 증거 보존 | 정책 값·A 실제 patch·H·probe·판정 산식 유지. 오류 주입 단위검증, 예정 preparation에서 실제 수집 확인 |
| fresh_live.py | 준비/cleanup 동안 제한 transport watcher | worker auto/1→fixed/2→auto/1 유지. 기존 cleanup 재개·ownership 검증 사용 |
| fresh_campaign.py | 새 collection 모듈을 policy manifest에 포함 | 새 source/policy freeze 필요. 예전 hash를 현재 hash로 표시하지 않음 |
| 기존 S1 A DEV | 6730ecf 두 attempt·판정·source/raw 보존 | 실제 A 전달과 안전·cleanup 증거로 유지. 새로운 운영 source로 DEV를 수행했다고 주장하지 않으며 기계적 반복 없음 |

새 preparation은 새 source와 profile로 freeze하고, 모든8개 go/no-go 뒤에만 main29개에 진입한다. 첫 main 이후 source/policy/판정/수집 계약을 변경하지 않는다. 과거 source로 생성한 DEV report는 그 frozen source에서만 재실행한다. 현재 source로 report 검사를 우회하지 않는다.

## 시간과 worker 재사용 판단

DEV attempt-02 실측은 fixture365.59초, adapter1913.12초, cleanup259.53초, 합계2538.25초(42.30분)다. attempt-01은387.52/1860.08/317.75초이며 인프라 실패다. 이를 정상 두 표본처럼 평균내지 않는다.

기존31시간21.6분은 case nominal1318분×1.2+6세션×50분이다. **기존 V1 nominal28분은 의무1800초 stream보다 짧다.** 이를 S1과 같은45분으로 정정하면 case1369분×1.2+300분=**1942.8분(32시간22.8분)**이다. 각 case nominal에는 준비·정리가 이미 포함되므로 DEV 준비를 추가로 더하지 않는다. 표본37개와 H·stream·tail·안정창·cleanup/down 상한을 줄이지 않는다.

S1/S2 총21개에서 DEV의 준비+cleanup625.12초를 모두 없앤다는 불가능하게 낙관적인 상한조차218.79분이다. contingency까지1.2배 절감한다고 가정해도 잔여28시간0.25분이다. 이 값은 비교 가능한 재사용을 입증하거나 달성한 절감이 아니다. S3/S4의 VM/volume 상태 변경에는 이 가정을 적용하지 않는다.

따라서 검증되지 않은 worker 재사용으로24시간을 약속하지 않는다. 이번 보완에서는 기존 auto/1 계약을 유지한다. session worker 유지에는 별도 시작 identity·잔존 namespace/taint/QoS/volume·정책·배치 검증과 종료 복원 계약이 필요한데, 그 구현·검증 비용을 감수해도 확인 가능한 절감만으로24시간 조건을 충족하지 못한다. 자동 범위 축소·불필요한 기동을 하지 않는다.

01:20 KST 부근 계산에서 즉시 시작 예상은10/28 09:43 KST, 원장 추정 약118936원, 완료 후 누적44시간까지 여유 약7시간7분이다. 실시간 Billing이 아니며 기동 지연·실패에 따라 바뀐다. 실제 재개 시 다시 계산한다. 원래10/29 00:00 KST 한도 안의 기한 연장 또는24시간 유지/진입 보류 결정을 사용자에게 조기에 요청했다. 답변 없이 늦은 기한을 적용하지 않는다.

실행 상태·정확한 계산 입력·원장 경로는 새 root의 `progress.json`, `schedule-feasibility.json`에 남긴다. 기존 HOLD/driver/자동화를 수정하거나 재시작하지 않는다. 아직 실행할 장기 driver가 없으므로 빈 자동 점검을 등록하지 않는다. 새 기한 승인 뒤 새 세션에서만 단일 driver와 필요한 점검을 등록한다.

## 로컬 검증과 실행 상태

변경 영향에 해당하는74개 테스트가 통과했다: collection10, execution12, calibration10, live review14, agreement review28개다. 일시 SSH 실패·누적 재시도 상한·원격 응답 유실·snapshot 결측/시각 위반·별도 재수집·과거 시도 ownership 차단·S1 부분 증거 보존·추가 조회 없는 checkpoint·cleanup 재개·S4 start 응답 유실 후 Ready→MHC 복원 순서를 검증했다. calibration의 로컬 HTTP 테스트는 sandbox loopback bind 제한을 확인한 뒤 같은 오프라인 모음을 승인된 sandbox 밖에서 재실행해 통과했다. 클라우드 장애를 추가 주입한 테스트가 아니다.

Python compile, shell syntax, `git diff --check`, 기존 정상 보정 binding/원자료 재계산, 과거 DEV frozen manifest/source/profile integrity도 통과했다. 신규 수집 경로는 아직 live preparation에서 확인하지 않았으며 현재 문서를 본시험 완료나 최종 live 계약 동결이라고 표시하지 않는다. source commit 후 새로운 profile에 이 문서·수집 계약을 등록하고 freeze해야 한다. 기존 V3 또는 과거 driver를 그대로 실행하지 않는다.
