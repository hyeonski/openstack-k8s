# Architecture Decision Records

이 디렉터리는 현재 GCP 전용 테스트베드의 유효한 기술 결정을 기록한다. 이전
실행 환경의 ADR과 검증 보고서는 GCP-only 전환 커밋 이전 Git 이력에 보존한다.

| ADR | 결정 | 상태 |
|---|---|---|
| [0013](0013-use-gcp-as-the-only-runtime.md) | GCP AMD64를 유일한 실행 환경으로 사용한다 | 채택됨 |
| [0014](0014-run-management-capi-on-controller.md) | management kind와 CAPI/CAPO를 controller에서 실행한다 | 채택됨 |
| [0015](0015-require-layered-gcp-verification.md) | IaC부터 Autoscaler까지 계층별 GCP 검증을 요구한다 | 채택됨 |

결정이 바뀌면 기존 ADR을 수정해 과거 결론을 감추지 않고 새 ADR에서 대체 관계와
전환 조건을 기록한다.
