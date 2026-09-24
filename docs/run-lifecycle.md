# 실행 자원 수명주기 관리 (기반작업 1-5)

현재 범위는 단일 운영 클라이언트에서 실행하는 worker 자동 증감 시험이다.
고객 코드 실행, 분산 실행기, worker 장애 복구는 별도 작업이다.

## 실행과 복원

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

## 상태와 충돌 방지

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

## 상한과 보존

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
