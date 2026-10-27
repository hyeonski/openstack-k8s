# S1 이미지 불변성 실패와 보정 당시 digest 고정

V4의 첫 preparation `s1-smoke01-p/attempt-01`은 trial_valid/fault/impact/recovered/cleanup=true, safety=false다. safety의 유일한 실패는 `image_unchanged=false`다. source에서 target compute로 재배치했고 H1200초·필수 stream1800초와 completion host 경합을 관측했지만 서비스 컨테이너 이미지가 바뀌었으므로 pilot go로 수용하지 않는다. main은0개다. V4의 manifest·profile·raw·판정·report는 수정하지 않는다.

실패 원인은 두 worker의 `python:3.12-alpine` 태그 cache/신규 pull 차이다. 공개 Docker Hub registry의 index→linux/amd64 manifest→config를 조회해 다음을 확인했다. 토큰은 저장하지 않았으며 원본 manifest/config는 V4 root의 `image-drift-analysis/registry-manifests.json`에 보존한다.

| 역할 | index digest | Python 버전 / config 생성 |
|---|---|---|
| 정상 보정 및 실패 시도 source 서비스 | `b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d` |3.12.15 /2026-10-21|
| 정상 calibration·validation 및 실패 시도 probe | `4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111` |3.12.14 /2026-09-17|
| 실패 시도 재배치 후 서비스 | `dcc0e21003470826202b4bbb3ac8404eb3076b8a5d22119175f4b69edc55bee4` |3.12.16 /2026-10-26|

index뿐 아니라 amd64 manifest/config가 달라 단순한 digest 표기 차이로 볼 수 없다. 실패 source와 정상 보정의 서비스 digest, 현재 probe와 두 validation의 probe digest는 각각 정확히 같다. 서로 다른 역할의 서비스와 probe까지 같은 이미지였다고 주장하지 않는다.

## 좁은 수정과 재사용

`kubernetes/graduation-s1/service.yaml`의 서비스 image를 정상 보정 당시 `python@sha256:b658…`로 고정한다. `experiments/graduation_s1.py`의 IMAGE는 독립 probe의 정상 보정 당시 `python@sha256:4c471…`로 고정한다. `load_job()`/정상 baseline factory는 그 같은 probe 상수를 사용한다. 기존 app.py·loadgen.py·측정/판정 여섯 source와 SLO200ms·요청 rate·rounds·첫60초 baseline·H·안정창·A patch/진단/복구 정책 값은 그대로다. 실행 시간을 줄이거나 회복 효과를 맞추는 변경이 아니다.

실제로 validation에서 사용했던 각 역할의 동일 digest를 선택했으므로 정상3+2회와 기존 A DEV의 실제 경로 확인은 재사용한다. 새 runtime version으로 바꾸거나 과거 image hash 검사 대상을 삭제하지 않는다. 새 source/profile에서 매 case의 baseline과 이미지 identity를 다시 확인하고 예정된 P/V1 preparation이 실제 재배치 경로를 검증한다. 새로운 digest의 정상 calibration을 수행했다고 주장하지 않는다.

유효하지만 안전 계약이 실패한 V4 시도를 infra retry로 재분류하지 않는다. 원인을 고친 **별도 image-pinned V5 cohort**를 만들고 preparation8개를 모두 새로 검증한다. V4 preparation1개는 새8개나 main29개에 합치지 않는다. 첫 main 전 수정이며 source/policy manifest가 바뀌므로 기존 pilot 재개/성공 선택으로 처리하지 않는다. 새 main29개는 V5의 같은 정책·같은 계약 preparation 전체 go/no-go를 요구한다. 새 artifact root를 택하는 이유와 과거 안전 gate의 해결 증거를 이 문서와 운영 원장에 명시하며 과거 실패를 숨기지 않는다.

## 안전 종료와 재진입 조건

V4는23:57:35 UTC(10/27 08:57:35 KST)에 소유 cleanup·worker auto/1·세 호스트 TERMINATED를 확인하고 공유 bed ledger를 닫았다. 누적 가동19364.01초(약5시간22분44초), 원장 당시 추정36070.78원이며 Billing이 아니다. 추가 조회에서도 세 호스트 정지를 확인했다. 이전 case를 자동으로 다시 실행하지 않고, 수정 source 검증·V5 freeze·새 전체 시간/비용 gate 후 V5에 진입한다.

종료 한도10/29 00:00 KST와 비용·가동·관측·표본 조건은 변경하지 않는다. 실패·기동·cleanup 시간을 기존 공유 원장에 누적하고 새 cohort에도 같은 여유를 적용한다. 24시간 목표 미달은 유지한다. V4의 추가 소요가 남은 전체 일정을 초과시키면 임의 축소/초과 없이 중지한다.
