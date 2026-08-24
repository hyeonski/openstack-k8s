# ADR-0013: GCP AMD64를 유일한 실행 환경으로 사용한다

- 상태: 채택됨
- 결정일: 2026-08-24

## 배경

OpenStack, CAPI/CAPO와 Cluster Autoscaler 기준선이 GCP의 중첩 가상화 AMD64
호스트에서 검증됐다. 여러 host provider와 CPU 아키텍처를 한 코드베이스에서
유지하면 기본 환경 오선택, 배포 입력 혼입과 검증 범위 증가가 발생한다.

## 결정

- `cloud-gcp-amd64`를 유일한 실행 구성으로 사용한다.
- controller 한 대와 compute 두 대를 GCP custom VPC에서 운영한다.
- 원격 실행과 파일 전송은 `gcloud compute ssh/scp` 및 IAP를 사용한다.
- Kubernetes 노드 이미지는 GCP 일회성 nested-KVM builder에서 AMD64/BIOS로 만든다.
- 모든 `make` target은 별도 환경 인자 없이 GCP state를 사용한다.
- 제거된 실행 환경의 코드와 문서는 Git 이력으로만 보존한다.

## 결과

provider fallback과 아키텍처별 보정이 사라지고 실행 경로가 단일화된다. 대신 다른
cloud 또는 bare-metal 지원은 이 저장소의 암묵적 기능이 아니며, 필요하면 별도
프로젝트나 명시적인 새 ADR로 도입해야 한다.

## 재검토 조건

- GCP가 필요한 nested virtualization 또는 routing 기능을 제공하지 않는 경우
- production 수준의 HA control plane, persistent storage 또는 다른 region이 필요한 경우
- 두 번째 실행 환경을 유지할 명확한 운영 주체와 독립 검증 파이프라인이 생기는 경우
