# ADR-0016: 환경 준비·관측·능동 검사를 분리한다

- 상태: 채택됨 — 준비·조회·능동 검사 분리 구현 및 검증
- 결정일: 2026-09-11
- 관계: ADR-0015의 계층별 선행 검증 및 실패 증거 보존 원칙 유지

## 배경

상태 조회에서 Calico 설정을 patch하거나 시험 Pod를 생성하면 구성 불일치와
조회 실패가 변경으로 가려진다. 준비와 관측, 능동 검사의 책임을 분리한다.

## 결정

- `workload-cluster-prepare`: Calico 의도 설정 적용 및 rollout 대기
- `workload-cluster-status`: 기존 연결로 한 번 조회, 관리 구성·시험 자원 변경 없음
- `workload-cluster-verify`: 동일한 읽기 전용 관측으로 제한 시간 내 수렴 대기
- `workload-cluster-probe`: management→workload API, 모든 Node의 CNI/DNS 능동 검사
- 구축 경로: Calico 설치 → prepare → verify → probe
- 수동 증감 및 기존 자동 증설 검증: verify와 probe를 명시적으로 분리 호출
- 수동 증감 중 암묵적인 OpenStack recovery 제거

ready(0), preparing(10), mismatch(20), unavailable(30), timeout(40)을 구분한다.
삭제·부팅·rollout 진행은 preparing, 설정 drift는 mismatch로 기록한다.
조회 오류를 빈 목록이나 0대로 처리하지 않으며 자동 patch·복구를 수행하지 않는다.
기본 수렴 제한은 3,600초다. Make가 상세 종료 코드를 보존하지 않으므로
자동화는 JSON 결과 또는 스크립트 직접 종료 코드를 확인한다.

CAPI/MD/MS/Machine/OSM/Node/Nova 상태와 providerID를 대조하고 Calico 설정·전체
Node coverage·CoreDNS readiness를 검사한다. snapshot과 조회 오류, 시간 초과의
마지막 관측 및 기존 진단 자료를 비공개 권한과 credential redaction으로 보존한다.

시험 Pod는 실행별 이름·cluster/run label·UID를 기록한다. 성공 시 JSON/events/log
저장 후 UID 조건부 삭제하고, 실패 자원은 보존한다. 이전 소유 시험 자원의 정리는
증거 저장 후에만 허용한다. 소유 label 없는 과거 고정 이름 Pod는 자동 삭제하지 않는다.

## 검증과 한계

[실행 절차와 검증 기록](../worker-autoscaling-validation.md)을 따른다.
상태 조회와 API/CNI/DNS 검사는 고객 HTTP 요청의 무중단 처리나 성능 여유를
검증하지 않는다. 자동 축소 정책과 worker 증감 범위 확장은 후속 변경에서 다룬다.
