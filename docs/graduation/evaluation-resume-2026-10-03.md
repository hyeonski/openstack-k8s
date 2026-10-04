# 반복 평가 중단·재개 이력

**2026-10-04 06:37 KST에 전체 평가와 자체 검증을 마감했다.** 예정 34건 모두 종료됐고, 32건은 시험별 수용 조건을 통과했다. 미완결 2건은 무효 기록으로 유지했다. 실제 GCP 조회에서 소유 호스트 3대 모두 `TERMINATED`, 실행기 없음, 최종 대조 14개 항목 통과를 확인했다. 현재 `campaign.json`은 `reviewed-with-exceptions`이며 재개할 `pending`은 없다. 최신 결과는 [반복 평가 결과](final-evaluation-results-2026-10-03.md), 최종 근거는 평가 디렉터리의 `final-closure-verification.json`과 `environment-final.json`을 따른다.

아래는 2026-10-03 18:34 KST의 과거 중단 지점과 당시 준비한 재개 절차를 보존한 기록이다. 사용자가 1·2·3번 작업과 자체 검증의 재개를 요청해 같은 날 21:07 KST에 재개했으며, 이후 남은 시험을 모두 수행했다. 아래의 남은 수와 다음 실행은 당시 기준이다.

당시 사용자 요청: “지금 하던거까지만 하고 나중에 다시 시작할 수 있게 정리해줘”. 이에 S3 준비 오류 복구를 완료한 경계에서 중단했다.

## 당시 재개 위치

- 평가: `graduation-evaluation-20261002T124843Z-9e04aebf`
- 다음 예정 실행: **`s3-automatic-02` — S3 자동 복구 2회차**. 이 실행의 본 측정과 장애 주입은 아직 시작되지 않았다.
- 전체 34건 중 14건의 시도가 종료됐다. 12건은 수용 조건 및 독립 검증을 통과했고, 2건은 연결 오류로 무효인 측정 기록을 보존했다. **남은 20건은 재개 대기**다.
- 12건에는 정상 시험 7건, 유효한 무조치 비교 1건, 의도된 거절 시험 3건, 중단·재개 시험 1건이 포함된다. 이를 모두 자동 복구 성공률로 합산하지 않는다.
- 수치와 한계는 [반복·비교 평가 결과](final-evaluation-results-2026-10-03.md), 실행 조건은 [고정 실행 계약](final-evaluation.md)을 따른다.

## 이번에 마친 정리

`s3-automatic-02`의 워커 준비 중 management API TLS 연결 시간이 초과됐다. 이후 직접 조회에서 동일한 클러스터·MachineDeployment·Autoscaler 식별자, 안정적인 워커 1대, 정지된 Autoscaler를 확인했다. 새 S3 namespace나 측정 기록은 없었고 이전 S3 기록은 이미 정리된 상태였다.

소유 워커 작업 기록을 복구하고 `auto` 모드·워커 1대로 복원했다. 네 시나리오 namespace 부재, 시험용 taint 부재, 이전 S3 기록 불변, worker operation journal 제거, 준비 오류 로그 보존을 확인했다. 준비 단계의 중단이므로 같은 예정 실행을 `pending`으로 되돌렸으며, 측정 실패를 성공으로 대체한 것이 아니다.

18:06:56 KST의 로컬 `Software Sleep` 기록이 오류 시점과 겹친다. 관련 로그는 보존했지만 연결 오류의 유일한 근본 원인으로 단정하지 않는다. 재개 시 전원을 연결하고 맥이 수동 절전이나 덮개 닫기로 잠들지 않는 상태를 유지한다. 실행 명령의 `caffeinate -i`는 자동 유휴 절전을 억제하지만 수동 절전까지 막지는 않는다.

2026-10-03 **18:34:31 KST** 최종 대조에서 호스트 3대 모두 `TERMINATED`, 실행기 없음, 중단 지점 검증 13개 항목 통과를 확인했다. `campaign.json`은 `paused-by-user`로 저장했다. 근거는 아래 평가 디렉터리의 `checkpoint-verification-02.json`이며 `safe_checkpoint_verified=true`다. 일시 중단용 환경 스냅샷은 `environment-paused-20261003T093431Z.json`이며, 전체 평가 완료를 뜻하는 `environment-final.json`으로 사용하지 않는다.

## 당시 준비한 재개 절차 — 이미 수행됨

아래 명령은 과거 중단 지점을 위한 기록이다. 이번 평가의 재개는 이미 완료됐으므로 다시 실행하지 않는다.

1. `campaign.json`이 `paused-by-user`이고 첫 `pending`이 `s3-automatic-02`인지 확인한다. 실행기 중복 프로세스와 `worker-operation.json`이 없어야 한다.
2. 아래 명령으로 기존 평가를 이어간다. 동일 실행기가 환경 기동, 터널 준비, 각 시험, 정리, 독립 검증을 순차 처리한다. 새 평가 집합을 만들거나 완료된 시험을 다시 실행하지 않는다.

```bash
cd /Users/hyeonseungkim/workspace/openstack-k8s
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
caffeinate -i bash -c '
  set -a
  source scripts/lib/common.sh
  set +a
  export PROJECT_ROOT STATE_DIR
  python3 -u artifacts/cloud-gcp-amd64-greenfield/graduation-evaluation-20261002T124843Z-9e04aebf/analysis/continue-and-verify.py "$PROJECT_ROOT/artifacts/cloud-gcp-amd64-greenfield/graduation-evaluation-20261002T124843Z-9e04aebf"
' >> artifacts/cloud-gcp-amd64-greenfield/graduation-evaluation-20261002T124843Z-9e04aebf/analysis/continuation.log 2>&1
```

3. 새로운 오류가 나면 원본과 실제 자원 상태를 확인한다. 본 측정이 시작된 실패는 원래 시도와 분모에 남기고 임의 재실행으로 대체하지 않는다. 본 측정 전 준비 실패는 소유권·정리 확인 및 별도 기록 후 같은 예정 시험의 준비를 재개할 수 있다.
4. 완료된 시험마다 원본 검증과 image consistency를 확인한다. 마지막에는 전체 검증, 보완 검토, 결과 문서 갱신 및 소유 호스트 종료를 확인한다. 무효 측정 2건 때문에 원래 verifier의 전체 성공 여부는 거짓으로 남을 수 있으며, 기록 검토 통과와 구별한다.

고정 실행본 144개 파일과 환경 override의 SHA-256은 유지한다. 조건이나 실행 코드를 바꾸면 같은 반복 집합으로 합산하지 않는다. 복구용 단발성 `reconcile-*.py`는 이미 실행했으므로 재실행하지 않는다. 터널이 필요한 수동 복구는 터널 준비와 실제 작업을 같은 실행 세션에서 수행한다.

## 보존한 기록

근거 디렉터리: `artifacts/cloud-gcp-amd64-greenfield/graduation-evaluation-20261002T124843Z-9e04aebf/`.

- `campaign.json`, `independent-verification.json`, `bundle-review.json`, `outcome-counts.json`: 예정 시도, 원본 재검산, 보완 검토, 실패를 포함한 분모.
- `checkpoint-verification-02.json`, `analysis/pause-request-02.json`, `analysis/pause-02-environment-stop.log`: 이번 중단 요청과 종료 확인.
- `cases/s3-automatic-02/preparation-interruption-01.json`, `preparation-interruption-independent-check.json`, `preparation-cleanup-snapshot-01.json`: 본 측정 미시작과 복원 근거.
- 같은 case 디렉터리의 `prepare-before-reconciliation-01.log`, `local-sleep-wake-20261003.log`: 원래 준비 실패와 절전 기록.
- `failed-attempt-verification.json`, `s2-failed-attempt-verification.json`: 무효 측정 2건의 원본 보존 및 정리 검증. 유효 성능 측정으로 재분류하지 않는다.

당시 남은 순서: S3 자동 2회차 → S4 정상 2회차 → 3·4·5회차의 S1 자동/무조치, S2 고정/동적 비교, S3 자동/런북, S4 정상. 이후 고정된 `campaign.json` 순서대로 모두 수행했다.
