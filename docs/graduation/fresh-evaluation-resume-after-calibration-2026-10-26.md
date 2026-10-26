# 새 세션용 — S1 정상 기준 확인 후 새 평가 재개

워크스페이스 `/Users/hyeonseungkim/workspace/openstack-k8s`에서 [정상 보정 결과](s1-baseline-calibration-result-2026-10-26.md), [기준 amendment](s1-baseline-amendment-2026-10-26.md), 기존 연구·구축·실행 문서와 현재 branch/status·최근 5개 commit을 먼저 읽어라. 기존 DEV·run-v1 실패와 모든 frozen source/profile/raw/judgement는 보존한다.

**S1 정상 calibration 3회와 동결 후보의 별도 validation 2회가 통과했고 SLO는 200ms를 유지했다.** 효과·복구 실험은 아직 0건이다. 이전 실행 프롬프트의 네 가지 사전 보완 미구현은 과거 설명이다. 현재 코드와 306개 테스트 증거를 확인하고 중복 구현하지 않는다. 모델은 사용자 설정을 따르며 과거 Sonnet 5.5 재검토를 반복하지 않는다.

## 사용할 입력

- 새 immutable profile: `/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-v2.json`
- profile SHA-256: `7328bdd130dbc1c962fa0e637a4faec57a1a7c1f88dd054e335cce411d21adfe`
- 정상 보정 증거: `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/baseline-calibration-2026-10-26/run-v2`
- 등록 source commit: `32188ca`. 등록 source/protocol/profile SHA와 복사본은 `registration.json`, `source/`, `protocol.md`, `retry-protocol.md`다. 후속 결과 문서 커밋은 코드 변경이 아니다.
- 새 development root: `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-development-calibrated-2026-10-26`
- 새 preparation/main release root: `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-calibrated-2026-10-26/bed-a`
- 누적 가동·비용 원장: `/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-2026-10-26/bed-uptime-cost-ledger.json`

`analysis.s1_calibration`과 `operations.preregistered_documents`를 삭제하거나 완화하지 않는다. Live validate와 freeze가 후보·validation raw·문서·설정·코드 일치를 확인해야 한다. 기존 `fresh-20261026-confirmed-v1.json`이나 calibration의 candidate-profile을 대신 넘기지 않는다. 200ms를 이후 비교군이 실패/성공하도록 바꾸지 않는다. S1 진입·전체 primary·회복은 같은 200ms이며 S2~S4·V1은 변경하지 않는다.

## 실행 순서

사용자가 이 재개 작업을 요청하면 기존 환경 기동·소유 fixture·등록 장애/조치·cleanup·down의 통상 작업을 수행하되 더 이른 시간·비용 gate를 유지한다. 정상 보정 세션에서 이미 DEV/pilot/main을 수행했다고 표현하지 않는다. 최종 기록상 호스트 3대는 TERMINATED이지만 기동 전 현재 상태·병행 프로세스·잠금·worker auto/1을 다시 확인한다.

1. 코드·문서·profile SHA와 실제 환경 readback을 확인하고 새 snapshot의 **S1 A 전용 DEV**를 별도 development root에 freeze한다. 기존 두 DEV는 주입 전 baseline 실패였고 A restart 효과를 검증하지 않았다. 실제 source/target·이미지·clock·ownership·고정 첫 60초 baseline과 실제 restart 전달·같은 Node/VM/compute 유지·Pod 교체·cleanup을 검증한다. A가 보류되면 실제 restart 검증으로 세지 않는다.
2. DEV 결과와 예산을 확인한 뒤 필요한 **preparation 8개**를 새 root에 freeze한다. S1→S2→S3→S4 순서를 유지한다. V1 조건·정상 보류, fault 실현, 안전, clock, H, cleanup과 P/on 회복 go/no-go를 확인한다. Native 환경 준비 probe는 연구 preparation 8개를 대체하지 않는다.
3. 모든 go/no-go가 충족된 뒤 별도 main freeze에 해당 `PILOT_CAMPAIGN`과 공통 `POLICY_MANIFEST`를 연결해 **main 29개**를 수행한다. S1 두 main 세션은 같은 freeze를 쓴다. 첫 attempt만 primary이며 retry는 대체하지 않는다. S4 마지막 규칙도 유지한다.

실제 명령은 현재 `make help-evaluation`, `evaluation/fresh_campaign.py --help`, 기존 execution prompt와 CLI를 확인해 사용한다. 기동·준비 중 로컬 API 터널 연결과 실제 VM/Node 준비를 구분한다. 이전 19:28 snapshot은 VM ACTIVE/worker Ready였지만 Node·Pod·Calico가 local API 조회 거절이었다. 이번 retry의 감시기 재연결은 0회였으므로 터널 근본 원인을 해결했다고 단정하지 않는다. 연결 준비에는 기존 ensure를 재사용하고 상한을 자동 연장하지 않는다.

### DEV 진입 명령 예시

아래는 다음 세션용이며 이번에는 실행하지 않았다. Ensure 뒤 실제 host ID·cpuPlatform·Node/VM/이미지 readback이 profile과 일치하는지 확인한 경우에만 freeze/run으로 진행한다. 경로가 이미 있으면 덮어쓰지 말고 기존 상태를 먼저 확인한다.

```bash
export ENV_OVERRIDE_FILE=/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env
S1_CAL_PROFILE=/Users/hyeonseungkim/workspace/openstack-k8s/.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261026-s1-calibrated-v2.json
S1_DEV_CAMPAIGN=/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-development-calibrated-2026-10-26/dev-v1
make graduation-fresh-environment-ensure FRESH_PROFILE="$S1_CAL_PROFILE" CAMPAIGN=/Users/hyeonseungkim/workspace/openstack-k8s/artifacts/fresh-evaluation-calibrated-2026-10-26/operations
make graduation-fresh-dev-freeze FRESH_PROFILE="$S1_CAL_PROFILE" CAMPAIGN="$S1_DEV_CAMPAIGN"
make graduation-fresh-run CAMPAIGN="$S1_DEV_CAMPAIGN" LIMIT=1
make graduation-fresh-report CAMPAIGN="$S1_DEV_CAMPAIGN"
```

## 예산과 불변 조건

기존 bed `cloud-gcp-amd64-greenfield`, project `openstack-k8s`, zone `asia-northeast3-a`, override `/Users/hyeonseungkim/workspace/openstack-k8s/config/environments/local.env`를 사용한다. Controller e2-standard-4, source compute02 n2-standard-4, target/control-plane compute01 n2-standard-8, Kubernetes v1.35.7과 등록 flavor·이미지·배치를 유지한다. 새 프로젝트/bed·유료 전환·현금 초과 지출은 하지 않는다.

S1 baseline은 index 0–299의 고정 첫 60초다. 좋은 창 탐색·warmup 추가·부하 축소는 없다. 총 1800초, 주입 뒤 H1200+30초, bin20초·bad .05·선형 p95·최종120초를 유지한다. 과거 burst의 원인은 미확정이다. 후속 baseline 실패는 보존하고 주입하지 않으며 SLO를 유리하게 바꾸지 않는다. V1은 전용 100ms·상대배율 1.5를 그대로 검증한다.

종료 마감은 **2026-10-29 00:00 KST**다. 마지막 새 case는10/28 21:00 미만, 주입22:00 미만, drain23:00, down 개시23:30이며 누적44h 신규 중지/48h 한도를 유지한다. Cold ensure3600·fixture1800·adapter5400·cleanup1800·down1800·host headroom10800초와 예약 gate도 유지한다.

신규 작업146234원/정리40000원이다. 사용자 제공 잔액186234원(10/26 17:10 KST)은 실시간 Billing 값이 아니다. 원장의20000원 reserve를 다시 더하거나 estimate를 잔액에서 중복 차감하지 않는다.

**정상 보정 25분 관측은 완료했다. 미래 시간에 다시 추가하지 않는다.** 남은 DEV122분+preparation372.8분+main1508.8분은 총2003.6분(33시간23.6분)의 기존 계획이며 실측 보장이 아니다. 현재 원장·시각으로 재산정하고 DEV 후/전체 pilot 후에도 미실행분만 다시 계산한다. 자동 연장이나 무단 범위 축소는 없다.

중단 시 소유 cleanup을 먼저 확인한다. Worker auto/1·cluster/MD UID·소유 namespace/VM·taint·MHC·QoS/volume 복원을 검증하기 전 down하지 않는다. 기존 persistent320GiB 디스크와 snapshot14개는 보존한다. Raw·비밀정보는 커밋하지 않고 `type: 한국어 제목`과 변경 bullet·검증 본문을 포함한다. A 실제 restart·V1 조건·S2~S4 효과는 현재 계속 미검증이다.
