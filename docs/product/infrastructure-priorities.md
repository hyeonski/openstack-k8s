# 테스트베드 기반 운영 과제

기준: 2026-10-23 코드 구조와 2026-10-04 마감 평가 기록. 클라우드 상태를 새로 조회한 결과는 아니다.
현재 목적은 GCP의 OpenStack·Kubernetes 연동 테스트베드와 S1~S4 장애 실험이다.

## 유지할 기능 경계

| 영역 | 현재 역할 | 근거·진입점 |
|---|---|---|
| 기반 구축·운영 | GCP·Kolla·CAPI/CAPO·worker 증감, 기존 환경 기동·소유 자원 정리 | [루트 README](../../README.md), [운영 가이드](../operations.md) |
| 장애 실험 | S1 CPU 경합·재배치, S2 QoS, S3 DB/볼륨 복구, S4 VM 교체 관측 | [실험 운영](../graduation/experiments.md) |
| 반복 평가 | 조건 고정·반복·비교군·거절·중단 시험과 독립 검증. 필요 시 명시적으로 실행 | [평가 계약](../graduation/archive/first-evaluation-2026-10/final-evaluation.md) |
| 상시 관측 | OTel·GCP 지표/로그·GCS 반출. 실험의 직접 측정·로컬 원본 저장과 구분 | [관측 운영](../../observability/README.md) |

제어·관측·수명주기의 [기반 종합 검증](../archive/foundation-priority1-final-validation-2026-09-24.md)과
S1~S4 [최종 평가](../graduation/archive/first-evaluation-2026-10/final-evaluation-results-2026-10-03.md)는 당시 조건의 근거다.
단일 운영 클라이언트·고정 샘플의 결과이며 임의 고객 서비스나 다중 운영자의 지원 완료를 뜻하지 않는다.

## 남은 실환경 안정화

1. 최종 평가에서 반복된 Neutron 보안 그룹 주소 동기화 누락과 API·DNS 연결 실패의 원인·영구 수정.
   에이전트 재시작으로 복원한 측정과 운영 안정화를 구분한다.
2. 기본 프로필과 기존 greenfield 배포의 혼동 방지. override·IaC state·정확한 호스트를 확인하며
   label 조회가 비었다는 이유만으로 리소스 부재를 단정하지 않는다.
3. 호스트 준비 검사 통합. `gcp-host-verify`, controller→compute SSH, 실제 nested kernel boot의
   확인 경로를 일관되게 묶는 작업이 남아 있다.
4. `verify-kubernetes-image-guest.sh`의 고정 keypair 사전 삭제를 고유 이름·충돌 거부·소유 자원
   정리 방식으로 개선한다. 과거 artifact의 보완을 공통 코드 수정으로 간주하지 않는다.
5. 선택 관측을 사용하는 환경의 kubelet 인증서 검증·mTLS 갱신·전송 복귀와 수집 부하를 검증한다.

소유 label 없는 과거 probe는 운영자가 소유권을 확인한다. 실험 원본·실패·정리 예외는 보존한다.
S3의 단일 controller Cinder는 스토리지 HA를 제공하지 않으며, S4 Service proxy 결과를 일반
Ingress 품질로 확대 해석하지 않는다. 현재 구현의 이 제한을 없애는 작업은 필요가 생길 때 별도로 정한다.

## 구조 정리 후 확인할 것

2026-10-23에 공통 환경·OpenStack 접근을 특정 시나리오에서 분리하고 인프라·실험·선택 평가의
코드 위치와 명령 진입점을 나눴다. 상태 파일·UID 소유권·잠금·정리·판정 기준은 유지한다.
코드가 이동했으므로 새 실측은 새 코드 해시로 기록하고, 이전 캠페인의 동결 조건으로 재개하지 않는다.
로컬 회귀 검사와 실환경 수용을 구분하며 코드 정리만으로 새 실환경 검증을 선언하지 않는다.

초기 1~14번 제품 확장 우선순위는 Git 이력에서 확인한다. 당시 자동 증감의 미구현 범위는
[2026-09-11 기록](../archive/worker-autoscaling-validation.md#follow-ups-2026-09-11)에 보존한다.
