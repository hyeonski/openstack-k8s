# 새 세션용 — 미실행 S1 정상 보정 재개

워크스페이스 `/Users/hyeonseungkim/workspace/openstack-k8s`에서 S1 정상 baseline 보정을 이어서 수행해 줘. 먼저 [이번 실패 보고](s1-baseline-calibration-report-2026-10-26.md), [사전 등록 프로토콜](s1-baseline-calibration-protocol-2026-10-26.md), 기존 `fresh-evaluation-*2026-10-26.md` 연구·운영 문서, `artifacts/baseline-calibration-2026-10-26/run-v1/release-summary.json`, 기존 전체 가동/비용 원장과 현재 Git 상태를 읽어라.

이번 기록은 **새 정상 측정0/3·validation0/2**, 후보/SLO amendment/새 confirmed profile 없음이다. worker2개 준비 중 local workload API SSH tunnel이 끊겼고600초 준비 상한에 도달했다. cleanup 잠금 충돌 후에도 down에 진입하는 실행기 결함을 발견해 수정했다. 중간 controller 정지 뒤 소유 cleanup을 재개한 이력과 최종 상태를 확인하라. 이전 DEV2회는 주입 전200ms baseline 실패이며 불변 이력이다. 200ms를 아직 확정된 정상 기준 또는 폐기된 기준으로 부르지 않는다.

## 기동 전에 끝낼 일

1. 저장소 지침·branch/status·최근5개commit, `evaluation/fresh_calibration.py`, `fresh_contract.py`, `fresh_live.py`, 기존 readiness/worker-control/터널과 tests를 확인한다. code·doc 변경은 `type: 한국어 제목`과 bullet·검증 본문으로 커밋한다. 기존 frozen DEV345파일과 run-v1 원본을 수정하지 않는다.
2. 원래 API 터널의 Broken pipe 원인은 미확정이다. 준비 중 local API 연결 끊김을 조기에 감지하고 기존 연결 ensure로 재연결하는 절차를 좁게 준비·검증하라. 서비스/worker VM 장애 주입이나 평가 대상 복구 정책으로 대신하지 않는다. 터널 로그·readiness의 실제 Node/Pod/Calico 상태와 연결 오류를 구분한다.
3. 현재 runner의 cold ensure900초·initial worker600초·run420초 예약과 실측 준비 지연을 검토하라. 상한을 무조건 늘리지 않는다. 첫 기동부터120분 중 cleanup30+down30분을 예약하므로 준비·5회 관측·동결이60분 안에 들어가야 한다. 새로운 측정 전에 필요한 준비 절차/예상시간/더 이른 deadline과 변경 사유를 별도 문서/JSON/source로 고정하라. 기본25분 관측을 줄이거나 이전 세션의 예산을 자동 연장하지 않는다.
4. cleanup 실패 시 down을 막는 수정과 예외 경로·고정 index/clock/deadline·후속 freeze binding을 테스트하고 `make lint`를 통과시킨다. 실행 중 source를 수정하지 않는다.

## 정상 측정만 수행

기존 bed `cloud-gcp-amd64-greenfield`, GCP project `openstack-k8s`, zone `asia-northeast3-a`, override `config/environments/local.env`를 사용한다. controller e2-standard-4, source compute02 n2-standard-4, target/control-plane compute01 n2-standard-8을 유지한다. 다른 실행과 잠금을 먼저 확인하고3대 호스트·소유 자원·worker auto/1의 현재 상태를 readback한다.

새 고유 artifact root를 `artifacts/baseline-calibration-2026-10-26/` 아래 만든다. run-v1을 재사용하지 않는다. 기존 `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-confirmed-v1.json`은 **정상 측정의 입력 기반**이다. 새 SLO가 검증된 profile이 아니다. 현재 CLI는 아래와 같고, source/준비 절차를 바꿨다면 새 계약을 소비하는지 다시 확인한다.

```bash
ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env \
  bash evaluation/s1-baseline-calibration.sh register \
  --directory /Users/hyeonseungkim/workspace/openstack-k8s/artifacts/baseline-calibration-2026-10-26/<새-고유-실행명> \
  --profile /Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-confirmed-v1.json

ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env \
  bash evaluation/s1-baseline-calibration.sh run \
  --directory /Users/hyeonseungkim/workspace/openstack-k8s/artifacts/baseline-calibration-2026-10-26/<새-고유-실행명>
```

정상 calibration3×300초와 동결 후 validation2×300초는 모두 미실행이다. 5rps·100000rounds·deadline5초·동일 실제 URL/placement·warmup0, 매 run fixture 재생성·새 stream을 유지한다.

프로토콜의 선정 규칙(45개 bin 최대 선형p95×1.20,10ms 올림,최소200/상한500)을 새 validation에 맞춰 튜닝하지 않는다. bin20초·bad.05·index0 첫60초·최종 안정120초를 유지한다. 후보값·profile·source·판정 코드를 동결한 뒤에만 별도 validation2회를 수행한다. 두 run 각각 첫60초 진입 조건과 전체300초의 모든 bin 안정 조건을 구분해 판정한다. 실패·미실행·결측·모든 시도를 보존하며 성공할 때까지 반복하지 않는다. 정상/장애군의 유불리에 맞춰 임계값을 고르지 않는다.

## 예산·정리·다음 평가

이번 가동 원장에 든 실패/정리 시간을 미래 예상에 또 더하지 않는다. 하지만 완료된 정상 관측은0분이므로25분 관측과 준비/정리 비용은 여전히 필요하다. 다음 정상 보정은 새120분의 작업 배정이 필요하며, 이전 예산을 이어 무한 연장하지 않는다. 전체10/29 00:00 KST 마감·44h 신규 중지/48h 상한·신규146234원/정리40000원을 유지하고 최신 원장으로 재산정한다. 186234원은10/26 17:10 KST 사용자 제공 잔액이며 실시간 Billing값이 아니다. 기존20000원 reserve를 다시 더하거나 실제 잔액에서 estimate를 중복 차감하지 않는다.

cleanup proof가 통과하기 전 down하지 않는다. 원래 worker auto/1·UID·namespace/소유자원을 확인하고 기존 down으로3대 TERMINATED를 검증한다. 잠금·journal이 남으면 소유 process 종료와 기존 worker control-recover를 먼저 확인한다. 필요한 안전 정리는 계속하되 신규 측정은 시작하지 않는다. 기존320GiB persistent disks·snapshot은 보존한다.

**이 정상 보정 세션에서 경쟁 VM·장애·A 재시작·DEV·pilot·main을 실행하지 않는다.** 보정과 별도 validation이 모두 통과하면 새 immutable profile/amendment를 만들고 `analysis.s1_calibration`에 candidate/validation raw·metrics/summary의 SHA와 amendment SHA를 연결한다. `operations.preregistered_documents`에 amendment·프로토콜·새 설정을 등록해 후속 freeze가 복사본/내용을 검증하게 한다. S1 진입 gate와 전체primary/회복은 같은 SLO를 쓰고, S2~S4 및 V1의100ms는 바꾸지 않는다.

그 뒤 별도 평가 세션에서 새 snapshot DEV→필수preparation8→main29 순서다. DEV122분·preparation372.8분·main1508.8분 합계2003.6분은 남은 fault 평가의 기존 보수적 계획값이며 실측 보장이 아니다. 정상 보정이 아직 남아 있으므로 별도 정상 보정 시간도 추가로 필요하다. A 실제restart·V1조건·S2~S4효과는 계속 미검증으로 인계하라.
