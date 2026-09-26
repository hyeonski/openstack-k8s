# S4 통합 실행·자동 분석 검증 (2026-09-26)

공통 환경 준비와 시나리오 실행은 분리한다. 이미 Ready인 환경에서는 `make graduation-s4-run`이 S4 fixture 준비, 단일 worker VM 정지, 서비스·용량 관측, 원본 분석, 소유 자원 정리를 한 번에 수행한다. 호스트가 정지된 환경에서 전체 과정을 실행하려면 `make graduation-s4-e2e`를 사용한다. 이 명령의 환경 단계는 기존 자원만 확인·기동하며, 종료할 때 **그 환경 실행이 기동한 GCP 호스트만** 중단한다. 독립 재분석은 호스트가 꺼져 있어도 `make graduation-s4-analyze`로 실행할 수 있다. 과거 실행은 `EVIDENCE_DIR=... make graduation-s4-analyze`로 선택한다.

분석기는 원본 `http.jsonl`의 **Nova stop 명령 직전 기록부터** 요청을 재집계한다. Kubernetes API 프록시 연결 실패와 Service 엔드포인트 부재를 분리하고 Node taint, Pod 퇴출·대체 Ready, MHC 삭제, 신규 worker HTTP 검사와 용량 안정화를 같은 UTC 시간선에 놓는다. 산출물은 각 실행의 `analysis/summary.json`, `http-requests.csv`, `infrastructure-timeline.csv`, `events.csv`, `report-row.csv`, `report-table.md`다. 원본 파일의 SHA-256을 결과에 남기고 원본 자체는 수정하지 않는다. 관측 공백·조회 오류·중단 후 재개 여부도 별도 표기한다.

## 독립 실험 비교

| 실행 | stop 이후 HTTP 성공/전체 | API 프록시 오류 / 엔드포인트 부재 | 첫 실패→첫 정상 응답 | Node 이상 판정 대기 | Pod 퇴출 대기 | `SHUTOFF`→worker 안정화 |
|---|---:|---:|---:|---:|---:|---:|
| [1차 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T025550Z-e022fb3e) `s4-e7a4fd084e56` | 197/226 | 7 / 22 | 71.515초 | 39.011초 | 30.000초 | 246.697초 |
| [2차 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T034042Z-3bd154aa) `s4-055ac54a8adf` | 191/221 | 7 / 23 | 73.413초 | 41.161초 | 30.000초 | 246.495초 |

두 실행 모두 Node 이상 판정 후 명시한 30초 toleration이 만료됐고, 새 Pod는 그 약 2초 뒤 Ready였다. MHC가 기존 Machine을 삭제하고 CAPO가 다른 Nova VM을 만든 뒤 worker 2대와 신규 worker HTTP 검사 Pod가 안정화됐다. 첫 실패→첫 정상 응답 값은 표본 간격과 5초 API 타임아웃의 영향을 받는 **관측값**이다. 검사 경로가 Kubernetes API Service proxy이므로 일반 사용자 ingress 중단시간이나 성공률로 해석하지 않는다. 두 번의 독립 성공은 경로 재현을 보여주지만 통계적 신뢰도나 모든 장애 조건의 성공률을 뜻하지 않는다.

1차 분석에서 초기에는 `SHUTOFF` 확인 **이후**의 요청만 세는 오류가 있었다. 4단계 분석기는 stop 명령 직전 기록을 기준으로 원본 전부를 재계산해 두 실행 모두 같은 규칙으로 비교한다. 1차의 이전 결과는 `result-original.json`으로 남아 있다.

## 검증 범위와 복원

국소 테스트는 통합 단계 순서, 이미 준비된 환경에서 불필요한 환경 단계를 건너뛰는 경로, 불확실한 장애 주입 시 소유 자원과 호스트를 강제로 정리하지 않는 경로, HTTP 오류 분류와 안정화 판정을 확인한다. 실환경에서는 `graduation-s4-e2e`로 준비→주입→분석→정리→호스트 종료를 **추가 명령 없이** 실행했다. workflow 실행 ID는 `s4-workflow-b55529d05af2`, 환경 실행 ID는 `env-38e5981ef9a2`다. 환경 준비 중 control-plane 게스트가 첫 안정화 검사에서 실패했지만 제한된 재시도로 무개입 복구됐다.

최종 `finalization.json`과 재분석된 `summary.json`에서 S4 fixture는 `restored`, worker 제어는 원래 `auto`·1대, 환경은 `stopped`였다. GCP controller와 compute 2대가 모두 `TERMINATED`로 확인됐다. 실환경 종료 시 workflow·S4 실험·분석 상태는 각각 `completed`·`completed`·`complete`였다.
