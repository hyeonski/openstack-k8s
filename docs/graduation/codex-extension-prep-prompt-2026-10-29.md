# Codex 작업 지시 — S2 분리 단독(S) 확장 실험 사전 수정 (2026-10-29)

워크스페이스: `/Users/hyeonseungkim/workspace/openstack-k8s`, 브랜치 `codex/fresh-evaluation-execution-20261026`.
**마감: 16:30 KST까지 아래 수정·검증·커밋·freeze 준비 완료.** 실험 실행은 이 문서의 범위 밖이다(8절은 실행자를 위한 인계 정보).

## 1. 목적과 배경

원래 main29와 보충11은 종료·봉인됐다. 평가 진단 결과 핵심 주장("두 계층 조치가 함께 필요하다", R2/R3)을 지금 설계로 식별할 수 없다. S2의 P는 K8s 분리(uploader를 다른 worker로 이동)와 Neutron QoS를 묶어 실행하므로 어느 조치가 API를 보호했는지 분리되지 않는다.

이를 보완하기 위해 **K8s 단독 ablation arm `S`**를 추가한다. S는 P와 같은 진단·같은 시점에 uploader를 옮기되 QoS를 적용하지 않는다. 오늘 22:00까지 결과 정리를 마쳐야 하므로 **재시도 없이 한 번에 끝나도록** 준비한다.

확장 계획(고정, 실행 전 변경 금지): `s2-x01-s`, `s2-x02-s`, `s2-x03-s`, `s2-x04-p`. 각 case는 1 attempt이며, P는 같은 날짜의 비교 기준점이다. 이 cohort는 별도 `purpose=extension`이고, 원래 main29나 보충을 대체하거나 그 표본에 합치지 않는다.

## 2. 이미 작성된 초안 (커밋 안 됨, 반드시 검토)

Claude가 아래 변경을 작업트리에 초안으로 남겼다. 그대로 쓰지 말고 검토하고 필요하면 고친다.

| 파일 | 변경 |
|---|---|
| `evaluation/fresh_scenarios.py` | `split_if_enabled`가 mode `P`/`S` 모두 분리를 수행한다. `set_rate`는 `P`에서만 호출한다. 분리 진입 조건도 `mode in ('P','S')`로 바꿨다. rate ladder는 기존대로 `P` 전용이다. |
| `evaluation/fresh_analysis.py` | S2 `scenario_checks`에 `mode=='S'` 분기를 추가했다. `split_only` = 최종 uploader node ≠ API node이고 포트 QoS 없음. |
| `evaluation/fresh_fake.py` | fake raw에서 S의 최종 uploader node를 n2로 둔다. |
| `evaluation/fresh_extension.py` (신규) | `freeze_extension`이 v11 profile을 변경 없이 쓰고, manifest에 위 4 case만 등록한다. stage는 `extension`이다. |
| `evaluation/fresh_campaign.py` | stage `extension`의 attempt cap을 1로 둔다. CLI에 `freeze-extension` 액션을 추가했다. |
| `config/fresh-read-registry.json` | `fresh_scenarios.py`의 source SHA와 call line 번호를 갱신했다. 원격 호출 집합과 정책은 동일하다(`audit()` 348 calls 통과). |
| `tests/test_fresh_extension.py` (신규) | synthetic freeze·run·판정, 1회 cap, S에서 QoS 미호출 AST 검사. 3개 통과. |

초안 상태에서 전체 `test_fresh*.py` 224개가 통과했다(기존 221개 + 신규 3개). 검토 후 수정하면 다시 실행한다.

## 3. 해야 할 수정·검증

1. **초안 검토.** S 경로가 P와 진단·타이밍·이동 대상(`b['node']`)·이벤트(`action_requested`/`action_applied`)에서 같고 QoS만 빠졌는지 확인한다.
   - S에서도 fixture가 QoS policy와 rule을 생성하지만 포트에는 붙이지 않는다. 기존 소유 정리가 이 미부착 상태를 정상 정리하는지 코드로 확인한다. `fresh_scenarios.py`의 owned-resource readback과 `qos-rule`의 6000 kbps ownership 검사를 볼 것.
   - 분석기의 `contract_valid`, `action_outside_horizon_or_without_request`, `uploader_offered_through_H`가 S에서 의도대로 동작하는지 확인한다.
2. **새 profile v12.** `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261029-dns-readiness-v11.json`을 복사해 `fresh-20261029-extension-v12.json`을 만든다. 바꾸는 것은 다음 두 가지뿐이다.
   - `operations.artifact_root` → `.../fresh-evaluation-measurement-repaired-2026-10-27/bed-extension-v12`
   - `operations.stability.credit_reference` → 새 credit 파일 경로와 sha256. 새 파일은 기존 `latest-credit-20261029T074337KST.json` 형식을 따른다. 사용자 보고 원문은 "₩320,850 / ₩435,523 크레딧 사용됨"(2026-10-29 14:40 KST 무렵)이고, total 435523, used 320850, displayed_remaining 114673이다. cleanup 40000원, 기타 20000원 reserve는 유지한다.
   - 과학적 값(SLO·H·부하·bin·정책·fault·timers)과 host identity는 바꾸지 않는다. `fresh_campaign.py validate --profile <v12>`와 `forward_credit(profile, 4*37*72+1500)['margin_krw']>0`을 확인한다.
3. **측정 코드는 바꾸지 않는다.** 벽시계 기반 지연, bin 판정, 회복 정의를 그대로 둔다. 기존 P/M과 비교 가능해야 한다. 시계 문제는 clock guard로 막는다.
4. **확장 분석 스크립트.** `evaluation/fresh_extension_analysis.py`를 만든다. 읽기 전용이다.
   - 입력: extension campaign과 기존 원래 main S2 유효 P/M(그리고 `s2-b03-p-supplement01`, 별도 표시).
   - 출력 항목:
     - 조치 시점(`action_applied_seconds`, 없으면 `diagnosis_seconds`) 이후 SLO 위반율
     - H 전체 `service_slo_violation_fraction`
     - 실패율
     - 조건부 p95
     - 불건강 bin 수
     - upload goodput(`upload_goodput_Bps`)
     - 기존 strict 판정 필드
   - S1에 대해서도 같은 조치 후 위반율 표를 만든다. 이 사후 분석이 원래 primary를 대체하지 않는다는 문구를 출력에 포함한다.
   - synthetic campaign으로 단위 테스트를 작성한다.
5. **전체 회귀.** `python3 -m unittest discover -s tests -p 'test_fresh*.py'`가 모두 통과해야 한다. localhost bind 테스트는 sandbox 밖에서 재실행한다.
6. **커밋.** 기존 컨벤션(`type: 한국어 제목` + 변경 bullet + 검증 본문)을 따른다. raw와 비밀정보는 넣지 않는다. 커밋 후 `git status`가 깨끗해야 freeze가 source hash를 고정할 수 있다. `docs/graduation/fresh-evaluation-final-results-2026-10-29.md`(미추적)도 함께 커밋할지는 사용자에게 묻지 말고 별도 docs 커밋으로 포함한다.
7. **실행 전 점검 스크립트(읽기 전용).** `evaluation/fresh_extension_preflight.py`를 만든다. 확인 항목:
   - clock guard 서비스 상태(`/var/db/openstack-k8s-clock-guard/state.json` status가 `restored` 또는 `idle`, 활성 lease 없음)
   - `pmset` sleep 방지
   - 실행 중 evaluation 프로세스와 lock 부재
   - 공유 원장의 열린 세션 부재
   - 3 VM TERMINATED
   - source가 커밋과 동일
   - v12 validate와 forward credit
   - 결과를 JSON으로 남긴다. mutation은 하지 않는다.

## 4. 하지 말 것

- 원래 main29, 보충, 준비 실험의 원자료·판정·manifest를 수정하지 않는다.
- 기존 release/authorization 체인(transport/stability/dns release)을 새로 확장하지 않는다. 이 확장은 독립 extension campaign이다.
- profile의 과학적 값, 분석기 판정 규칙, 기존 contrast 등록을 바꾸지 않는다.
- 클라우드 기동, 장애 주입, VM 조작은 하지 않는다(실행은 별도 지시).
- 시간을 맞추려고 테스트를 건너뛰지 않는다. 실패하면 원인과 함께 즉시 보고한다.

## 5. 완료 보고

다음을 간결히 보고한다.

- 커밋 SHA
- 변경 파일
- 테스트 수와 결과
- v12 profile 경로와 SHA
- credit 파일 SHA와 forward margin
- preflight 결과
- S가 P와 다른 점(QoS 미적용) 외에 남은 차이가 없다는 확인 근거
- 미해결 위험

## 6. 실행자 인계 정보 (참고 — 수정 단계에서 실행하지 않음)

시간 gate(KST):

| 시각 | 할 일 |
|---|---|
| 16:30 | ensure |
| 17:00 | 첫 case |
| **19:50 이후** | 새 case 시작 금지 |
| 20:40 | down 완료 |
| 22:00 | 결과 정리 마감 |

순서:

1. `fresh_campaign.py environment-ensure --profile <v12> --campaign <v12 root>/operations`
2. `freeze-extension --profile <v12> --campaign <v12 root>/s2-extension`
3. `run --limit 1`을 case마다 순차 실행하고, 각 case 후 판정과 cleanup을 확인한다.
4. `environment-down`, 원장 종료, 시각 원설정 확인

실패 정책: **재시도·현장 source 수정 없음.**
- 하네스 오류가 나면 `resume-cleanup --case`로 소유 정리만 하고 무효를 보존한다.
- 정리가 검증됐고 19:50 전이면 다음 case로 진행한다.
- 정리 실패나 비용 gate 실패면 중단하고 down한다.

환경변수 `ENV_OVERRIDE_FILE`, `ENVIRONMENT_NAME`, `GCP_PROJECT_ID`, `GCP_ZONE`, `STATE_DIR`는 기존 driver(`evaluation/fresh_release_driver.py`)가 설정하던 값과 동일하게 맞춘다.
