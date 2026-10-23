# Worker 제어와 자동 증감 시험 운영

현재 지원 범위는 단일 운영 클라이언트다. [worker 제어](#worker-control)와
[시험 수명주기](#run-lifecycle)를 함께 확인한다. 졸업작품별 실행은 [문서 안내](README.md)를 따른다.

<a id="worker-control"></a>

## Worker 제어권 운영

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
않을 때만 진행한다. 미완료 실행이 있으면 `make cluster-autoscaler-test-status`로 ID를 확인하고
`make cluster-autoscaler-test-cleanup RUN_ID=<확인한-run_id>`로 증거를 보존하고
정리한다. 수명주기 기록이 없는 과거 시험 자원은 `RUN_ID` 없이 별도 소유권 검사를
거쳐 정리하는 경로를 사용한다. 자동 시험은 `auto`에서만 실행한다. `fixed`로 전환한
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
클라이언트를 허용할 때는 클러스터 단위 잠금/제어권을 추가해야 한다.
졸업작품 S1~S3는 기존 제어 경로로 `fixed`·worker 2대를 준비하고 종료 시 원래
모드·대수를 복원한다. S4도 이 경로를 사용하며 장애 주입·관측과 재개 중에는
`WorkerControl` 잠금을 유지한다. 실험별 잠금 범위가 다르므로 여러 시나리오의
동시 실행이나 다중 운영 클라이언트의 조정을 지원한다는 의미는 아니다.
시나리오별 절차는 [S1~S4 실험 운영](graduation/experiments.md)을 따른다.

### 최종 검증 기록

수동 실패 후 CA 중지 유지, 명시적 복구, fixed/auto 전환, 실제 변경 명령 중 SIGKILL과 전체 증감 재개 결과는 [2026-09-24 종합 검증](foundation-priority1-final-validation-2026-09-24.md)에 있다.

<a id="run-lifecycle"></a>

## 실행 자원 수명주기 관리 (기반작업 1-5)

현재 범위는 단일 운영 클라이언트에서 실행하는 worker 자동 증감 시험이다.
고객 코드 실행, 분산 실행기, worker 장애 복구는 별도 작업이다.

### 실행과 복원

실환경 프로필은 `ENV_OVERRIDE_FILE=config/environments/local.env`로 지정한다.

```bash
make cluster-autoscaler-test
make cluster-autoscaler-test-status
make cluster-autoscaler-test-cancel RUN_ID=<status에 표시된 run_id>
make cluster-autoscaler-test-reconcile RUN_ID=<run_id>
make cluster-autoscaler-test-resume RUN_ID=<run_id>
make cluster-autoscaler-test-cleanup RUN_ID=<run_id>
```

`test-status`는 로컬 기록만 조회한다. `test-cancel`은 실행 ID를 확인한 뒤
취소 요청을 원자적으로 기록하며 자원을 즉시 삭제하지 않는다. 실행기는 다음
검사 지점에서 종료한다. 진행 중인 외부 검증 명령에는 최대 300초 상한이 있다.
SIGINT/SIGTERM도 취소로 기록한다. SIGKILL 뒤에는 상태가 `running`으로 남을 수
있으므로 `test-reconcile`로 실제 자원을 대조한다.

재개는 같은 실행 ID와 소유권 아래에서 기존 시험 자원을 증거 저장 후 정리하고,
CA가 worker 1대로 수렴한 것을 확인한 다음 새 attempt로 전체 측정을 시작한다.
중간 측정 단계부터 계속하지 않으며 이전 attempt의 결과를 덮어쓰지 않는다.
실패 원인은 기존 결과에 남고, 새 attempt 성공과 구분된다. 만료된 실행은 재개할
수 없고 정리한 뒤 새 실행을 시작한다.

`.state/<환경>/experiment-run.json`은 최근 실행의 위치를 가리킨다.
`artifacts/<환경>/autoscaler-run-*/run.json`에는 실행 상태·고정 클러스터 UID·소유 ID·
시간 상한·시도 횟수·상태 이력이 원자적으로 저장된다. 이 두 기록과 artifacts를
함께 보존해야 재시작 시 소유권을 확인할 수 있다.

### 상태와 충돌 방지

`created → running → passed`가 정상 경로다. 취소/실패/시간 초과는 `cancelled`/`failed`/`timed_out`,
실행기 소실 뒤 대조는 `interrupted`로 기록한다. 정리는 `cleaning → cleaned`이며,
실패하면 `cleanup_failed`와 별도 증거 경로를 남긴다. 조회 불가를 정리 성공으로
처리하지 않는다. `passed`와 `cleaned`만 다음 새 실행을 허용한다.

worker 제어 잠금을 실행 전체에 유지한다. 미완료 실행이 있으면 새 시험·수동 증감·
모드 변경·CA 설치·클러스터 생성/삭제·능동 probe를 거부한다. 상태 확인과 명시적
복원/정리는 가능하다. 여러 클라이언트나 직접 kubectl 변경은 지원하지 않는다.

정리 전에 Cluster/MD/CA UID, control-plane 정체성, 저장된 시험 자원 UID를
대조한다. 다른 실행 소유 자원이 섞였거나 조회가 불가능하면 중단한다. 현재
실행의 label과 UID 조건으로만 Pod/Deployment를 삭제하며, worker VM은 CA/CAPI의
정상 축소로 회수한다. CP와 공유 Neutron 자원이 유지되는지도 확인한다.

### 상한과 보존

- 전체 실행 상한은 기본 14,400초(4시간), `RUN_TIMEOUT_SECONDS=60..28800`으로 지정한다.
  재개·정리 대기 중에도 최초 실행의 시계는 초기화하지 않는다.
- 새 실행 전 GCE 3대의 실제 시작 시각과 자동 STOP 설정을 조회한다. 요청한 실행
  시간과 15분 여유를 확보하지 못하면 시작하지 않는다. 정리는 별도 최대 40분,
  자동 STOP 2분 전 중 빠른 시각까지 제한된다. 부족하면 실패 기록을 남긴다.
- worker 1~3대, 시험 Deployment 1개·Pod 최대 3개를 유지한다. Pod CPU request/limit는
  시작 시 가용량에서 고정하고 메모리 limit는 각각 32Mi다. 능동 probe는 순차 실행한다.
- 각 attempt의 측정·실패 결과와 UID/time manifest, 별도 cleanup/reconcile 기록을 보존한다.
  로컬 증거와 기존 GCS 증거는 자동 삭제하지 않는다. 이 내부 인프라 시험의 정책은
  무기한 보존이며 고객 데이터의 보존 정책으로 사용하지 않는다.
- GCS 반출은 기존 `observability-publish-run RUN_DIR=<attempt 경로>`를 사용한다.
  전체 run 상태는 로컬에 남고, 허용된 attempt manifest/result만 반출한다.
  GCS 경로는 `<환경>/<전체 run ID>/<attempt 폴더>/`로 구분하므로 서로 다른
  실행의 `attempt-001`이 충돌하지 않는다. manifest의 `run_id`는 attempt 폴더 이름이며
  전체 실행은 상위 경로와 `workload_owner_id`로 구분한다.

실환경 검증 결과는 [2026-09-24 검증 기록](run-lifecycle-validation-2026-09-24.md)에서 실제 수행 범위와 한계를 확인한다.
