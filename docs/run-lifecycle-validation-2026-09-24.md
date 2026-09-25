# 기반작업 1-5 실환경 검증 — 2026-09-24

이 문서는 최초 수명주기 검증 기록이다. 이후 SIGKILL 명령 격리 수정과 관측 수용 시험을 포함한 결과는 [1순위 종합 검증](foundation-priority1-final-validation-2026-09-24.md)에 별도로 기록한다.

## 범위와 코드

단일 운영 클라이언트의 worker 자동 증감 시험에 실행 상태·취소·재시작 후 대조·
정리 후 재측정·전체 시간 상한을 추가했다. 사용법과 보존 정책은
[실행 수명주기](run-lifecycle.md)를 따른다. 고객 실행 격리와 분산 실행 관리는
이 검증의 범위 밖이다.

실행 기록은 `artifacts/lifecycle-validation-20260924/`에 저장한다.
`code-sha256.txt`는 실환경 시험 시작 전의 실행 코드 해시다. 로컬 `make lint`는
최초 77개 테스트를 통과했고, 실환경에서 발견한 신호 처리 버그와 증거 반출 경로를
보완한 신호 수정 코드는 80개 테스트, Python 컴파일, 셸 구문·ShellCheck를 통과했다.

## 실환경 준비에서 확인한 사항

- 시작 전 GCE controller·compute01·compute02는 모두 `TERMINATED`였다.
  3대를 기동하고 기존 OpenStack 및 현재 CAPI workload VM만 복구했다.
- 최초 IaC plan은 관측 서비스 계정을 제거하려 했다. 해당 연결은
  `observability/gcp-setup.sh`가 관리하므로 foundation의 `ignore_changes`에
  `service_account`를 추가했다.
- 기존 controller state에는 이미 제거된 Ops Agent 정책 label 기록이 남았다.
  state를 백업하고 controller를 동일 GCP ID로 다시 import했다. 재등록으로 드러난
  confidential-compute 비활성 옵션의 absent/false 차이를 선언에서 해소했다.
  검토한 saved plan에서 `terraform_labels`만 바뀌는 것을 검사한 뒤 관리 label
  기록만 동기화했다. VM 교체·삭제는 없었고 최종 plan은 **No changes**였다.
  상태 백업은 기존 state 옆 `.before-lifecycle-reimport` 파일에 보존했다.
- controller→compute SSH와 두 compute의 실제 nested kernel boot를 통과했다.
- OpenStack 게스트 생성·부팅과 compute 두 대에서 Keystone/임시 API 접근을 확인하고
  검증 게스트를 정리했다. Kolla 설정 검증도 통과했다.
- management kind와 CAPI/CAPO/ORC, application credential 인증을 통과했다.
- workload API 터널이 실행 도구 세션 종료 때 사라져 초기 조회는 `unavailable`이었다.
  별도 세션에서 터널을 유지한 뒤 CP1+worker1 Ready와 API/CNI/DNS를 확인했다.
  이 연결 복구를 시험 성공으로 대체하지 않고 초기 실패 로그를 그대로 보존했다.
- 호스트 및 두 클러스터의 관측 수집기가 정상이며 시험 전 Cloud Monitoring/Logging
  조회는 `state=complete`, `missing=[]`였다. 이는 조회 범위의 자료 존재·최신성
  검증이며 모든 시계열의 끊김 없는 30분 연속성 검증을 의미하지 않는다.

## 수명주기 시험

최초 시험에서 60초 전체 시간 상한, 미완료 실행의 새 실행 차단, 명시적 정리,
실제 Deployment 생성 후 취소는 통과했다. 정리 중 SIGTERM 시험은 실행기가
종료되지 않아 **실패**했다. Python의 하위 프로세스 대기에서 `InterruptedError`가
EINTR 재시도로 취급될 수 있어, 별도의 `Cancelled` 예외로 변경했다. 실제
subprocess 대기 중 SIGTERM을 보내는 로컬 회귀 검사를 추가했다.

증거 저장도 임시 파일·fsync·원자적 교체로 변경했다. 교체 실패 시 기존 완전한
JSON이 남는 것을 테스트했다. GCS 반출은 전체 실행 ID/attempt 폴더로 구분하여
서로 다른 실행의 동일한 attempt 번호가 충돌하지 않게 했다.

최초 실패 실행은 `autoscaler-run-20260924T063826Z-1dd84a6b`이며 실패 기록을
덮어쓰지 않았다. 중단된 정리 실행기만 종료하고, 수정한 코드로 기존 실행을
대조·정리한 후 수명주기 시험을 다시 수행했다. 최종 시험의 독립 기록과
해시는 `artifacts/lifecycle-validation-20260924-final/`에 저장한다.

수정 후 시간 초과·중복 실행 차단·정리·Deployment 생성 후 취소와 정리 중
SIGTERM 기록을 통과했다. 이어진 재개에서는 아직 `ContainerCreating`인 Pod의
로그 조회가 BadRequest로 실패해 정리가 안전하게 중단됐다. 컨테이너별 상태를
확인하여 아직 시작하지 않은 컨테이너는 로그 부재 사유를 저장하고, 실행 중인
컨테이너의 로그와 재시작 대기 컨테이너의 이전 로그는 개별 수집하도록 보완했다.
실행 중 컨테이너의 실제 로그 조회 오류를 무시하지 않는다.

컨테이너 로그 처리 보완과 아래 재개 기록 정렬 검사까지 **83개 로컬 테스트와 정적 검사**를 통과했다. 같은 실행
`autoscaler-run-20260924T070512Z-05ed7c21`의 재개 이후 기록은
`artifacts/lifecycle-validation-20260924-resume/`에 별도로 보존한다. 각 변경 전의
실패 기록과 해시는 남겨두며, 최종 자동 증감 실행 중에는 실행 코드를 고정한다.

재개 시 동일 이름으로 생성한 자원은 가장 최근 attempt의 UID와 대조하도록
기록 경로를 정렬한다. 파일시스템 열거 순서에 따라 오래된 UID를 선택하지 않는
회귀 검사를 추가했다. 최종 코드 해시는
`artifacts/lifecycle-validation-20260924-resume/final-attempt-code-sha256.txt`다.

attempt 2의 실제 Deployment 생성 직후 기록된 실행기 PID에 SIGKILL을 보냈다.
내구 기록은 `running`으로 남았고 새 실행은 미완료 실행을 이유로 거부됐다.
독점 잠금 아래 실제 자원을 대조한 `test-reconcile`은 `interrupted`를 기록했다.
같은 실행 ID를 재개해 이전 자원을 정리하고 attempt 3에서 전체 측정을 완료했다.
최초 실행의 만료 시각은 재개해도 2026-09-24 11:05:12 UTC로 유지된다.

## 최종 실행 결과

2026-09-24 09:03:17 UTC(18:03:17 KST)에 attempt 3과 전체 실행이 `passed`로
저장됐다. 전체 `1→2→3→2→1→2→1` 순서, 각 단계 안정화와 API·노드별 DNS,
새 worker IPAM 검사, 시험 Deployment 제거 후 최종 1대 상태를 통과했다.
각 축소에서 Machine·Node·OpenStackMachine·Nova VM·포트 회수와 control plane·
공유 자원 보존을 대조했다. 세 축소 단계에서 worker 1대씩 회수했다.

| 단계 | 통과 시각 (UTC) |
|---|---|
| 기준 1대 | 07:51:44 |
| 1→2 | 07:56:17 |
| 2→3 | 08:01:27 |
| 3→2 | 08:16:31 |
| 2→1 — 아래 수집기 배치 수정 포함 | 08:41:10 |
| 1→2 재확장 | 08:45:51 |
| 2→1 재축소 | 09:00:28 |
| 부하 자원 제거 후 최종 안정화 | 09:02:52 |

`artifacts/lifecycle-validation-20260924-resume/exercise.json`과
`validation-summary.json`이 최종 결과다. 실행기는 최종 코드 해시 6개와 모두
일치했다. 각 시도의 manifest/result와 원본 단계 증거는 전체 run 디렉터리에 남는다.

삭제 순간 Port가 조회 사이에 사라져 두 차례 Nova inventory 표본이 조회 불가였다.
다음 표본에서 회복해 상태 검사와 자원 회수를 통과했다. 최종 manifest는 이를
`missing_data: ["nova"]`로 유지한다. 관측 누락이 없는 실험이라고 주장하지 않는다.
HTTP 요청 연속성, 실제 CPU 성능·비용, 고객 코드 격리와 분산 실행은 검사하지 않았다.

## 관측 수집기가 축소를 막는 문제

attempt 3의 `1→2→3→2` 이후 `2→1` 단계에서 CA가 기존 worker를
`pod with local storage present: cluster-state-…` 사유로 제외했다.
관측 Deployment의 `emptyDir` 전송 대기열이 worker 축소를 막는 문제였다.
`observability/k8s-collectors.yaml`의 cluster-state를 고정 control plane에
배치하도록 nodeSelector와 해당 taint의 toleration을 추가했다. CA의 전역
local-storage 보호 정책은 변경하지 않았다.

수정은 attempt 3 실행 중 적용했다. 이동 전에 Collector 자체 지표로
export queue가 0임을 확인했고, 이동 후 control plane에서 단일 수집기 Pod가
Available임을 확인했다. 이 환경 수정은 실행 도중 개입한 사실로 기록하며,
전체 순서를 처음부터 동일한 환경에서 무개입 수행했다고 주장하지 않는다.
실행기 Python/shell 코드는 최종 해시와 동일하게 유지한다. 이후 축소·재확장·
재축소 결과로 수정된 배치에서 자원 회수와 재사용을 확인한다.

근거는 `artifacts/lifecycle-validation-20260924-resume/collector-placement-fix/`의
수정 전후 Deployment·Pod, 자체 지표, 패치, 서버 측 dry-run diff다.
workload의 diff는 비었으며 management의 diff는 동일 배치 제약 추가뿐이다.
management 수집기는 이미 단일 kind control-plane에서 동작하여 이번에 재시작하지
않았다. YAML의 배치 제약은 다음 선언 적용 시 management에도 반영된다.

## 최종 회귀·상태 확인

- 09:04:15 UTC에 실제 init 컨테이너가 실행 중이고 main 컨테이너가 대기 중인
  작은 Pod로 로그 오류를 재현했다. 기존 `--all-containers` 조회가 실패하는 것을
  확인한 뒤 컨테이너별 수집으로 init 로그·main 로그 부재 사유를 보존하고 소유
  Pod를 정리했다. 남은 시험 소유 자원은 없었다.
- 최종 workload 확인은 `ready: workers=1`이었다. 제어 상태는 `auto`, 미완료
  제어 작업 없음, worker stable, CA replicas/available 모두 1이었다.
- 최종 관측 조회 범위 08:35:10~09:05:10 UTC에서 `state=complete`, `missing=[]`를
  확인했다. 이 값은 수집 자료의 존재·최신성 검사이며 앞서 기록한 개별 Nova
  snapshot 누락을 없애거나 모든 시계열의 연속성을 보장하지 않는다.
- 검증 후 controller·compute01·compute02를 모두 중지했고 `TERMINATED`를 확인했다.
  기존 VM·기반 자원은 삭제하지 않았다. 종료 근거는 `final-host-stop.log`다.
- 근거: 재개 검증 디렉터리의 `pending-container-check/result.json`,
  `final-workload-verify.log`, `final-control-status.json`, `final-observability.json`.

## 증거 반출 기록

삭제된 수동 시험 worker `osk8s-workload-md-0-s7rz4-7f885`의 과거 로그 5건을
Cloud Logging에서 조회했다. 원본 응답은 최종 검증 디렉터리의
`deleted-manual-worker-logs.json`에 보존했다.

최초 취소 실행의 manifest/result 업로드는 자동 승인 검토에서 명시적인 반출
승인이 없다는 이유로 거절됐으며 당시 업로드하지 않았다. 이후 사용자가 기존
버킷으로 업로드하도록 명시적으로 승인하여, 2026-09-24 10:34:55 UTC에 최종
성공 attempt 3의 두 파일 업로드 및 다운로드 대조를 완료했다.

- 버킷: `gs://osk8s-724098042704-evidence`
- 경로: `cloud-gcp-amd64-greenfield/autoscaler-run-20260924T070512Z-05ed7c21/autoscaler-cycle-attempt-003/`
- `manifest.json`: 18,994 bytes, generation `1790246091433852`
- `result.json`: 1,074 bytes, generation `1790246092945635`
- 두 객체 모두 다시 읽어 로컬 원본과 바이트 단위로 일치함을 확인했다.
  `--if-generation-match=0`으로 기존 객체 덮어쓰기를 방지했다.
- 반출 검증 근거: `artifacts/lifecycle-validation-20260924-resume/gcs-publication/verification.json`.
  객체 메타데이터·다운로드 사본·SHA-256도 같은 디렉터리에 보존한다.

GCS에는 최종 attempt의 manifest/result 두 파일만 보관했다. 상세 진단, 이전 실패
및 재개 기록, 수집기 배치 수정 내역과 이 검증 문서는 로컬에 남는다.
manifest의 `missing_data: ["nova"]`도 수정 없이 업로드했다.

## 1-5 완료 기준 재확인

단일 운영 클라이언트의 자동 증감 시험 범위에서 완료로 판정한다. 실행 상태와
소유권 보존, 취소·전체 시간 제한, 미완료 실행 중복 차단, SIGKILL 후 실제 자원
대조와 정리 후 재측정, 정리 실패 별도 기록, 소유 시험 자원 제거 후 다음 실행
준비를 검증했다. 최종 코드는 실환경 시험 해시와 일치하며 83개 회귀 검사를
통과한 코드다. GCS 결과 백업과 3대 호스트 중지까지 완료했다.

이 판정은 고객 실행 격리·분산 제어의 완료나 1-4 관측 수용 시험 전체의 완료를
뜻하지 않는다. 수집기 배치 수정 중 개입과 Nova 표본 누락의 한계는 위 기록을 따른다.
