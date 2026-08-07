# Architecture Decision Records

이 디렉터리는 OpenStack 기반 Kubernetes worker node autoscaling 테스트베드의
주요 기술 결정을 기록한다. 문서는 2026-08-06에 기존 대화와 구현을 바탕으로
소급 작성했으며, 이후 결정이 바뀌면 기존 ADR을 삭제하지 않고 새 ADR로
대체한다.

소급 기록에서 대화의 초기 추천안과 최종 구현이 다를 때는 다음 순서로
판단했다.

1. 현재 repository와 2026-08-06 clean-room 검증 결과
2. 사용자가 명시적으로 확정한 선택
3. 대화에서 제시된 비교안과 추천안

추천만 있었고 구현이나 명시적 확정이 없는 항목은 채택된 결정으로 만들지
않고 아래의 열린 결정에 남긴다.

## 상태 정의

- **채택됨:** 현재 설계 기준으로 사용한다.
- **제안됨:** 방향은 유력하지만 구현 전에 추가 결정이나 검증이 필요하다.
- **대체됨:** 더 새로운 ADR이 이 결정을 대신한다.
- **폐기됨:** 더 이상 적용하지 않는다.

ADR의 상태와 구현 상태는 다르다. 예를 들어 CAPI/CAPO는 설계로는 채택됐지만
아직 저장소에 구현되지 않았다.

## 결정 목록

| ADR | 결정 | 상태 | 구현 상태 |
|---|---|---|---|
| [0001](0001-stage-project-around-a-scale-up-baseline.md) | scale-up 기준선을 중심으로 프로젝트를 단계화한다 | 채택됨 | M0 및 M1 완료 |
| [0002](0002-use-standalone-capi-capo.md) | Kubernetes lifecycle은 standalone CAPI/CAPO로 관리한다 | 채택됨 | 로컬 kind 완료, provider 미구현 |
| [0003](0003-port-by-rebuilding-environment-profiles.md) | 환경 이전은 상태 이동이 아닌 프로필 기반 재구축으로 수행한다 | 채택됨 | 로컬 프로필만 구현 |
| [0004](0004-use-lima-arm64-for-the-local-feasibility-gate.md) | 로컬 기능 게이트는 Lima 기반 ARM64 2노드 환경으로 구성한다 | 채택됨 | 구현 및 검증 완료 |
| [0005](0005-deploy-openstack-with-kolla-ansible.md) | OpenStack 2025.2를 Kolla-Ansible로 배포한다 | 채택됨 | 구현 및 검증 완료 |
| [0006](0006-use-single-nic-with-logical-external-networking.md) | 로컬에서는 단일 NIC와 논리 external network를 사용한다 | 채택됨 | 구현 및 검증 완료 |
| [0007](0007-split-automation-by-responsibility.md) | 자동화 도구의 책임과 실행 위치를 분리한다 | 채택됨 | 구현 완료 |
| [0008](0008-require-layered-verification-and-safe-lifecycle.md) | 계층형 검증과 보수적인 상태·삭제 정책을 적용한다 | 채택됨 | 구현 및 clean-room 검증 완료 |
| [0009](0009-scope-arm64-compatibility-workarounds-locally.md) | ARM64 호환성 보정은 로컬 프로필에만 한정한다 | 채택됨 | 구현 및 검증 완료 |
| [0010](0010-build-pinned-arm64-kubernetes-image.md) | 고정 입력과 격리 builder로 ARM64 Kubernetes 노드 이미지를 만든다 | 채택됨 | Glance 및 Nova 재부팅 검증 완료 |

## 현재 마일스톤

```text
M0  로컬 OpenStack 자동 구축·검증                     완료
M1  Kubernetes용 ARM64 이미지와 management cluster   완료
M2  CAPI/CAPO workload cluster와 수동 증설            예정
M3  Pending Pod 기반 Cluster Autoscaler scale-up      예정
M4  scale-down 또는 장애·지연 개선 연구               미결정
M5  클라우드 AMD64 및 물리 AMD64 프로필               예정
```

M1부터 M3까지의 순서는 다음과 같다.

1. Kubernetes용 ARM64 Glance 이미지 빌드 및 Nova 부팅 검증 (완료)
2. macOS에 별도 local management Kubernetes cluster 생성 (완료)
3. CAPI, kubeadm bootstrap/control-plane provider, CAPO 설치 (다음 단계)
4. CAPO용 OpenStack application credential 연결 및 API 접근 검증
5. workload control plane 1대와 worker `MachineDeployment` 1대 생성
6. CNI를 설치하고 control plane과 worker의 `Ready` 확인
7. `MachineDeployment`를 1대에서 2대로 수동 증설
8. Cluster Autoscaler를 설치하고 Pending Pod 기반 scale-up 검증

첫 scale-up 실험은 HPA를 제외하고 resource request와 Deployment replica를
직접 조정한다. 이렇게 해야 Pod 증가 판단과 node 증가 판단을 분리해 문제를
분석할 수 있다.

## 아직 열린 결정

다음 항목은 대화에서 후보나 추천안은 나왔지만 최종 결정으로 확정하지 않았다.

- cloud/bare-metal 환경의 management cluster 실행 위치와 lifecycle
- CAPI, CAPO, Cluster Autoscaler의 정확한 버전 조합
- CNI로 Calico와 Cilium 중 무엇을 사용할지
- OpenStack Cloud Controller Manager를 어느 단계와 방식으로 설치할지
- workload Kubernetes API endpoint에 Octavia를 사용할지, PoC용 단일 endpoint를 사용할지
- Cluster Autoscaler의 최종 실행 위치와 scale-to-zero 지원 여부
- 첫 클라우드 프로필을 GCP와 AWS 중 어디로 구현할지
- 물리 서버의 실제 NIC, VLAN, switch 및 storage 구성
- scale-down을 필수 범위에 포함할지
- 후속 연구를 failure-aware recovery, warm pool, flavor-aware policy 중 무엇으로 정할지
- 현재 `172.24.4.0/24` external CIDR이 호스트 네트워크와 충돌할 때 사용할 대체 대역

## 관련 문서와 근거

- 프로젝트 사용법과 현재 검증 상태: [`README.md`](../../README.md)
- 로컬 환경 변수: [`config/environments/local-arm64.env`](../../config/environments/local-arm64.env)
- Kolla 설정: [`kolla/globals.yml.tpl`](../../kolla/globals.yml.tpl)
- Kubernetes 이미지 입력: [`kubernetes/image-builder-variables.json`](../../kubernetes/image-builder-variables.json)
- clean-room lifecycle 검증 커밋: `0882abf`
- 최초 로컬 테스트베드 구현 커밋: `194d4b3`
