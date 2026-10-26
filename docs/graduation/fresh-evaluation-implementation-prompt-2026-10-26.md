# S1~S4 새 평가 체계 구현 시작 프롬프트

2026-10-26 사용자 결정: 기존 결과를 새 평가에서 제외하고 S1~S4 모두 새로 평가한다. 추가 축소 지시가 없으므로 합의안의 전체 작업 기준인 **F-repeated**로 구현한다. 아래 프롬프트를 이 저장소에서 실행하는 코딩 에이전트에게 그대로 전달한다.

## 전달할 프롬프트

이 저장소의 졸업작품 평가 체계를 구현해줘. 계획만 다시 설명하지 말고, Codex와 Claude가 합의한 구축 상세 계획에 따라 코드·설정·검증·사용 문서까지 구현해줘.

### 확정된 방향과 이번 작업 범위

- 기존 실험 결과는 새 본평가의 표본·비교·그래프·성공 증거에서 제외한다. 과거 raw와 고정 계약은 삭제하거나 소급 수정하지 않는다. 과거 자료를 참고한 설계라는 사실은 남긴다.
- **S1~S4 전체 새 반복 비교인 F-repeated**를 구현 기준으로 삼는다. 구현을 편하게 하려고 F-bounded나 S1-only로 축소하지 않는다.
- 이번 단계는 로컬 구현과 오프라인 검증이다. 클라우드 기동·배포·장애 주입·live smoke·pilot·본시험 실행은 다음 단계다. 20시간·10/28·10/31 등 과거 일정 가정을 확정 예산이나 실행 승인으로 사용하지 않는다.
- 사람 H와 transient T는 합의안의 선택 항목이며 이번 필수 구현 범위에 추가하지 않는다. 선택 여부가 필수 S1~S4 구현을 막지 않도록 한다. 사람이 없는 결과로 인간 대비 우위를 주장하지 않는다.
- 새 지표에 필요한 값을 과거 결과로 채우지 않는다. 합성 trace는 검증용으로 명확히 표시하고 실험 결과로 보고하지 않는다.

### 먼저 읽을 문서

1. `docs/graduation/fresh-evaluation-build-plan-2026-10-26.md`: B01~B11의 대상 파일·변경·완료 조건·검증 표.
2. `docs/graduation/fresh-evaluation-run-plan-2026-10-26.md`: F-repeated의 비교군·run 목록·SOP·freeze·실패·재실행 규칙.
3. `docs/graduation/consensus-research-plan-2026-10-26.md`: 지표·통제·주장 범위와 통계 원칙.
4. `docs/graduation/consensus-discussion-2026-10-26/README.md`: 최종 승인과 사용자의 범위 결정. 중간 대화 원본을 읽을 필요는 없다.
5. 저장소의 `AGENTS.md` 등 적용되는 지침이 있으면 준수하고, `README.md`, `Makefile`, 관련 운영 문서에서 실제 인터페이스를 확인한다.

이 프롬프트의 사용자 범위 결정이 문서에 남은 ‘범위 미선택’ 표현에 우선한다. 나머지 연구 통제와 주장 제한은 합의안을 따른다. 문서에 아직 구현 대상이라고 적힌 옵션을 이미 존재하는 명령으로 간주하지 않는다.

### 만들어야 할 실험 계약

| 시나리오 | 본시험 구성 | 목적 |
|---|---|---|
| S1 | P 재배치 / M no-action / A 같은 worker 재시작, 각3회·3block | 조치 유무와 재시작 대비 재배치 효과 |
| S1 V1 | host-only 본시험2회, 별도 pilot1회 | 서비스 정상인 host 경합에서 보류/오조치/예외 구분 |
| S2 | P 분리+QoS / M 같은 초기 조건의 무개입, 각3회·3pair | 전체 정책의 API·uploader 효과 |
| S3 | P3600 / M3600, 각3회·3pair | 동일 timer 구성에서 H 내 복구·seed·fencing 순서 |
| S4 | MHC on / off, 각3회·3pair | 기존 MHC/CAPI/CAPO의 서비스·용량 복원 |

본시험은 **29 run**이다. 별도 준비/pilot은 자동 smoke1 + V1 pilot1 + S2/S3/S4 pair pilot6 = **8 run**이며, 개발 smoke 묶음은 또 별도다. request·stage·pilot을 독립 본시험 표본으로 세지 않는다. 본시험29와 준비8의 구분을 schedule·report에서 검증한다.

S3 M은 native 기본 설정 비교가 아니다. S4 off 비교는 자체 알고리즘의 고유 우위가 아니다. S2 P 안의 무제어 창을 독립 M 표본으로 대체하지 않는다.

### 구현 순서

1. 현재 Git 상태와 코드를 확인하고 기존 변경을 보존한다. 실행 중인 campaign이 있다면 그 checkout과 원격 소스를 바꾸지 않도록 격리한다. 개발/실행 checkout, artifact, 환경 override 경로의 관계를 명확히 한다.
2. **B01:** profile schema, 명시적 cases, purpose·block·seed·순서, profile 선택 경로, dry schedule와 검증을 구현한다. 기존 구 profile의 동작을 별도 유지하고 새 선택 profile·분석 설정을 freeze/hash에 포함한다.
3. **B02:** 실제 사건 필드 의미를 감사하고 누락된 계측을 추가한다. 기존 raw는 유지하며 독립 adapter에서 정규화한다. 정책과 계측이 섞인 파일은 최초 main 전 필요한 hook 분리를 검토한다.
4. **B03/B04:** S1 P와 기존 M을 새 계약에 연결하고 A·V1을 구현한다. M은 새로 만드는 기능이 아니라 기존 no-action의 재사용이다. 같은 worker 재시작의 node/VM/compute 불변과 경합 지속을 검증한다.
5. **B05/B06:** 독립 판정·분석·attempt 원장·cleanup·재개·hash 검증을 구현한다. 이 단계의 안전/증거 계약이 뒤 시나리오에도 적용되게 한다.
6. **B08/B09/B10:** S2~S4의 독립 비교군·관측 H·정리·판정·테스트를 끝낸다. S1만 완료하고 전체 구현이 끝났다고 하지 않는다.
7. 관련 테스트와 저장소의 오프라인 검사를 수행하고, 실제 구현된 CLI·설정 준비 절차·미확정 입력을 문서화한다. 다음 단계에서 live pilot을 준비할 수 있게 인계한다.

### 반드시 처리할 구현상 함정

- `evaluation/graduation_evaluation_case.py`의 `seconds=1080`, `graduation_evaluation_verify.py`의 요청 수5,400 하드코딩을 없애고 실제 profile/rate/duration/warmup 의미에서 유도한다. 현 의미를 유지하면 S1 rate5×1,800초=9,000개다.
- `schedule()`의 고정 mode 쌍·qualification ID 때문에 새 구성이 KeyError를 내지 않게 한다. 기존 profile의34개 case ID는 회귀 검증한다.
- profile을 선택해서 읽는 것만으로 끝내지 말고 선택된 파일·경로·내용과 분석 규칙까지 freeze에 포함한다. 다른 profile이나 source 변경은 검출되어야 한다.
- S2/S3 검증의 기존 ‘복구 성공’ 전제를 M에 강요하지 않는다. **실험 계약의 유효성(`trial_valid`)과 복구 여부(`recovered`)를 분리**한다. H 내 미복구가 유효한 결과가 되어야 한다.
- S2는 H 전체에 업로드가 활동하도록 등록·검증한다. P/M은 같은 초기 port·QoS·workload·진척 상태에서 각각 시작한다.
- S3의 기존 `node_not_ready_at`을 실제 NotReady 순간으로 사용하지 않는다. 실제 관측과 진단 완료를 별도 사건으로 기록한다. 연속 read probe를 구현하되 지속 write 내구성이나 ACK 무손실로 확대하지 않는다.
- S4는 교체 후 실제 Machine/Node/VM identity와 물리 배치를 다시 확인한다. off 설정 복원·usable capacity·서비스 probe를 별도로 검증한다.

### 지표·증거·freeze 원칙

- 주입 요청/실제 적용, 영향, 탐지/진단, 조치 요청/적용, 지속 회복 시작/안정 확인을 구별한다. UTC와 프로세스별 monotonic clock을 기록하고 다른 host의 monotonic 값끼리 빼지 않는다.
- 예정 arrival·실제 시작·완료를 저장하거나 손실 없이 재구성할 근거를 남긴다. queue 대기·inflight rejection·미완료 요청을 숨기지 않는다. 성공 요청의 latency와 전체 실패율을 함께 보고한다.
- 정책에 주입 정답·미래 해제 시각을 제공하지 않는다. 독립 판정은 raw에서 재계산하며 runner success flag에 의존하지 않는다.
- pilot/연습/합성/과거자료가 primary에 섞이지 않도록 한다. raw와 정규화 view 간 파일·필드·변환 출처를 남긴다.
- 정책이 회복했다고 같은 군의 관측을 조기 종료하지 않는다. H 종료 뒤 구조·cleanup을 primary 복구 시간에 포함하지 않는다.
- 정책 hash는 모든 시나리오에서 고정한다. pilot/main은 별도 완전한 manifest, S1 모든 main 세션은 같은 freeze를 사용한다. 활성 campaign에서 소스를 수정하며 계속 돌리지 않는다.
- 평가 도구 수정은 allowlist·diff·영향 분석과 새 cohort로 관리한다. 판단/조치/guard/threshold 변경을 계측 수정으로 위장하지 않는다. 실패 attempt와 불리한 결과는 덮어쓰거나 삭제하지 않는다.
- H·SLO·bin·안정창·최소 표본·deadline·주입 강도의 live 값은 합의한 절차로 본시험 전에 확정한다. 아직 모르는 값은 draft 설정과 명확한 validation error로 표현한다. 구현·합성 테스트는 계속하되, 미확정 값으로 live freeze/run을 허용하지 않는다.

### 검증과 완료 조건

구축 상세안의 검증 표를 실제 테스트에 연결한다. 특히 정상 회복, 재악화, M 미복구, 잘못된 대상, 시간 역전, 누락·중복·queue 지연, hash 변경, 과거자료 혼입, 적용 후 응답 소실, 재개, cleanup 실패를 검증한다. runtime 권한이 필요한 테스트는 mock/fake로 격리하고 네트워크를 호출하지 않도록 한다.

관련 테스트가 통과하면 실제 저장소의 `make lint`가 오프라인 검사인지 다시 확인하고 실행한다. 사용할 수 없는 의존성이 있으면 정확히 보고하고 가능한 검증을 완료한다. 구현에 필요한 회귀 검증 없이 문서만 갱신해 완료 처리하지 않는다.

완료 보고에는 다음을 포함한다.

1. B01~B06·B08~B10별 구현 상태와 파일, 미완료 항목 및 이유.
2. 검증 명령과 실제 결과. 합성 증거와 live 증거의 명확한 구분.
3. F-repeated의 본시험29·준비8 schedule 및 pilot/main 분리 확인.
4. 실제로 구현한 CLI와 로컬 사용법, draft profile을 실행 가능한 profile로 확정하는 절차.
5. live pilot 전 필요한 환경 값·운영 입력과 현재 차단 조건. 아직 실행하지 않은 실험을 통과했다고 표시하지 않기.
6. 변경 diff와 커밋 여부. 커밋할 때는 저장소 관례인 `feat:`, `fix:`, `test:`, `docs:` 등의 타입과 한국어 요약을 사용하고 관련 변경만 포함하기.

계획 재작성이나 S1 구현만으로 멈추지 말고, 선택된 전체 범위의 로컬 구현과 오프라인 검증을 마무리해줘. 실환경이 필요한 최종 확인은 정확한 인계 항목으로 남겨줘.
