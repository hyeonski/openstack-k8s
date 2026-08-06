# ADR-0008: 계층형 검증과 보수적인 상태·삭제 정책을 적용한다

- 상태: 채택됨
- 결정일: 2026-08-06 (소급 기록)
- 구현 상태: 구현 및 clean-room 검증 완료

## 맥락

프로세스가 실행 중이거나 Nova server가 `ACTIVE`인 것만으로 실제 기능을
보장할 수 없다. 중첩 KVM, DHCP, Floating IP, outbound, workload API path와
재기동 readiness가 각각 실패할 수 있다. 실패 시 자동 정리를 먼저 하면
원인 증거를 잃을 수 있고, 광범위한 삭제는 사용자의 다른 VM과 도구를
손상시킬 수 있다.

## 결정

검증을 다음 순서로 통과시킨다.

1. macOS architecture, RAM, disk, CIDR와 prerequisite read-only preflight
2. controller/compute 양방향 관리망
3. compute `/dev/kvm` 존재와 실제 ARM64 Linux kernel boot
4. Kolla bootstrap/prechecks와 rendered config 검증
5. 제한된 application credential의 token 및 tenant resource 접근
6. CirrOS VM의 config drive, DHCP, Floating IP, SSH와 outbound
7. Ubuntu VM의 cloud-init과 TCP 6443 dummy workload API
8. macOS와 격리된 Docker bridge에서 OpenStack API/FIP:6443 접근
9. clean-room 삭제·재구축과 완전 정지 후 readiness 복구

성공한 임시 guest는 정리하되 실패한 guest와 로그는 진단을 위해 보존한다.
`local-down`은 route와 프로젝트 VM 정지만 수행한다. `local-destroy`는
`CONFIRM=<environment>`를 요구하고 정확한 두 Lima VM만 삭제한다.

secret은 `.state/<environment>/secrets`에 `0700/0600` 권한으로 저장하고 Git에서
제외한다. artifact에는 secret을 복사하지 않는다. SOPS는 원격 공유 필요가
생길 때까지 도입하지 않는다.

## 검토한 대안

- **service/container 상태만 확인:** 실제 guest data plane을 검증하지 못한다.
- **모든 검증을 한 script에 결합:** 실패 계층과 재시도 범위가 불명확하다.
- **실패 시 항상 자동 정리:** console log와 orphan 상태를 잃는다.
- **범용 destroy/초기화 명령:** 프로젝트 외 Lima/Docker/socket_vmnet 상태를
  삭제할 위험이 있다.
- **처음부터 SOPS 도입:** 현재 local-only secret에는 운영 부담이 더 크다.

## 결과

- 성공 기준이 상태값이 아닌 사용자 관점의 end-to-end 기능으로 정의된다.
- CAPO를 설치하기 전에 필요한 두 네트워크 경로를 Kubernetes 없이 검증했다.
- 최신 local clean-room과 restart lifecycle이 통과했다.
- `make lint`는 ShellCheck가 없으면 Bash syntax만 검사하므로 CI 품질 게이트에는
  ShellCheck 설치가 여전히 필요하다.

## 재검토 조건

- CI나 공동 개발에서 secret을 안전하게 공유해야 할 때
- cloud/bare-metal destroy 범위와 복구 정책을 정의할 때
- Kubernetes/CAPO 상태와 scale-up timing evidence를 artifact에 추가할 때
