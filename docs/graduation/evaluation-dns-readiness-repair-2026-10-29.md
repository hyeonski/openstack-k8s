# DNS 준비 검사 복구 및 마지막 보충 인계

2026-10-29. 기준 경로: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/dns-probe-investigation-v11`.

## 결과 보존과 남은 범위

- 원본 main 29: 유효 21, 무효 8, 전부 종료·정리 완료.
- 이전 보충 10: 유효 7, 무효 3, 전부 종료·정리 완료. 원본 무효 8개 중 7개의 보충이 유효하게 완료됐다.
- 마지막 원본은 `s3-b02-m3600`. 다음 별도 ID는 `s3-b02-m3600-supplement03`, 순서 48이다. 다른 원본·보충·유효 미복구는 재실행하지 않는다.
- `closed-progress.json`은 전체 과거 campaign 및 attempt 해시를 검증한 집계다. 원본 유효 미복구 3개와 보충 유효 미복구 3개를 그대로 유지한다.

## 확인된 운영 원인과 복구

`s3-b02-m3600-supplement02`는 fixture 준비 중 DNS 검사에서 실패했다. 실험 adapter나 장애 주입에 진입하지 않았고, 워커 2→1 정리의 DNS 검사도 실패했다. 이미지 두 종류 모두 같은 경로에서 실패했으므로 이미지 차이는 원인으로 판정하지 않는다.

제어 노드가 있는 `osk8s-compute01`의 Neutron worker security-group IP set에는 삭제된 워커 `10.6.0.179`만 남고 현재 워커 `10.6.0.47`이 없었다. Neutron API와 compute02의 집합에는 현재 주소가 존재했다. 실제 패킷 관찰은 워커에서 IPIP DNS 요청 8개가 나갔지만 CP 게스트에는 도착하지 않았음을 보였다. 해당 ingress 규칙은 worker remote-group 집합을 참조한다. 캐시 불일치와 실제 차단 경로는 확인했지만, 최초 이벤트 누락/순서 뒤바뀜의 내부 RPC 원인은 확정하지 않는다.

compute01의 기존 `neutron_openvswitch_agent`만 재시작했다. 동일 컨테이너 ID, 동일 Neutron 보안 규칙을 확인했고 캐시는 현재 포트와 일치했다. 원래 DNS 준비 검사가 통과하고 해당 probe 소유 자원도 제거됐다(`agent-reconcile/result.json`). GCP 호스트·보안 정책·실험 장애·부하·H·SLO·판정은 바꾸지 않았다.

실패 당시 18개 파일은 `failed-attempt-initial-copy/`와 해시로 보존했다. 기존 실패 probe Pod를 증거 보존 후 소유권 검사로 정리하고 worker-control recover를 수행했다. 원래 attempt에 `resume-cleanup`만 실행하여 `VERIFIED`, `trial_valid=false`, `cleanup=true`로 봉인했다. 최종 24개 파일의 해시는 `closed-attempt-sha256.json`, 사본 보존과 주입 부재 확인은 `closure.json`이다. 실패를 성공으로 승격하지 않았다.

## 소스와 재검증

v10 source259 대비 과학·계측·장애·판정 코드와 설정은 byte 단위 동일하다. 새 source263은 마지막 보충03 게이트와 dispatch, 준비 probe 직전의 Neutron 캐시 가드, 원격 호출 등록부, 회귀 및 예산 추정만 변경한다. 기존 probe 본문은 선행 hook을 제거한 AST 비교로 불변이며, 기존 343개 원격 호출 정책도 유지한다(새 등록부 348개). 이전 main29 및 보충10의 판정/정리/증거 해시를 보존하고 마지막 원본 하나만 허용한다.

221개 fresh 회귀가 통과했다(`tests.json`, `tests.log`). 초기 신규 테스트는 보충 block 이름까지 원본과 같다고 잘못 가정하여 실패했고, 시나리오/모드의 동일성만 검사하도록 바로잡았다. 초기 실패 로그도 별도로 보존했다. 추가 worker-control/lifecycle 50개 테스트에서는 48개가 통과했고, 2개 오류는 수정 전 v10 frozen source의 임시 복사에서도 같은 테스트·같은 예외로 재현됐다. 하나는 옛 OwnedProbeReads AST 템플릿, 하나는 get/k mock 가정이다. 이번 변경의 새 회귀로 판정하지 않으며 `related-tests-baseline.json`과 양쪽 로그를 보존한다.

첫 1→2→1의 원래 DNS probe는 모두 통과했지만 삭제된 새 워커 `10.6.0.237`이 compute01 캐시에 남아 엄격 정합 검증이 실패했다. 수 분 뒤에도 남음을 확인하고 첫 검증 파일과 로그를 보존했다. 단회 재시작만으로 충분하다고 판정하지 않았다.

`scripts/lib/neutron_members.py`는 fresh 준비 probe 이전에 Kubernetes node/Nova host/Neutron SG 포트를 묶어 확인하고, 불일치가 있는 기존 agent만 한 번 재시작한다. 보안 규칙은 바꾸지 않는다. 측정 token 또는 미복원 clock guard가 있으면 차단한다. 재시작은 durable journal을 먼저 기록하고, 응답이 불명확하면 다시 보내지 않는다. 다음 호출은 실제 캐시·동일 컨테이너를 읽어 완료만 확인하거나 수동 복구를 요구한다. 전체 450초와 호출별 최대 45초 안에서 수행하며 기존 준비/정리 phase 한도를 늘리지 않는다.

새 실제 검증(`live-qualification-02`)은 UTC 04:13:17에 통과했다. 실제 잔류 캐시를 production hook으로 복구했고, 건강한 증설 단계는 재시작 없이 통과했으며, 축소 후 다시 남은 주소도 필요한 compute01 agent만 재시작하여 정리했다. 동일 보안정책에서 기존 워커 1→2→1 명령과 각 단계 원래 DNS probe, 양쪽 호스트의 worker/CP SG 멤버 정합, 최종 auto/1·소유 정리·동일 인프라 identity를 확인한다. 이 검증에는 실험 장애를 주입하지 않았다. `qualification.json`에 source263, runner 해시, 양쪽 SG 정합, 원래 probe 통과, auto/1 소유 정리 및 동일 환경 ID를 기록했다.

## 재개 상태

실제 증감 검증과 live admission이 완료되고 새 authorization/profile/freeze 및 인계가 기록되기 전에는 실행하지 않는다. 수정·검증 중에는 Astra가, 인계 수락 뒤에는 Sol이 단독 소유권을 갖는다. 최신 확정 상태는 `qualification.json`, `admission-readback.json`, `go-review.json`, `sol-handoff.json` 및 이후 실행 progress를 따른다.

## 비용과 종료

최신 사용자 표시 잔액 120,972원(수신 UTC 2026-10-28 22:43:37, 청구 cutoff 미확인)에서 이후 경과와 앞으로의 전체 작업만 차감한다. 기존 원장 비용을 중복 차감하지 않는다. 마지막 실험+종료 예약은 4,979초(약 83분; 새 캐시 검사 여유 600초 포함); 실제 준비/재검증 시간은 이후 경과로 갱신한다. 정리 40,000원, 기타 20,000원, 미확인 12시간 청구 지연 32,000원을 유지한다. 최신 수치는 `remaining-budget.json`이다. 현금·유료 전환·새 GCP 호스트는 승인되지 않았다.

Sol은 한 driver로 마지막 별도 회차를 실행하고 최종 증거·분석·보고, 소유 자원 정리, 동일 3개 VM 정지, 원장 종료, 시각 원설정 복원을 검증한다. 무효 원본/보충과 운영 버전을 분리 보고한다. 이 30분 heartbeat는 Astra만 관리하며, 모든 종료 조건 확인 후 삭제/비활성화한다. 이전 채팅은 archive하지 않는다.
