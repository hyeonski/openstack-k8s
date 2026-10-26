# 새 평가 실행 상세안

작성: 2026-10-26. 실제 합의 상태와 승인본 hash는 [협의 기록](consensus-discussion-2026-10-26/README.md) 참조. 이 문서는 실행 설계이며 실험·구현·클라우드 비용 집행이 완료됐다는 뜻이 아니다.

[체계 구축 상세안](fresh-evaluation-build-plan-2026-10-26.md)과 함께 읽는다. 기존 결과는 새 primary에서 제외한다. [이전 연구 합의안](consensus-research-plan-2026-10-26.md)의 통제·해석 원칙은 유지하고, 이전 실행안의 ‘기존 34건+추가 실험’ 범위와 시간표는 아래 선택지로 대체한다. 사용자 실제 일정·예산은 아직 미확정이며 20시간은 과거 문서의 테스트베드 예산 가정일 뿐이다.

## 1. 실행 범위 선택

| 구성 | 새 본시험 | 목적과 한계 |
|---|---|---|
| F-repeated | S1 P/M/A 각3, S2 P/M 각3, S3 P/M 각3, S4 on/off 각3, V1 2 | 전체 S1~S4를 같은 새 계약 계열로 반복 비교. 소표본·고정 fixture의 제한된 효과 평가 |
| F-bounded | 위에서 S3 M과 S4 off를 각1회로 축소 | S3·S4 대조는 H 내 동작 시연. 그 군의 변동성·확률·paired 평균 효과 주장 제외 |
| F-S1 | S1 P/M/A 각3, V1 2 | 시간 제한용 부분 평가. S2~S4의 새 실증 결과는 없음 |
| H 선택 | 실제 사람3 + 연습1 | 동일 S1 block에 H 추가. 참여자 사례이며 일반 운영자 집단으로 확대 금지 |
| T 선택 | S3 transient pilot1 + main2 | 경계 동작 사례. 사전 구현·범위 선택 시에만 추가 |

F-repeated는 반복 대조까지 요구할 때의 전체 작업 기준이다. F-bounded는 대조를 시연으로 줄이는 연구 주장 축소안이고, F-S1은 시나리오 범위 자체를 줄이는 안이다. n=3은 충분한 검정력이나 확증을 보장하는 보편적 최소값이 아니다. G0에서 하나를 선택하고 본시험 결과에 따라 바꾸지 않는다.

Codex는 반복 대조를 갖춘 F-repeated를 전체 작업 기준으로, Claude는 정보 증가가 적은 S3 M/S4 off의 반복을 줄이는 F-bounded를 비용 대비 선택으로 권한다. 두 안의 타당성·주장 한계·실행 절차에는 합의할 수 있으며, 실제 예산 선택을 에이전트 간 합의로 대신하지 않는다.

## 2. 비교군·질문·허용 결론

| case 계열 | 같은 조건 / 달리할 조건 | 관측·허용 주장 | 금지 확대 |
|---|---|---|---|
| S1 P-M | workload·배치·진단·timer·H 동일 / 재배치 실행 여부 | 해당 fixture에서 모듈의 조치가 H 내 서비스 피해·회복을 개선하는지 | 기본 설정 일반/N-native와 동치라고 단정 |
| S1 P-A | 동일 진단·통보 / 다른 compute 재배치 대 같은 worker 재시작 | 단순 재시작과 배치 변경의 차이 | topology 정보 자체의 독립 효과, OpenStack actuator 필요성 |
| S1 H-P | 같은 증상·도구·허용 조치·판정 / 실제 사람의 판단·명령 | 해당 참여자의 전체/작업 시간·개입 차이 | script를 인간으로 계산, 일반 사람보다 항상 빠름 |
| S1 V1 | host 경합이 있고 서비스는 정상 / 제안 정책 관측 | 해당 음성 조건에서 정상 보류 또는 오조치·예외 | 두 번으로 오탐률·범용 원인 분류 추정 |
| S2 P-M | 같은 초기 공유 port·부하·H / P만 workload 분리+QoS 정책 실행 | 이 설정에서 전체 정책의 서비스·uploader 효과 | 최적 고정 QoS보다 우월, 모든 단일 계층 정책 불가능, 각 조치 효과 분리 |
| S3 P3600-M3600 | 같은 toleration·force-detach·MHC·관측 / P만 fencing+복구 실행 | 원래 fixture의 H 내 read 가용성·seed·안전 순서 | native 기본 구성보다 우월, 영원히 미복구, 지속 write ACK 무손실 |
| S4 on-off | 같은 workload·머신·H / MHC remediation 활성 여부 | 기존 MHC/CAPI/CAPO의 서비스·용량 복원과 workflow 관측 | 자체의 새로운 VM 복구 알고리즘 우위 |

F-bounded의 S3/S4는 P 반복 결과와 M/off 1회 시연을 나란히 기술한다. P3 대 M1의 평균 배수·paired 통계·비복구 확률을 계산하지 않는다. 한 번의 관측과 설정상 기대 동작을 구분한다. pilot을 부족한 본시험 n에 합치지 않는다.

## 3. 실행 목록과 반복 단위

case ID는 사전 생성하여 manifest에 고정한다. 예: `s1-b01-p`, `s1-b01-m`, `s1-b01-a`; `s2-b01-p/m`; `s3-b01-p/m`; `s4-b01-on/off`; `s1-v1-pilot-01`, `s1-v1-main-01/02`. retry는 case ID를 덮어쓰지 않고 별도 attempt ID를 부여한다.

| 순서 묶음 | F-repeated 예정 내용 | nominal 시간 |
|---|---|---:|
| 개발 D | 신규 S1 경로·공통 도구 smoke 묶음, 본시험 제외 | 별도 총 122분 |
| S1 준비 | 자동 smoke1×45 + V1 pilot1/main2×28 | 129분 |
| S1 본시험 | 3block×P/M/A, 각45 | 405분 |
| S2 준비·본시험 | P/M pair pilot1 + 본시험3pairs, 각run38 | 304분 |
| S3 준비·본시험 | P/M pair pilot1 + 본시험3pairs, 각run35 | 280분 |
| S4 준비·본시험 | on/off pair pilot1 + 본시험3pairs, 각run25 | 200분 |

F-repeated는 본시험29 run(S1 9+S2 6+S3 6+S4 6+V1 2), 별도 준비/pilot 8 run(자동1+V1 pilot1+세 시나리오 pair pilot6)이다. 개발 D는 이 숫자 밖의 검증 묶음이다. F-bounded는 본시험25 run, 준비/pilot 동일. F-S1은 본시험11 run, 준비2 run이다. H 선택은 본시험3+연습1, T 선택은 본시험2+pilot1을 추가한다.

P/M/A 3군 순서는 seed로 선택한 균형 순환 순서를 사용한다. H까지 4군이면 3block만으로 완전한 Latin square가 될 수 없으므로 제약 무작위화와 위치 불균형을 공개한다. 2군3pair도 2:1 순서 불균형이 남으므로 seed·순서와 세션을 기록한다. 같은 block은 되도록 한 host 세션에서 끝내며 분리되면 사전 정한 incomplete block 처리 규칙을 적용한다.

H 결측은 P-M/P-A를 버리는 이유가 아니다. H-P는 실제 사람이 참여한 block만 사용한다. 나쁜 결과·복구 실패를 결측으로 바꿔 제외하지 않는다. F-bounded의 S3/S4 control 1회는 별도 시연 case로 라벨링한다.

## 4. 시나리오별 수행 절차

### S1

1. source/target worker·VM·compute·image·replica가 profile과 일치하는지 확인한다. 다른 compute로 이동 가능한 목적지가 실제로 있는지 확인한다.
2. 동일 loadgen으로 총 1,800초 조건을 사용한다. warmup/측정 포함 의미를 profile에 명시하고 요청 수를 실행기와 검증기가 일치시킨다.
3. baseline을 기록한 뒤 source compute에 경합을 주입한다. 서비스·host 영향과 실제 적용 시각을 독립 관측한다.
4. P/M/A는 동일 진단 지점에서 각각 재배치/조치 억제/같은 worker 재시작으로 분기한다. A의 임의 scheduler 이동을 막고 실제 동일 node/compute를 사후 확인한다.
5. H는 같은 서비스 증상 통보부터 측정한다. 사람이 명령을 선택하며 안전 executor는 정답을 추천하지 않는다. 정답이 노출되면 H-E로 분리한다.
6. 회복 여부와 무관하게 공통 H와 등록한 관측 구간을 유지한다. 경합 유지·재악화·부수 영향도 기록한다. 종료 후 경합/임시 배치와 자원을 정리하고 다음 run baseline을 확인한다.

V1은 pilot 전에 후보 workload/경합 parameter와 ‘host 경합·서비스 정상’ 조건을 고정한다. pilot 후 main parameter를 고정한다. main에서 조건 불성립이면 그 사실을 결과로 남긴다. 최대 추가 pilot 1회 허용 여부·28분+여유 비용은 사전 예산에 등록하며 기본 합계에는 포함되지 않는다.

### S2

1. 매 run 같은 초기 workload·port·QoS·업로드 진행도·queue 상태로 reset한다. 기존 P의 순차 stage를 독립 M run으로 대체하지 않는다.
2. 등록한 workload trace와 API probe를 실행한다. 업로드는 전체 H 동안 활동하도록 충분한 총량 또는 고정 지속 발생을 등록한다. 총량·진척·실제 active 여부를 관측한다.
3. M은 결합 정책의 변경을 하지 않고 기존 동작을 유지한다. P는 분리+QoS 경로를 실행한다. 정책 외 초기 상태 차이를 금지한다.
4. API 지연·오류·정확성, queue 지연, uploader 고유 완료 byte/goodput을 같은 시간 범위에서 계산한다. 업로드가 끝나 M이 자연 회복했다면 숨기지 않고 원인을 기록한다.
5. H 종료 뒤 qdisc·Neutron QoS·분리 workload·port의 설정과 ownership을 확인하며 정리한다. restore 실패면 다음 run 금지.

### S3

1. 실제 admitted toleration, force-detach, MHC 존재/정책, volume identity·attach·seed checksum을 확인한다. P와 M을 동일 설정으로 맞춘다.
2. 독립 연속 read probe를 baseline부터 H까지 유지한다. 주입 적용, NotReady 실제 관측, 진단 완료를 서로 다른 사건으로 기록한다.
3. P는 기존 writer를 안전하게 fencing한 뒤 out-of-service·volume 복구를 진행한다. M은 해당 변경을 억제하고 H까지 관측한다. M에서 회복하지 않았다는 이유로 harness exception을 만들지 않는다.
4. seed 일치·writer 차단 근거·UID·실제 변경 순서를 보존한다. sparse probe나 attachment 수만으로 강한 데이터/단일 writer 보장을 주장하지 않는다.
5. H 종료 뒤의 구조·정리는 별도 actor다. 필요하면 복구하되 그 시간은 실험 회복으로 세지 않는다. firewall·taint·volume·VM·DB 상태가 정리될 때까지 다음 run을 막는다.

M의 H가 3,600초보다 짧으면 native eviction을 기다린 시험이 아니다. 결론에 timer와 H를 반드시 병기한다. 더 강한 native 또는 fencing-only 조치 분해는 원 연구 계획의 별도 실험이다.

### S4

1. 실제 MHC·Machine·VM 매핑, 보호 대상·controller 상태, 서비스 replica와 목표 capacity를 기록한다.
2. off는 해당 case의 remediation만 억제하고 on은 기존 MHC/CAPI/CAPO 동작을 허용한다. 다른 제어기·수동 복구가 개입하면 actor와 원인을 기록한다.
3. 같은 방식으로 worker VM을 정지하고 서비스 probe와 usable capacity를 관측한다. Pod/Node Ready와 실제 scheduling 가능성을 구분한다.
4. H 종료 뒤 MHC 설정을 복원하고 실제 worker 수·배치를 확인한다. 전체 일정에서 S4를 마지막에 둔다. 교체된 VM/Node 이름을 이전 run에서 캐시하지 않는다.

### 선택 T

pilot 뒤 등록한 early/late 사건에서 장애를 해제한다. 실제 해제 시각을 확인하고 정책에 미래 해제 정보를 제공하지 않는다. 예외 중단·정상 보류·fencing·자가 회복을 분리한다. T는 별도 구축·검증 gate를 통과해야 하며 남은 시간을 보다가 임의로 추가하지 않는다.

## 5. run 공통 SOP와 중단 규칙

| 단계 | 실행·저장 | 통과하지 못하면 |
|---|---|---|
| 0 예산/동결 확인 | source/profile/분석 hash, 남은 host 수명·예산, case·purpose·seed | 주입하지 않음; 준비 실패 기록 |
| 1 환경 초기화 | ownership·배치·용량·timer·기존 잔존물·probe 경로 | 수정 가능한 준비 문제만 정리; 예상과 다른 배치는 새 snapshot/검토 |
| 2 baseline | 정상 서비스·부하·계측 완전성·clock/요청 수 | baseline 실패. 정상으로 간주하고 계속하지 않음 |
| 3 주입 | 요청/실제 적용·대상 identity·장애 강도 | 주입 실패와 영향 없음 분리; 모든 attempt 보존 |
| 4 관측·조치 | 정책/비교군·독립 probe·API 요청/결과·사람 작업 | 위험·오염 시 중단하고 intervention 기록; 실패를 성공으로 재라벨링 금지 |
| 5 H 종료 | recovered/미복구/불명, 안정창·재발·직접 관측 안전 증거 | H 후 회복은 primary 밖; 결측을 정상으로 채우지 않음 |
| 6 cleanup | 주입 해제, 변경 복원, workload/volume/controller·잔존물 검사 | 다음 case 금지. 잔여 비용으로 정리 우선 |
| 7 증거 마감 | raw hash·attempt status·독립 판정·source 재검증 | evidence incomplete로 보존; 이전 결과 덮어쓰기 금지 |

host 수명 10시간을 가정할 때 2시간 headroom을 남긴다. 새 case와 정리까지 계획 한도에 들어오지 않으면 다음 세션으로 넘긴다. `H`, `max_case`, cleanup 상한은 서로 다른 값으로 profile에 둔다. 최종 허용 시각 이후 새 주입 금지, 정리와 자료 보존은 계속한다.

## 6. 판정·분석·보고서

본시험 전에 H·SLO·안정창·bin·최소 관측 수·deadline·primary contrast를 고정한다. 값의 확정 절차는 구축 상세안 8절에 있다. 고정이 끝나지 않으면 본시험 실행 불가이며, 문서가 있다는 이유로 임의 기본값으로 실행하지 않는다.

기본 raw 판정은 `{trial_valid, fault_realized, impact_realized, recovered, safety, execution, cleanup}`이다. primary 표에는 실패·미복구·개입·불명을 모두 남긴다. 계약 불성립 attempt는 별도 표에 함께 공개하며 부적합 표본을 조용히 교체하지 않는다.

S1/S2 및 F-repeated S3/S4의 주 분석은 block별 paired raw 점·차이와 범위다. 성공 run의 회복시간과 전체 H 내 회복 비율을 분리한다. p값을 만들기 위해 반복을 늘리거나 유리한 run만 고르지 않는다. N=3에서 신뢰도·일반화·유의한 우위가 입증됐다고 미리 정하지 않는다.

기존 자료를 새 primary table에 읽는 코드 경로를 막고, report는 campaign ID와 purpose=main을 명시적으로 확인한다. 산출물은 `run-results`, `attempt-ledger`, `paired-contrasts`, `missingness`, `claim-coverage`, source/설정 manifest 및 원자료 재분석 방법이다. S3/S4 bounded control은 별도 시연 표, 과거자료는 선택적 개발 부록으로만 둔다.

## 7. 시간표 — 시나리오를 한 세션에서 혼합하지 않는 보수적 기준

45/38/35/25/28분은 각 run의 개별 준비·관측·정리를 포함한 잠정 추정이다. 새 M, 긴 H, 연속 probe, 환경 복원 비용은 실제 pilot으로 검증해야 한다. run 합계×1.2로 여유를 두고 **본시험 세션당 공통 운영 50분**을 더한다. 개발 D는 `60×1.2+50=122분`으로 별도 계산한다. 시나리오별 pair pilot은 D에서 검증하지 못한 신규 경로의 live smoke를 겸한다.

| 본시험 세션 | F-repeated | nominal | 20%+50분 포함 |
|---|---|---:|---:|
| A S1 | 자동 smoke45+V1 84+block1 135 | 264 | 366.8 |
| B S1 | block2·3 | 270 | 374 |
| C S2 | pair pilot+3pair | 304 | 414.8 |
| D S3 | pair pilot+3pair | 280 | 386 |
| E S4 | pair pilot+3pair | 200 | 290 |

모든 nominal은 355분 이하, wall은 480분 이하다. 개발 D와 본시험 세션 D의 이름 혼동을 피하기 위해 실행 manifest에서는 개발을 `DEV`, 본시험은 `SESSION-A`~`E`로 기록한다. 같은 시나리오라도 새 세션에서는 full health/placement gate를 통과한다.

| 선택 | 산식 | 예상 테스트베드 시간 |
|---|---|---:|
| F-repeated | 1318×1.2 + 5×50 + 122 | **1953.6분 = 32시간 33.6분** |
| F-bounded | 1198×1.2 + 5×50 + 122 | **1809.6분 = 30시간 9.6분** |
| F-S1 | 534×1.2 + 2×50 + 122 | **862.8분 = 14시간 22.8분** |
| F-S1+H | 714×1.2 + 3×50 + 122 | **1128.8분 = 18시간 48.8분** |
| F-S1+T | 600×1.2 + 3×50 + 122 | **992분 = 16시간 32분** |
| F-S1+H+T | 780×1.2 + 4×50 + 122 | **1258분 = 20시간 58분** |

T의 66분은 S3이므로 이 표의 시나리오 분리 원칙에 따라 **별도 본시험 세션 운영 50분**이 든다. 이전의 같은 세션 혼합 산식보다 비싸다. 중간에 세션을 공유하려면 실제 전환/복원 비용과 placement gate를 검증한 수정 계획이 필요하다. 그 절감은 기본 예산에 미리 넣지 않는다.

F-S1+H는 준비174분을 세션A에, 4군 block1·2·3을 각180분으로 두어 A354/B180/C180으로 배치할 수 있다. 사람의 4×45분 참여 창과 실제 대기/체류 시간은 별개다. 전체안에 H를 추가하면 S1 세션이 하나 늘어나므로 F-repeated+H는 2219.6분(36시간 59.6분), F-bounded+H는 2075.6분(34시간 35.6분)이다.

전체안의 T는 이미 있는 S3 세션에 붙일 수 있다. F-repeated의 S3 nominal은346분, F-bounded는276분이 되어355분 이하이고 총액은 각각79.2분 증가한다. F-S1에서는 S3 세션이 없으므로 위 표처럼50분 운영비도 추가한다.

20시간 가정에서 F-S1 잔여는337.2분, H 포함 잔여는71.2분이다. 새 세션에서 45분 case를 재실행하면104분, 3군 block 전체면212분이 더 들 수 있다. H안의 잔여만으로 새 세션 재실행 한 번도 감당하지 못한다. 여유를 초과하면 사전 축소·중단 규칙을 적용한다.

본시험마다 최대 추가 retry1회를 사전 상한으로 두되, retry를 보장하는 예산은 아니다. 주입·계측·환경 문제를 구분하고 원 attempt를 유지한다. 복구 실패를 ‘무효’로 바꿔 유리한 retry로 교체하지 않는다. paired block 오염·버전 변경은 단일 run 교체로 해결했다고 하지 않는다.

구현 노동은 S1 공통20~30h, 전체안 추가10~16h, H 추가6~8h, T 추가3~5h의 잠정 범위다. 테스트베드·구현·분석/집필은 별도 자원이다. 10/31 제출·10/28 신규 실험 종료는 재확인이 필요한 기존 가정이며, 이 총량이 그 일정에 들어간다는 약속은 하지 않는다.

## 8. gate와 완료 판단

- **G0 범위:** 전체/축소안, 일정·시간/비용의 의미·사람·세션 운용 주체를 확정한다. 이 단계 전에는 live 비용을 집행하지 않는다.
- **G1 구현:** 선택 범위의 구축 작업·합성 테스트·profile/CLI 검증 통과. core 실패 시 사람만 빼고 강행하지 않는다.
- **G2 pilot:** 개발 smoke와 필요한 pair pilot으로 경로·조건·측정·시간을 확인한다. 실패하면 본시험 진입 전 수정·재추정한다. pilot 초과비용은 실제 총액에 더한다.
- **G3 freeze:** 최초 main 전 전체 선택 범위의 정책 hash를 고정하고, 각 시나리오의 pilot과 main은 별도 frozen manifest로 관리한다. pilot은 후보값이 모두 명시된 계약으로 실행하며 null 값으로 시작하지 않는다. main 전 parameter·H·분석·순서·source를 확정하고 새 main manifest를 만든다. S1의 두/세 세션은 같은 main freeze를 사용한다. 활성 campaign 내 변경은 금지한다.
- **G4 run/stop:** 위 SOP로 실행하며 남은 budget·host 수명·cleanup 상태를 매 case 검사한다. 정해진 종료 시각 이후 새 주입 금지.
- **G5 보고:** raw 재분석과 주장 coverage를 확정한다. 미수행 S2~S4를 과거 결과로 자동 충당하지 않는다. 축소했으면 제목·초록·결론의 평가 범위도 함께 축소한다.

주장에 유리한 결과가 나와야 완료되는 것이 아니다. 실행 상태·원자료·실패·한계가 남고, 각 주장에 어느 새 실험이 대응하는지 확인되면 평가 기록이 완결된다. 설계 상세 명세 작성 완료와 실제 구축/pilot/main 완료는 각각 따로 표시한다.

### 시나리오별 freeze와 결함 처리

정책 파일·판단/조치/guard·threshold·허용 정보는 모든 시나리오 freeze에서 같은 policy manifest를 따른다. 평가 도구의 시나리오별 수정은 사전 allowlist와 diff·영향 분석으로 구분한다. 정책 parameter를 profile 변경으로 우회해 조정하지 않는다. calibration으로 정할 부하/측정 설정의 범위는 pilot 전에 등록한다.

pilot 결함이면 해당 시나리오를 중단하고, 별도 개발 checkout에서 고쳐 새 freeze의 pilot을 통과한 후 main을 시작한다. 기존 파일·attempt는 폐기하지 않는다. 이미 완료된 다른 시나리오는 그 시나리오의 freeze와 정책 hash가 유효한 경우 보존하되 서로 다른 비교를 하나의 표본으로 풀링하지 않는다.

main 중 발견한 결함이 비교의 의미를 바꾸면 영향을 받은 비교군 전체를 새 cohort로 재실행해야 한다. 유리한 run만 이전 버전에서 가져오지 않는다. 재개 시 도구 수정이 과거 판정에도 영향을 주는지 검사한다. 공통 판정·정책의 변경이면 새로운 연구 release와 재분석/재실행 범위를 명시한다.

재실행 비용은 실제 실패 attempt·재검증·새 세션 비용으로 합산한다. 예를 들어 S2 세션 전체를 한 번 더 수행하면414.8분을 추가로 예상한다. 이것은 실패 비용의 보장된 최대치가 아니며, 반복 수정·긴 정리에 따라 더 커질 수 있다. 그 예산이 없으면 해당 새 main은 미완료로 보고한다.
