# Worker 제어권 운영

이 저장소가 지원하는 worker MachineDeployment 제어 모드는 다음 두 가지다.

| 모드 | CA 상태 | worker 수 변경 |
|---|---|---|
| `auto` | CA 1 replica Available | CA가 Pod requests에 따라 1~3대를 조정한다. 수동 증감은 CA를 잠시 중지하고 작업 후 원래 상태로 복원한다. |
| `fixed` | CA 0 replica, Pod 없음 | `workload-cluster-scale WORKERS=1..3`만 worker 수를 변경한다. 수동 증감 후에도 CA는 중지 상태다. |

처음 `cluster-autoscaler-install`을 실행하면 `auto`로 기록한다. 기존 설치를 처음
관리할 때 CA가 1 replica Available이면 `auto`로 채택한다. CA가 이미 0이거나
정상 상태가 아니면 과거 수동 작업 중단과 의도적인 중지를 구분할 수 없으므로
자동 채택하지 않는다.

```bash
make cluster-autoscaler-control-status
make cluster-autoscaler-mode MODE=fixed
make workload-cluster-scale WORKERS=2
make cluster-autoscaler-mode MODE=auto
make cluster-autoscaler-test
```

모드 변경은 MachineDeployment가 안정적이고 저장소 소유 시험 자원이 남아 있지
않을 때만 진행한다. 남아 있다면 먼저 `make cluster-autoscaler-test-cleanup`으로
증거를 보존하고 정리한다. 자동 시험은 `auto`에서만 실행한다. `fixed`로 전환한
뒤의 `cluster-autoscaler-verify`는 CA 1 replica를 요구하므로 실패하는 것이 정상이다.

제어 기록은 `.state/<환경>/worker-control.json`, 진행 중인 변경 기록은
`worker-operation.json`에 원자적으로 저장한다. 로컬 파일 잠금은 수동 증감,
자동 시험, 시험 정리, 모드 변경, CA 설치 사이의 중복 실행을 막는다. 하위 셸에도
잠금 파일을 전달해 상위 실행기만 종료된 경우에도 셸 작업이 끝날 때까지 잠금을
유지한다. 기록에는 클러스터·MachineDeployment·CA UID를 저장한다.
클러스터 생성·삭제와 능동 probe의 공개 진입점도 같은 잠금을 사용한다.

자동 시험의 외부 명령은 잠금 FD를 가진 별도 감시기가 실행한다. 실행기
SIGKILL은 부모 생존 pipe의 종료로 감지하며, 감시기가 하위 명령을 종료·회수한
뒤 잠금을 놓는다. 명령 시간 상한도 감시기가 독립적으로 유지한다.
수동 증감 셸은 성공·실패 모두 CA를 중지한 상태로 반환하며, 성공 시 Python
제어기가 UID와 목표 MD 수렴을 확인한 뒤 원래 CA 상태를 복원한다. 실패나 신호
중단에서는 journal과 중지 상태를 보존하고 `control-recover`가 같은 확인을 수행한다.

실행 중단 뒤 다음 변경 명령은 먼저 진행 기록과 실제 MD·CA 상태를 대조한다.
MD가 안정적으로 수렴한 뒤에만 원래 CA 상태를 복원하거나 모드 전환을 완료한다.
명시적으로 확인하려면 다음을 실행한다.

```bash
make cluster-autoscaler-control-status
make cluster-autoscaler-control-recover
```

MD가 아직 수렴하지 않았거나 UID·replica 수가 기록과 다르면 명령은 중단하고
기록을 보존한다. 이 경우 상태·이벤트·artifact를 확인한 뒤 다시 복원 명령을
실행한다. 복원은 **제어권**을 회복하는 작업이며 중단된 수동 증감의 성공 판정은
아니다. 이후 `workload-cluster-status`, `workload-cluster-verify`, 필요 시
`workload-cluster-probe`로 worker와 통신 상태를 별도 확인한다.

`workload-cluster-create`는 기존 CA 설치가 있으면 재적용을 거부한다. 초기
manifest가 MachineDeployment replicas를 1로 되돌릴 수 있기 때문이다. CA 설치도
`fixed` 또는 미복원 상태에서 CA를 임의로 켜지 않는다.
`workload-cluster-destroy`가 성공하면 로컬 제어 모드 기록을 제거한다. 기존
삭제 범위대로 CA Deployment 자체는 삭제하지 않는다.

현재 제어권은 **한 운영 클라이언트의 로컬 상태와 잠금**을 기준으로 한다. 다른
운영 클라이언트와 직접 `kubectl` 변경은 이 잠금에 참여하지 않는다. 여러
클라이언트를 허용할 때는 클러스터 단위 잠금/제어권을 추가해야 한다. 앞으로
worker 복구 실행기를 도입하면 같은 제어권 규칙에 연결해야 한다.

## 최종 검증 기록

수동 실패 후 CA 중지 유지, 명시적 복구, fixed/auto 전환, 실제 변경 명령 중 SIGKILL과 전체 증감 재개 결과는 [2026-09-24 종합 검증](foundation-priority1-final-validation-2026-09-24.md)에 있다.
