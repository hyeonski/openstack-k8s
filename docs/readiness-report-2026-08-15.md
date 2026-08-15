# M3 진입 준비성 검증 보고서 — 2026-08-15

## 판정

**sleep/resume 복구와 M2 기능 기준선이 통과했고, M3 구현을 시작해도 된다.**

macOS sleep 뒤 nested workload VM clock이 뒤처지던 결함, CAPI 상태를 느슨하게
판정하던 결함, resume 뒤 host route가 사라지는 문제는 수정하고 실제 환경에서
검증했다. OpenStack clean-room 재구축, Kubernetes 이미지, management cluster,
provider, workload CP1+worker1과 `MachineDeployment` 1→2도 성공했다.

완전히 새로운 두 번째 worker에서 첫 Pod sandbox 생성이 실패한 이상이 한 번
발생했고 soft reboot로 복구했다. 이후 CPU, flavor와 timeout을 바꾸지 않고
2→1→2를 다시 실행한 결과 개입 없이 통과했으며, 새 worker를 명시적으로 지정한
CNI/DNS probe도 즉시 성공하고 orphan 프로세스가 없었다. 따라서 지속적인 CPU
부족으로 단정하지 않고 cold-path 관찰 사항으로 남긴다. 원래 5분 CNI/DNS 기능
게이트는 유지한다.

## 범위와 증거

- 환경: `local-arm64`
- 기준 commit: `b72a022dcfbff0b34f84a4ae9b1d511fc6b0178a`
- 검증 중 수정 사항: 아직 commit하지 않은 working tree 변경
- OpenStack clean-room run:
  [`artifacts/local-arm64-20260815T051126Z-10007`](../artifacts/local-arm64-20260815T051126Z-10007)
- Kubernetes image run:
  [`artifacts/local-arm64-20260815T054152Z-12090`](../artifacts/local-arm64-20260815T054152Z-12090)
- management/CAPI/workload run:
  [`artifacts/local-arm64-20260815T054505Z-12765`](../artifacts/local-arm64-20260815T054505Z-12765)
- capacity failure diagnostics:
  [`20260815T065748Z-manual`](../artifacts/local-arm64-20260815T054505Z-12765/m2/failures/20260815T065748Z-manual)

clean-room에서는 정확한 workload Cluster, project kind cluster, controller/compute
Lima VM 두 대와 project route를 삭제했다. secret, application credential,
Kubernetes QCOW2, download cache와 이전 artifact는 보존했다. 검증 중에는
`caffeinate -dimsu`로 macOS sleep을 방지했다.

## 결과

| 게이트 | 결과 | 관찰 |
|---|---|---|
| 정적 검사 | PASS with warning | Python test 4개, Bash syntax, guest/workload clock self-test 통과; ShellCheck 미설치 |
| host preflight와 관리망 | PASS | controller/compute clock skew 0~1초, 양방향 관리망 통과 |
| nested KVM | PASS | compute가 `accel=kvm`으로 ARM64 kernel boot |
| Kolla precheck/deploy/config | PASS | controller/compute 모두 `failed=0` |
| OpenStack guest/data path | PASS | Ubuntu VM, DHCP, Floating IP SSH, outbound, macOS/Docker API path 통과 후 test VM 정리 |
| Kubernetes ARM64 image | PASS | Glance ACTIVE, 실제 Nova boot와 reboot gate 통과 |
| management와 provider | PASS | kind v1.35.0, CAPI v1.13.4, CAPO v0.14.6, ORC v2.4.0, credential token 발급 통과 |
| workload CP1+worker1 | PASS | v1.35.7 Node 2대 Ready, Calico/CoreDNS/API/CNI/DNS 통과 |
| Machine identity gate | PASS | 모든 Machine의 InternalIP와 `openstack:///` providerID를 확인한 뒤 clock 검사 수행 |
| strict CAPI gate | PASS | KCP/Cluster `Available=True`, desired/ready/available control plane 1/1/1 |
| workload clock gate | PASS | 세 workload VM 모두 macOS/controller 대비 skew 0초 |
| worker 1→2 infrastructure | PASS | Machine 3/3, Nova ACTIVE 3대, Node Ready 3대, Calico node 3/3 |
| 첫 scale 명령의 최종 CNI/DNS probe | **FAIL** | 새 worker의 `RunPodSandbox`가 deadline을 넘겨 Pod가 5분 동안 `ContainerCreating` |
| 수동 recovery 뒤 전체 WORKERS=2 검증 | PASS | soft reboot, `make resume-recover`, 전체 CAPI/Node/Calico/API/CNI/DNS 재검증 통과 |
| 동일 조건 2→1 cleanup | PASS | MachineDeployment 1/1, CAPI Cluster 2/2, Node 2대와 CNI/DNS 전체 검증 통과 |
| 동일 조건 1→2 재시도 | PASS | 약 3분 안에 Machine/Nova/Node/Calico/API/CNI/DNS가 개입 없이 통과 |
| 새 worker targeted CNI/DNS | PASS | `...-nhznk`에 명시적으로 배치, 즉시 `Completed`, Pod IP `192.168.88.130` |
| 재시도 worker orphan 검사 | PASS | load average 1.52, 실행 중인 `/opt/cni/bin/calico-ipam` 없음 |

## 이번에 수정한 검증 및 복구 결함

1. `workload-clock.sh`가 CAPI Machine, OpenStack server 상태, workload system/RTC
   clock을 검사하고 local profile에서 뒤처진 system clock만 앞으로 복구한다.
2. `resume-recover.sh`가 stopped Lima guest 기동, outer clock/OpenStack readiness,
   macOS Floating IP route, nested workload clock, strict CAPI readiness를 한 번에
   복구한다.
3. SSH가 느릴 때 미리 캡처한 macOS epoch를 미래 시각으로 오판하지 않도록,
   보정 직전의 동기화된 controller epoch를 사용한다. 최종 결과는 macOS 호출
   전·후 시간 창으로 다시 검증한다.
4. workload create/scale은 모든 Machine에 InternalIP와 providerID가 생길 때까지
   기다린 뒤 clock 검사를 실행한다. clean-room 첫 create에서 발견한 race를
   제거했다.
5. workload verify는 KCP와 Cluster `Available=True`, control-plane
   desired/ready/available 1/1/1을 필수로 검사한다.
6. Lima JSON 조회 helper는 입력을 끝까지 소비해 `pipefail`이 정상 조회를
   SIGPIPE 실패로 오인하지 않도록 수정했다.

## 첫 cold-path failure와 재시도 분석

두 번째 worker 생성 뒤 compute의 4 vCPU에서 세 개의 2-vCPU QEMU guest가 약
370% CPU를 사용했다. 새 worker의 load average는 25까지 상승했고 kubelet은
1초 housekeeping에 최대 약 43초가 걸렸다고 기록했다. Calico는 crash/restart
없이 결국 Ready가 됐지만 첫 Pod sandbox에서 다음 오류가 발생했다.

```text
Failed to create pod sandbox: rpc error: code = DeadlineExceeded
```

실패한 CNI 호출의 `/opt/cni/bin/calico-ipam`은 parent PID 1의 orphan으로 15분
이상 남았다. 같은 시점 compute에는 약 2.2 GiB available memory가 있었고 swap은
약 268 KiB만 사용했으므로 당시 직접 관찰된 병목은 CPU scheduling이었다. 정확한
새 worker 한 대를 soft reboot한 뒤 orphan이 제거됐다.

다만 이 관찰만으로 4 vCPU가 구조적으로 부족하다고 결론 내릴 수는 없다. 같은
환경에서 2→1 축소를 완전히 검증한 뒤 새 worker `...-nhznk`를 다시 생성했을 때는
Node와 Calico가 빠르게 Ready가 됐고 scale 명령이 약 3분 안에 끝났다. 새 worker
targeted Pod sandbox/CNI/DNS도 즉시 성공했다. 첫 실패는 현재 재현되지 않은
cold-path anomaly이며, CPU 증설이나 timeout 확대를 적용하지 않는다.

## M3 구현 및 완료 조건

1. CPU와 timeout은 현재 값으로 유지하고 Cluster Autoscaler 구현을 시작한다.
2. autoscaler가 만든 새 worker를 명시적으로 지정해 Pod sandbox/CNI/DNS를
   검증한다. 현재 일반 CNI probe의 scheduler 선택에만 의존하지 않는다.
3. 첫 cold-path 이상이 재발하면 CNI log, containerd `RunPodSandbox`, kubelet retry,
   API service path와 orphan process 상태를 자동 수집하고 그때 capacity 변경 여부를
   다시 판단한다.
4. M3 완료 판정에는 Pending Pod 기반 scale-up, scale-down, Nova/CAPI/Node orphan
   부재와 기존 strict clock/CAPI gate 통과가 모두 필요하다.
5. 배포 품질 검증 전 ShellCheck를 설치해 전체 lint를 다시 기록한다.

## 운영 경계

- clean-room 검증 한 사이클에서는 macOS sleep을 허용하지 않고 `caffeinate`를
  사용한다.
- 예상하지 못한 sleep/resume 뒤에는 workload가 존재하면
  `make resume-recover`, 아직 workload가 없으면 `make local-up`을 사용한다.
- 자동 복구는 뒤처진 workload system clock만 앞으로 맞춘다. 실제로 호스트보다
  앞선 clock은 자동으로 뒤로 돌리지 않고 실패시킨다.
