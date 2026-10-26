# 새 평가 실행 사전 보완 기록

2026-10-26. 승인된 연구·실행·설정 문서의 본문은 보존한다. 이 기록은 실행 도구의 보완과 운영 방법을 설명하며 실험 성공을 뜻하지 않는다.

- `development` freeze는 별도 S1 A case 하나를 생성한다. 등록된 37개 case를 재분류하지 않는다. live DEV는 `development_artifact_root`에 저장하고 main campaign root 밖에 둔다. 중단 시 같은 `resume-cleanup` 경로로 정리하며 primary는 0이다. A의 실제 전달 여부는 raw와 독립 판정으로 확인한다.
- 모든 live baseline은 index 0부터 `60×rate`개를 선택한다. bin membership은 index로만 정하며 예정 UTC/monotonic, 단일 clock, 요청 시각·deadline·완전성·bad 비율·성공 p95를 별도로 검증한다. V1은 전용 100ms를 사용한다. S1은 경쟁 VM 생성 전에 검사하고 기존 정책의 90초 대기/마지막 60초 창을 보존한다. S2는 기존 baseline raw, S3/S4는 연속 OpenLoopProbe raw를 사용한다. 판정기도 baseline을 재계산한다.
- S1/S2 paired conditional p95 차이는 유효·장애 재현된 첫 attempt 양쪽에 값이 있을 때만 계산한다. retry·무효·성공지연 결측은 null을 유지한다. 실패율·SLO 피해와 함께 해석하는 보조 지표다.
- case admission은 attempt 생성 전에 호스트·준비 상태·소유권·수명·가동/비용·마감을 검사한다. case 내부는 `verify_ready_environment`만 호출하며 자동 down/ensure를 하지 않는다. 준비 실패 후에는 attempt와 cleanup 증거를 남긴다.
- ensure/fixture/adapter/cleanup/down은 whole-phase 상한이다. fixture의 남은 절대 deadline을 adapter에 전달하고 실제 probe fixture가 준비되면 해당 상한을 끝낸다. 외부 명령마다 상한을 다시 시작하지 않는다. 준비 1800+adapter 5400+cleanup 1800+down 1800=10800초를 예약한다. cold는 14400, 명시적 down→ensure 회전은 16200초다. 주입 시에도 H·관측 tail·cleanup/down 여유를 검사한다.
- `BedLedger`는 ensure 직전부터 모든 호스트의 TERMINATED 재조회까지 보수적으로 가동시간을 센다. 준비·DEV·유휴·실패·정리를 포함하고 release/policy마다 초기화하지 않는다. 실패·프로세스 종료만으로 가동 구간을 닫지 않는다. 비용은 실시간 청구액이 아닌 운영 추정 gate다.
- pilot 계약에는 전체 단계 상한·headroom·마감이 포함된다. main 전 네 시나리오의 pilot wave 전체를 요구한다. 동일 source/계약의 별도 pilot campaign을 반복해 성공만 고르는 것은 차단한다. 기존 campaign의 infra-invalid attempt에 대한 명시적 retry를 사용한다.
- 설정 부록·수행 프롬프트는 source hash 및 별도의 문서 경로/SHA-256/복사본으로 보존한다. 현재 파일과 복사본의 변경을 모두 검사한다. 공통 판정·계측·운영 gate 파일도 policy manifest에 보수적으로 포함한다.

## 운영 입력과 원장

사용자는 2026-10-26에 총 435,523원 중 249,289원 사용, 만료일 2026-11-19라고 답했다. 잔액 **186,234원**은 사용자 제공값이다. 기존 신규 작업 gate 160,000원을 **146,234원**으로 낮추고 정리 reserve 40,000원을 유지한다. 만료일은 보수적으로 11월 19일 00:00 KST로 해석한다.

추정 원장은 bed 2,500원/가동시간, 보관 자원 4,000원/달력일, 다른 사용량·network·세금·오차 20,000원을 신규 작업 한도 안에 예약한다. 이는 등록 Catalog compute 약1,250.38원/시간·320GiB disk 약1,823.35원/일보다 보수적인 예산용 수치다. 정확한 Billing 총액·실시간 차단을 구현했다고 주장하지 않는다. 디스크·IP·image/snapshot 및 다른 프로젝트의 실제 자원 조회를 artifact에 별도로 남긴다. 유료 전환·신규 결제 계정·B의 유료 자원은 생성하지 않는다.

`artifacts/fresh-evaluation-2026-10-26/progress.json`은 단계·완료 수·다음 작업을, 같은 root의 `bed-uptime-cost-ledger.json`은 실제 가동 구간과 비용 추정을 보존한다. immutable profile은 `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/`에 둔다. source가 바뀌면 새 DEV snapshot부터 필요한 검증을 수행한다.

## 진입점

아래 경로는 실제 immutable profile·새 artifact 디렉터리로 채운다. 모든 live 명령에 기존 환경의 `ENV_OVERRIDE_FILE`을 지정한다.

```sh
make graduation-fresh-environment-ensure FRESH_PROFILE=/absolute/operations-profile.json CAMPAIGN=/absolute/operations-artifacts
# 실제 identity/version/image/flavor/timer/MHC readback을 확인한 별도 confirmed profile 생성
make graduation-fresh-dev-freeze FRESH_PROFILE=/absolute/confirmed-profile.json CAMPAIGN=/absolute/development/snapshot-v1
make graduation-fresh-run CAMPAIGN=/absolute/development/snapshot-v1 LIMIT=1
make graduation-fresh-report CAMPAIGN=/absolute/development/snapshot-v1
# session rotation: admission과 가동/비용 gate 후 별도 down→cold ensure
make graduation-fresh-environment-rotate FRESH_PROFILE=/absolute/confirmed-profile.json CAMPAIGN=/absolute/operations-artifacts
make graduation-fresh-environment-down FRESH_PROFILE=/absolute/confirmed-profile.json CAMPAIGN=/absolute/operations-artifacts
```

실제 측정·실패·go/no-go와 남은 일정은 artifact에 계속 기록한다. 이 문서 작성 시 새 live DEV·preparation·main은 아직 0개다. 기존 결과·합성·DEV·preparation은 main n에 포함하지 않는다.
