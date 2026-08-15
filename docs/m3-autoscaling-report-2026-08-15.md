# M3 Cluster Autoscaler 검증 보고서 — 2026-08-15

## 결론

로컬 ARM64 4-vCPU compute에서 CPU request 기반 Pending Pod가 Cluster
Autoscaler v1.35.0의 CAPI provider를 통해 worker MachineDeployment를 1대에서
2대로 자동 증설했다. CPU와 기존 timeout은 변경하지 않았다. M3 범위는
scale-up이며 scale-down, HPA와 scale-to-zero는 검증하지 않았다.

성공 artifact는 다음 로컬 경로에 보존했다.

```text
artifacts/local-arm64-20260815T054505Z-12765/m3
```

이 경로는 Git에서 제외되며 credential나 kubeconfig를 포함하지 않는다.

## 실행 환경

- management: kind v0.31.0, Kubernetes v1.35.0, ARM64
- workload: Kubernetes v1.35.7, control plane 1대, worker 1→2
- CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6, ORC v2.4.0
- Calico v3.32.1, containerd 2.3.2
- Cluster Autoscaler v1.35.0
- image index digest:
  `sha256:2fc9433dd3b47baef0e68d6b1110b770a3c93db10c7bead4c5bc6cb21c72b875`
- image arm64 child digest:
  `sha256:22cacc1f932484eab3ed12e09503f0d5efe472a92a9de915205aadd4fd66e6eb`
- MachineDeployment min/max: 1/2
- 전체 실험 동안 `caffeinate -dimsu` 유지

## 검증 순서와 증거

1. `make resume-recover`가 outer/nested clock, OpenStack과 strict CAPI readiness를
   통과했다.
2. `make workload-cluster-verify WORKERS=2`에서 CAPI 3/3, Nova 3대, Node 3대,
   Calico와 API/CNI/DNS probe가 통과했다.
3. `make workload-cluster-scale WORKERS=1`로 worker를 줄인 뒤 CAPI 2/2,
   Nova 2대와 Node 2대로 정리된 것을 확인했다.
4. management cluster에 Autoscaler를 설치하고 workload 전용 ServiceAccount
   kubeconfig Secret을 mount했다. running imageID는 고정한 index digest였고
   실행 node architecture는 arm64였다.
5. 기존 worker의 allocatable은 2,000m, 이미 요청된 CPU는 250m, 사용 가능한
   CPU는 1,750m였다. 한 개만 들어가고 두 개는 들어가지 않도록 test Pod당
   1,050m를 선택했다.
6. `m3-cpu-scale-up-97c46c48b-xm8gv`가 MachineDeployment=1 상태에서
   `PodScheduled=False`, `reason=Unschedulable`, scheduler message의
   `Insufficient cpu`를 보고했다. control plane의 기본 NoSchedule taint도
   message에 함께 기록됐지만 image, PVC 또는 affinity 오류는 없었다.
7. Autoscaler log가 다음 순서를 기록했다.

   ```text
   Scale-up: setting group MachineDeployment/osk8s-workload/osk8s-workload-md-0 size to 2
   ScaledUpGroup ... size set to 2 instead of 1 (max: 2)
   TriggeredScaleUp ... 1->2 (max: 2)
   ```

8. 새 Machine/OpenStackMachine `osk8s-workload-md-0-ppx4r-cv577`이 생성되고
   Nova server가 ACTIVE가 됐다. Machine은 10:24:34Z에 생성됐고 Node는
   10:25:48Z에 Ready가 됐다.
9. 새 node를 `spec.nodeName`으로 직접 지정한 `m3-new-worker-cni-dns`가 Pod
   sandbox 생성, CNI 주소 할당과 `kubernetes.default.svc.cluster.local` 조회를
   완료했다.
10. 기존 Pending Pod가 새 worker `…-cv577`에서 10:25:48Z Running이 됐다.
11. 최종 `workload-cluster-verify WORKERS=2`가 CAPI 3/3, Nova/Node 3대,
    workload clock, strict Cluster/KCP Available, Calico와 API/CNI/DNS probe를
    다시 통과했다.
12. targeted probe가 끝난 뒤 새 worker의 PID/PPID/elapsed/state/wchan process
    목록에 `calico-ipam`이 남지 않았다.

`scale-up-timing.txt`의 463초에는 실행 중 RBAC 보정을 조사한 시간이 포함되므로
provisioning 성능값으로 사용하지 않는다. 최종 권한이 적용된 성공 시도에서
Autoscaler scale event부터 Node Ready까지는 약 76초였지만 이 역시 로컬 기능
증거일 뿐 성능 결론이 아니다.

## 구현 중 발견한 실패와 보정

첫 설치와 첫 scale 판단 실패는 상태를 삭제하지 않고 다음 경로에 진단을
보존했다.

```text
artifacts/local-arm64-20260815T054505Z-12765/m3/diagnostics/20260815T101551Z-install
artifacts/local-arm64-20260815T054505Z-12765/m3/diagnostics/20260815T101613Z-manual
```

- Secret volume `0400`은 non-root Autoscaler가 읽지 못했다. Pod `fsGroup`과
  Secret mode `0440`으로 수정했다.
- v1.35 scheduler simulation은 `resourceslices`, `deviceclasses`,
  `resourceclaims` informer를 사용한다. 공식 v1.35 Helm Role의
  `resource.k8s.io` read 권한을 추가했다.
- CAPO node template 평가가 `OpenStackMachineTemplate`을 조회하므로 management
  namespace Role에 read 권한을 추가했다.
- CA v1.35가 `MachineDeployment/scale`을 patch하므로 scale subresource에
  `get/patch/update`를 부여하고 `can-i patch --subresource=scale`을 검증한다.

성공 상태의 수동 진단도 다음 경로에 보존했다.

```text
artifacts/local-arm64-20260815T054505Z-12765/m3/diagnostics/20260815T102757Z-manual
```

진단은 Autoscaler log/event/status, Pending Pod, CAPI/CAPO, Nova, Calico,
guest cloud-init/kubelet/containerd와 compute pressure를 포함한다. 모든 파일에
기존 redaction을 적용했고 M3 전체 artifact에서 kubeconfig data, application
credential, JWT/bootstrap token 패턴을 찾지 못했다.

## 남은 위험

- 첫 clean-room cold-path의 Pod sandbox/orphan CNI 이상은 이번 M3에서
  재현되지 않았다. 재발 시 수집하도록 한 containerd `RunPodSandbox`/취소,
  kubelet retry, Calico, API service path와 process wait 상태를 원인 확인 전에
  보존한다.
- workload ServiceAccount의 장기 token은 management Secret에 저장된다. 현재
  namespace 접근을 제한하고 artifact/log 출력을 막았지만 단기 TokenRequest
  기반 rotation은 후속 개선 대상이다.
- `--scale-down-enabled=false`는 v1.35에서 deprecated 경고를 내지만 아직
  지원되며 M3 범위를 확실히 제한한다. 제거되는 release로 upgrade할 때 M4
  정책과 함께 대체 방법을 정해야 한다.
- scale-down은 ADR-0001에 따라 M4에서 별도로 검증한다.
