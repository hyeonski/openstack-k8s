# S4 5단계 통합 검증 (2026-09-26)

## 실행 경계

공통 환경과 S4 시나리오는 독립 실행할 수 있다. 호스트 3대가 `TERMINATED`인 상태에서 `graduation-env-ensure`로 **기존** 호스트와 게스트를 회복했고, 환경 실행 `env-e1e936b809fd`가 `ready`가 된 뒤 `graduation-s4-run`만 호출했다. 상위 workflow `s4-workflow-f02d8106c5c3`의 모드는 `scenario`이고 `ensuring-environment` 단계 없이 준비→주입→관측→분석→정리를 완료했다. 시나리오 종료 당시 환경은 `ready`로 남았으며, 별도 `graduation-env-down`으로 이번 환경 실행이 켠 호스트 3대만 중지했다.

정상 환경에서 `graduation-env-ensure`를 한 번 더 실행한 결과, 동일 환경 실행 ID와 `started_hosts` 소유권을 유지하고 실제 호스트·클러스터 상태만 조회해 약 8초 만에 종료됐다. 이 경로는 SSH 대기, OpenStack 복구, 게스트 시작 루틴을 다시 호출하지 않는다. 상태 검사가 실패하면 기존 복구 경로로 돌아간다.

## 세 번째 독립 실험

원본: [S4 실행 디렉터리](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3). 실행 ID `s4-ec4f3851e726`, 원본 기반 [분석 요약](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3/analysis/summary.json), [보고서 표](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T041611Z-c2b2e5c3/analysis/report-table.md).

| 항목 | 관측값 |
|---|---:|
| Nova stop intent 이후 HTTP 성공/전체 | 182/212 |
| API Service proxy 연결 실패 / Service 엔드포인트 부재 | 8 / 22 |
| 첫 HTTP 실패→첫 정상 응답 | 78.649초 |
| 첫 실패→Node 이상 판정 | 46.474초 |
| Node 이상 판정→Pod 퇴출 | 30초 |
| Pod 퇴출→대체 Pod Ready | 1초 |
| `SHUTOFF` 확인→worker 용량 안정화 | 245초 |

실험·분석 상태는 각각 `completed`·`complete`이며, 인프라 스냅샷 조회 오류와 중단 후 재개 공백은 없었다. HTTP 표본 시작 간격 2.5초 초과 구간은 8개였다. 이 HTTP 경로는 Kubernetes API Service proxy이므로 78.649초를 일반 사용자 ingress의 중단시간으로 해석할 수 없다. 1·2차 결과와 비교하면 [이전 통합 검증](s4-automated-validation-2026-09-26.md)의 첫 실패→성공 71.515초·73.413초, 용량 안정화 246.697초·246.495초와 같은 범위의 재현 사례다. 표본 3회는 성공률의 통계적 추정치가 아니다.

## 중단·재개와 최종 정리

상위 실행기에 `make graduation-s4-resume`을 추가했다. `stop-intent`가 같은 환경·실험 기록에 있을 때에만 개별 실험의 `observe`로 이어지며 **Nova stop을 재호출하지 않는다**. 관측 중단으로 표본 공백이 생기면 분석의 `incomplete`를 보존하고, 다른 오류가 없고 서비스·용량 회복 증거가 충분한 경우에만 workflow를 `completed_with_gap`으로 표시한다. 불확실한 stop 결과나 다른 실행 ID는 거부한다. 정리 중단 시에는 이미 제거한 자원을 다시 소유권 확인하며 정리하고, 호스트 종료 중단 시에는 소유 호스트만 재대조한다.

이 재개·거부·중단 단계는 외부 명령 대역 테스트로 검증했다. **실환경에서 의도적으로 장애 실험 프로세스를 중단해 재개한 것은 아니다.** 실환경 통합 검증은 중단 없는 독립 3차 실행이며, 재개 경로의 실제 장애 후 동작은 최종보고서 전 추가 검증 대상으로 남긴다.

정리 후 S4 fixture는 `restored`, worker 제어는 원래 `auto`·1대, 환경 기록은 `stopped`다. GCP controller·compute 2대 모두 최종 `TERMINATED`로 확인됐다. 시나리오의 `finalization.json`은 해당 시나리오 종료 시점에 환경이 `ready`였음을 기록한다. 별도 환경 종료의 최종 상태는 `graduation-environment.json`에 남는다. `make lint`와 단위 검사는 최종 코드로 다시 실행한다.
