# 환경 준비·상태 조회·능동 검사 분리 검증

- 작성일: 2026-09-11
- 설계: [ADR-0016](adr/0016-separate-observation-and-enable-worker-scale-in.md)
- 과거 결과: [2026-08-24 기준선](gcp-validation-baseline.md), 당시 환경과 구분

## 실행 책임

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
scripts/gcp-management-cluster.sh tunnel
scripts/gcp-workload-api-tunnel.sh ensure
make workload-cluster-prepare
make workload-cluster-status WORKERS=1
make workload-cluster-verify WORKERS=1
make workload-cluster-probe
```

transport와 prepare는 구축 또는 명시적 구성 변경 단계에서 실행한다.
status/verify는 기존 kubeconfig와 연결을 사용하며 터널·설정·시험 자원을 만들지 않는다.
정지된 GCP 호스트를 임의 기동하지 않는다. 조회 실패 후 자동 recovery를 호출하지 않는다.

| 판정 | 직접 종료 코드 | 처리 |
|---|---:|---|
| ready | 0 | 상태·구성 일치 |
| preparing | 10 | 생성·삭제·rollout 등 예상 전이, verify는 제한 시간 내 재조회 |
| mismatch | 20 | 설정 불일치 기록, 자동 patch 없음 |
| unavailable | 30 | 조회 오류 보존, 빈 자원 목록으로 대체하지 않음 |
| timeout | 40 | 마지막 관측·기존 진단 자료 보존 후 종료 |

기본 수렴 제한은 3,600초다. Make의 nonzero 종료 코드만으로 상세 상태를
구분하지 않으며 artifact의 `result.json`을 함께 확인한다.

능동 검사는 management namespace의 API TCP probe, 각 Node의 CNI/DNS probe,
클라이언트의 API readyz로 구성한다. 실행별 이름·소유 label·UID를 사용하고
성공 시 JSON/events/log를 저장한 뒤 UID 조건으로 삭제한다. 실패 Pod는 남긴다.
이전 시험 자원은 소유권과 증거를 확인한 뒤 정리하며, 소유 표시 없는 과거 Pod는
이름만으로 삭제하지 않는다. 진행 중인 증감과 별도 능동 검사를 동시에 실행하지 않는다.

## 확인한 결과

- 로컬 상태·소유권 회귀 검사: 준비 중·drift·조회 불가·시간 초과 구분
- Machine/OSM/Node/Nova identity·ACTIVE, Calico 전체 Node coverage 검사
- 조회 중 명령이 읽기 전용인지 확인, UID 조건부 삭제 및 증거 저장 실패 시 삭제 금지
- probe 실패 보존 및 성공 시 증거 저장 후 삭제 순서 확인
- 실환경 기준선: CP1+worker1, Calico 설정·generation 일치, API/CNI/DNS 통과
- prepare 전후 Calico spec/generation 동일: 기존 설정이 이미 의도한 구성임을 확인
- read-only verify 전후 동일 설정 및 workload Pod 11개 유지
- 별도 능동 검사 성공 후 실행 소유 Pod 삭제 및 증거 보존

실환경 확인은 전체 변경의 최종 트리에서 수행했으며, 이 중간 커밋만을 배포한
결과로 표현하지 않는다. master 증거는
`artifacts/cloud-gcp-amd64-greenfield-20260911T084859Z-40405/`에 보존했다.
이 커밋의 별도 임시 트리에서 `make lint`: 43개 테스트·셸 구문·ShellCheck·GCP-only 검사 통과.
의도적인 Calico drift·강제 timeout은 실환경에 주입하지 않았으며 관련 분류는
로컬 회귀 검사로 확인했다. 고객 HTTP 요청의 무중단 처리는 검증하지 않았다.
