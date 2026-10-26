# Controller CPU architecture amendment — 2026-10-26

사용자는 재개 기동에서 동일 E2 controller의 CPU가 Intel Broadwell에서 AMD Rome으로 바뀐 관측을 확인한 뒤, controller는 ARM이 아닌 조건이면 된다고 지시했다. 이를 **controller에 한정한 x86_64 architecture 계약**으로 구체화한다. 이전 profile·calibration·DEV와 모든 source/raw/judgement는 보존한다. 아직 새 DEV·pilot·main은 수행하지 않았다.

## 허용 범위와 유지 조건

- 대상은 `osk8s-controller` 한 대, VM ID `8689617440184466555`, 사양 `e2-standard-4`다. ID·사양·환경·project·zone·설정은 기존 계약대로 유지한다.
- Controller의 CPU 모델은 Intel/AMD provider-selected 값으로 허용하되 실제 guest의 `uname -m`이 **정확히 `x86_64`**여야 한다. `aarch64`·`arm64`·32bit·미확인·조회 실패는 거절한다. GCP 플랫폼 값도 Intel/AMD여야 하며 ARM/미확인 provider 값과 모순되면 거절한다. Intel/AMD 이름만 보고 architecture 검사를 생략하지 않는다.
- Source compute02 `n2-standard-4`, target/workload-control-plane compute01 `n2-standard-8`의 VM ID·사양·`Intel Cascade Lake`는 계속 정확히 일치해야 한다. 예외를 workload/control-plane compute에 적용하지 않는다.
- 관측한 controller `cpuPlatform`을 실제 값 그대로 저장한다. profile의 과거 정상 보정 환경 snapshot은 보정 당시 참조이며, 이를 이번 기동 실제 관측으로 고쳐 쓰지 않는다. case 진입·ready 검사에서 현재 architecture와 CPU 모델을 별도 기록한다. 연속적인 CPU 모델 감시를 구현했다고 주장하지 않는다.
- profile에 명시적인 `operations.controller_platform_policy`와 이 문서의 SHA/preregistration이 있을 때만 적용한다. 키가 없는 기존 profile은 여전히 전체 host CPU 모델의 정확한 일치를 요구한다. 잘못된 scope·architecture·ID/type·문서 binding은 live validate/freeze/run 진입에서 거절한다.

Google Cloud는 E2에 minimum CPU platform을 선택할 수 없다고 명시한다. https://docs.cloud.google.com/compute/docs/instances/specify-min-cpu-platform (Limitations, 2026-10-26 확인). 특정 CPU가 나올 때까지 stop/start를 반복하거나 호스트 사양을 변경하지 않는다. 새 프로젝트/bed·유료 전환도 하지 않는다.

## 측정·연구 계약에 미치는 영향

Controller는 workload control-plane이 위치한 compute01과 별도지만 OpenStack/management 및 연결·조치 경로에 참여한다. 같은 x86_64라는 사실이 동등한 성능을 보장하지 않는다. controller 모델 변동이 연결·조회·조치 지연에 미칠 수 있는 영향을 한계로 공개하고 세션별 실제 플랫폼을 남긴다. 고정 CPU controller의 효과나 다른 controller 환경으로의 일반화는 주장하지 않는다.

변경은 admission/ready의 운영 identity 계약이다. `kubernetes/graduation-s1/app.py`, `loadgen.py`, `evaluation/fresh_baseline.py`, `fresh_analysis.py`, `fresh_contract.py`, `fresh_calibration.py`의 정상 측정·판정 source는 변경하지 않는다. 기존 `analysis.s1_calibration`의 모든 SHA·raw·validation 재계산과 [S1 정상 기준 amendment](s1-baseline-amendment-2026-10-26.md)를 그대로 검증한다. 기존 Broadwell controller의 정상 3+2 측정은 그 당시의 정상 보정 증거로 유지하며 AMD controller를 따로 3+2 검증했다고 표시하지 않는다. 현재 실행의 고정 첫60초 baseline·DEV·필수 pilot이 실제 조건에서 계속 gate 역할을 한다.

이미 완료한 정상25분을 새 수행이나 미래 작업으로 다시 세지 않는다. S1 SLO200ms(진입·primary·회복 공통), rate5·100000rounds·warmup0·총1800초·H1200+30초·bin20초·bad.05·선형 p95·최종120초를 유지한다. V1 전용100ms·상대배율1.5와 S2~S4·fault·fixture·seed·순서·첫 attempt 원칙은 바꾸지 않는다.

운영 identity 파일도 전체 source/policy hash에 포함하고, 이 문서는 새 profile의 preregistered_documents에 추가해 SHA·복사본을 보존한다. 기존 hash 대상을 제외하거나 보정 증거를 다시 쓰지 않는다. 새 profile은 v2를 덮어쓰지 않고 별도 immutable v3로 만든다. 새 source/profile snapshot에서 S1 A DEV를 먼저 실행하고 이후 preparation8개·go/no-go·main29개를 수행한다. 이전 release와 효과 표본을 합치지 않는다.

## 검증과 운영 한도

오프라인 검증은 controller Intel/AMD 허용과 실제 raw 보존, ARM/unknown 거절, controller ID/type 변경과 N2 플랫폼 변경 거절, 기존 profile의 strict 동작, 잘못된/없는 문서 SHA 거절, pilot–main 정책 불일치 거절에 집중한다. 기존 정상 보정 binding과 현재 live validate도 통과해야 한다.

최초 controller 불일치 기동은 attempt 미생성 거절 증거와 소유 상태를 저장한 뒤 정상 down한다. 이후 단 한 번의 정상 ensure로 제공된 controller가 x86_64이고 나머지 계약이 맞으면 진행하며, CPU 모델을 고르는 재기동은 하지 않는다. 실제 guest architecture·host/platform·Node/VM/image/flavor/MHC readback을 확인한 뒤 freeze/run한다.

2026-10-29 00:00 KST 종료, 10/28 21시 case·22시 주입·23시 drain·23:30 down 경계와 더 이른 예약 gate, whole-phase/host-headroom·누적44/48h·신규146234원/정리40000원을 유지한다. 현재 누적 가동·이번 실패 준비·정리·유휴를 같은 원장에 합산하고 reserve20000원을 중복 가산하지 않는다. controller mismatch가 해결됐다는 이유로 A 실제 restart·V1 조건·S2~S4 효과까지 확인됐다고 표현하지 않는다.
