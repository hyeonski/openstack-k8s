# ADR-0010: 고정 입력과 격리 builder로 ARM64 Kubernetes 노드 이미지를 만든다

- 상태: 채택됨
- 결정일: 2026-08-06
- 구현 상태: 빌드, Glance 업로드, Nova 부팅·재부팅 검증 완료

## 맥락

CAPO가 만드는 VM에는 cloud-init만 가능한 일반 OS 이미지가 아니라 kubelet,
kubeadm, container runtime과 Kubernetes 노드 선행 조건이 준비된 이미지가
필요하다. 로컬 호스트는 16 GiB이므로 OpenStack controller/compute와 이미지
빌드 VM을 동시에 실행하면 기능 검증 결과가 메모리 압박에 좌우될 수 있다.

재현 가능한 검증을 위해 latest tag나 수동으로 변경한 장기 실행 VM 대신
입력 버전, source commit과 결과 checksum을 고정해야 한다.

## 결정

- Kubernetes Image Builder v0.1.55의 정확한 commit
  `7ffb9b7f1f26cd66891874463cc9411e3633325f`을 사용한다.
- Ubuntu 22.04 ARM64/UEFI QCOW2에 Kubernetes v1.35.7,
  containerd 2.3.2와 pause 3.10.2를 설치한다.
- `osk8s-image-builder`라는 별도 6 GiB Lima VM에서 중첩 KVM/QEMU로
  빌드하며 controller/compute와 동시에 실행하지 않는다.
- upstream MaaS ARM64 QEMU 정의를 OpenStack용으로 최소 조정한다. MaaS
  post-processor와 `/etc/fstab` 삭제는 제거하고 결과를 QCOW2로 보존한다.
- upstream OpenStack Goss profile의 AMD64 전용
  `linux-cloud-tools-virtual` 검사 대신 ARM64 패키지 조건이 정의된
  `maas-arm64` profile로 공통 QEMU/cloud-init/Kubernetes 검사를 수행한다.
  OpenStack provider 적합성은 실제 Glance 업로드와 Nova 부팅으로 별도
  검증한다.
- 호스트에 복사된 결과의 SHA-256을 검증하고, 버전이 포함된 불변 이미지
  이름과 checksum/아키텍처/OS/버전 속성으로 Glance에 등록한다.
- Nova 게스트에서 cloud-init, ARM64, Kubernetes 도구, containerd CRI,
  커널 모듈/sysctl, swap, registry pull을 확인한 뒤 재부팅 후 readiness를
  다시 검사한다.

## 검토한 대안

- **일반 Ubuntu cloud image에 매번 cloud-init으로 설치:** 간단하지만 VM
  생성 시간과 외부 repository 상태가 machine provisioning 결과에 섞인다.
- **controller 또는 compute에서 이미지 빌드:** VM 수는 줄지만 OpenStack
  서비스 자원과 빌드 자원이 경쟁하고 실패 격리가 어렵다.
- **장기 실행 builder 유지:** 재빌드는 빠르지만 로컬 자원을 계속 점유하고
  수동 변경으로 재현성이 약해질 수 있다.
- **upstream OpenStack Goss profile을 그대로 사용:** ARM64 Ubuntu에는 없는
  AMD64 전용 package를 요구해 유효한 이미지를 실패로 판정한다.

## 결과

- Image Builder Goss 64개 검사와 `qemu-img check`, 호스트 SHA-256 검증을
  통과한 20 GiB virtual-size QCOW2가 생성됐다.
- Glance 이미지 `ubuntu-2204-kube-v1.35.7-arm64`는 ARM64/UEFI 속성과
  SHA-256을 가진 `active` 상태로 등록됐다.
- 실제 Nova VM에서 Kubernetes v1.35.7, containerd CRI와 노드 선행 조건을
  검증하고 재부팅 후에도 정상임을 확인했다.
- builder는 검증 후 삭제했으며 QCOW2, checksum과 검증 artifact는
  호스트에 보존했다.
- 이 결과는 노드 이미지 준비가 끝났다는 의미이며 management/workload
  Kubernetes cluster 또는 CAPI/CAPO가 동작한다는 의미는 아니다.

## 재검토 조건

- CAPI/CAPO 버전 조합이 Kubernetes v1.35를 지원하지 않는 경우
- workload bootstrap에서 추가 kernel module, package 또는 image가 필요한 경우
- 클라우드/물리 AMD64 프로필을 구현해 ARM64 adapter가 필요 없어지는 경우
- 로컬 호스트 자원이 늘어나 builder 동시 실행이 안전하게 검증되는 경우
