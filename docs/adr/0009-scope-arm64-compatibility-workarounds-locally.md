# ADR-0009: ARM64 호환성 보정은 로컬 프로필에만 한정한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 및 검증 완료

## 맥락

로컬 ARM64 배포 과정에서 공식 Kolla image와 Lima/VZ nested KVM의 조합에
환경 특화 문제가 발견됐다. 이를 공통 architecture에 숨기면 cloud AMD64와
bare-metal AMD64 프로필까지 불필요한 workaround가 전파된다.

## 결정

다음 보정은 `local-arm64`에 명시적으로 한정한다.

1. Kolla 2025.2 Debian ARM64 `nova-libvirt` image에 빠진 `dnsmasq-base`만
   추가한 pinned derivative image를 build한다.
2. Lima/VZ nested KVM에서 guest EFI boot가 실패하므로 compute host Ubuntu
   24.04의 AAVMF를 `nova-libvirt` container에 read-only mount한다.
3. metadata path 준비 전에도 network, SSH key와 user-data를 전달하도록
   verification VM에 Nova config drive를 사용한다.
4. 공개 verification image pull은 repository의 anonymous Docker config를
   사용해 사용자 credential helper 설정에 의존하지 않는다.

보정 이미지는 다른 OpenStack service image를 fork하지 않고
`nova_libvirt_image`만 override한다.

## 검토한 대안

- **공식 image를 직접 수정하거나 자체 Kolla image 전체를 운영:** 유지보수와
  supply-chain 범위가 불필요하게 커진다.
- **QEMU/TCG로 회피:** 실제 nested KVM 경로를 검증하지 못한다.
- **workaround를 공통 설정에 적용:** cloud/bare-metal profile의 차이를 숨긴다.
- **사용자 Docker 설정 변경:** 프로젝트 외 개발 환경에 side effect를 만든다.

## 결과

- local ARM64 guest boot와 Nova/libvirt capability discovery가 동작한다.
- OpenStack upgrade 시 derivative base tag와 workaround 필요성을 다시 확인해야 한다.
- AMD64 profile은 이 설정을 기본 상속하지 않는다.
- Kubernetes용 ARM64 Glance image도 별도 version과 checksum을 고정해야 한다.

## 재검토 조건

- 새 Kolla release가 ARM64 `dnsmasq-base` 문제를 해결할 때
- Lima/VZ 또는 AAVMF update로 host firmware mount가 불필요해질 때
- local profile의 base distribution이나 architecture를 변경할 때
