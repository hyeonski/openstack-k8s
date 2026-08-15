# ADR-0012: Cluster Autoscaler를 management cluster에서 실행한다

- 상태: 채택됨
- 결정일: 2026-08-15
- 구현 상태: 2026-08-15 실제 Pending Pod 기반 1→2 증설 검증 완료
- 대체 대상: ADR-0002의 Cluster Autoscaler 실행 위치 결정

## 맥락

M2는 Kubernetes v1.35.7 workload cluster의 control plane 1대와 worker 2대,
수동 `MachineDeployment` 증설, 새 worker의 CNI/DNS probe까지 검증했다. M3는
CPU request 때문에 스케줄할 수 없는 Pod를 Cluster Autoscaler가 감지하고
worker를 자동으로 1대에서 2대로 늘리는 기준선을 만들어야 한다.

management cluster와 workload cluster는 분리되어 있다. CAPI/CAPO 리소스는
Docker Desktop의 kind management cluster에 있고, Node, Pod와 scheduler event는
OpenStack VM 기반 workload cluster에 있다. 따라서 Autoscaler가 두 API에 서로
다른 권한으로 접근해야 한다.

ADR-0002는 첫 Autoscaler를 workload cluster에서 실행하기로 했지만, M3의
확정 설계는 management cluster에서 실행하는 것이다. standalone CAPI/CAPO와
분리된 management cluster를 사용하는 나머지 결정은 유지한다.

## 결정

- Cluster Autoscaler는 `osk8s-management` kind cluster에서 Deployment 1개로
  실행한다.
- Kubernetes Autoscaler의 버전 정책에 따라 workload Kubernetes v1.35와 같은
  minor인 Cluster Autoscaler v1.35.0을 사용한다. 이미지는 tag와 multi-architecture
  manifest digest를 함께 고정한다.

  ```text
  registry.k8s.io/autoscaling/cluster-autoscaler:v1.35.0@sha256:2fc9433dd3b47baef0e68d6b1110b770a3c93db10c7bead4c5bc6cb21c72b875
  ```

  이 manifest의 `linux/arm64` image digest는
  `sha256:22cacc1f932484eab3ed12e09503f0d5efe472a92a9de915205aadd4fd66e6eb`이다.
  실행 설정에서는 `latest`를 사용하지 않는다.
- `clusterapi` cloud provider는 다음 연결 계약으로 실행한다.

  ```text
  --cloud-provider=clusterapi
  --kubeconfig=/etc/cluster-autoscaler/workload/value
  --clusterapi-cloud-config-authoritative
  --node-group-auto-discovery=clusterapi:namespace=osk8s-workload,clusterName=osk8s-workload
  --scale-down-enabled=false
  ```

  management API에는 Pod의 in-cluster ServiceAccount 자격증명을 사용한다.
  `--kubeconfig`에는 workload API의 전용 ServiceAccount kubeconfig를 연결한다.
  `--clusterapi-cloud-config-authoritative`로 `--cloud-config` 미지정 상태를
  명시적으로 유지하고 workload kubeconfig로 management API 접근이 fallback되는
  것을 막는다.
- management 권한은 `osk8s-workload` namespace의 `MachineDeployment`, scale
  subresource, `Machine`, `MachineSet`, `MachinePool`과 CAPO
  `OpenStackMachineTemplate`에 필요한 권한으로 제한한다. v1.35는 scale
  subresource를 patch하므로 `get/patch/update`를 허용한다. workload에는 upstream
  v1.35 Helm Role의 Pod, Node, controller, storage, DRA `resource.k8s.io`, event,
  leader-election/status 권한을 전용 ServiceAccount에 부여한다.
- workload ServiceAccount token과 CA를 사용해 kubeconfig를 만들고 management
  namespace의 Secret으로만 연결한다. 임시 파일은 private state directory에서
  mode `0600`으로 다루며 성공과 실패 모두에서 제거한다. token, kubeconfig와
  Secret data를 artifact 또는 log에 출력하지 않는다.
- worker `MachineDeployment`에는 다음 annotation을 모두 설정한다.

  ```text
  cluster.x-k8s.io/cluster-api-autoscaler-node-group-min-size: "1"
  cluster.x-k8s.io/cluster-api-autoscaler-node-group-max-size: "2"
  ```

- M3는 1→2 자동 scale-up만 검증한다. scale-down은 명시적으로 끄고 M4로
  유지한다. HPA와 scale-to-zero도 포함하지 않는다.
- 테스트 Deployment의 CPU request는 실행 시점 worker의 allocatable CPU와
  기존 Pod request를 먼저 측정한 뒤 정한다. 한 worker에는 한 Pod만 들어가고
  두 Pod는 동시에 들어가지 않으며, 같은 크기의 새 worker에는 Pending Pod가
  들어가는 범위여야 한다.
- 성공 게이트는 `Unschedulable`/`Insufficient cpu` 증거, MachineDeployment
  1→2, 새 Machine/OpenStackMachine/Nova/Node/Calico 준비, 새 worker를 직접
  지정한 CNI/DNS probe, 기존 Pending Pod의 새 worker 배치, workload clock,
  strict CAPI readiness와 orphan `calico-ipam` 부재다.
- 실패하면 테스트 리소스와 증설 상태를 보존한다. 진단은 Autoscaler log와
  event, Pending Pod와 scheduler event, CAPI 리소스, Nova server, 새 worker의
  cloud-init/kubelet/containerd/Calico 상태 및 compute pressure를 수집하고 기존
  redaction 정책을 적용한다.
- 첫 cold-path CNI 이상이 재현되면 CPU 또는 기존 timeout을 먼저 바꾸지 않는다.
  Calico CNI log, containerd `RunPodSandbox` 요청/취소, kubelet sandbox retry,
  Kubernetes API service path, `calico-ipam` PID/PPID/elapsed/wait 상태와 worker/
  compute pressure를 수집한 뒤 원인을 판단한다.

## 검토한 대안

- **Autoscaler를 workload cluster에서 실행:** workload 관찰에는 in-cluster
  권한을 쓸 수 있지만 management kubeconfig와 CAPI 권한을 workload에 배포해야
  한다. 이번 topology에서는 lifecycle controller와 함께 management cluster에
  두고 workload credential만 제한적으로 연결하는 편이 운영 경계가 명확하다.
- **CAPI가 생성한 workload admin kubeconfig를 그대로 mount:** 구현은 단순하지만
  Autoscaler가 필요로 하는 범위보다 권한이 크다. M3는 전용 ServiceAccount와
  명시적 workload RBAC를 사용한다.
- **Helm chart 설치:** 유효하지만 이번 실험에는 하나의 고정 manifest template과
  네 개의 Make target만 필요하다. chart version과 values 변환 계층을 추가하지
  않고 upstream 실행 인자와 RBAC를 저장소에서 직접 검토 가능하게 유지한다.
- **정적 `--nodes` 지정:** Cluster API provider의 namespace/clusterName
  auto-discovery와 min/max annotation 계약이 이미 이 실험의 node group 경계를
  정확히 표현한다.
- **scale-down도 함께 검증:** scale-up 장애 원인과 drain/축소 정책이 섞인다.
  ADR-0001에 따라 scale-down은 M4에서 별도 검증한다.

## 실행 및 검증 결과

- CP1+worker2 전체 검증 뒤 MachineDeployment를 2→1로 줄였고 CAPI Machine,
  OpenStackMachine, Nova server와 Kubernetes Node 정리를 확인했다.
- worker allocatable 2,000m, 기존 request 250m를 측정하고 각 test Pod request를
  1,050m로 정했다. 하나는 Running, 다른 하나는 MachineDeployment=1 상태에서
  `PodScheduled=False`, `reason=Unschedulable`, `Insufficient cpu`가 됐다.
- Autoscaler가 `TriggeredScaleUp`과 `ScaledUpGroup` event를 기록하고
  MachineDeployment를 1→2로 patch했다. 새 Machine
  `osk8s-workload-md-0-ppx4r-cv577`은 10:24:34Z 생성, Nova ACTIVE 뒤 Node가
  10:25:48Z Ready가 됐다.
- 기존 Pending Pod가 새 worker에서 Running이 됐고, 같은 node를 직접 지정한
  CNI/DNS probe가 성공했다. CP1+worker2 전체 검증, workload clock, strict CAPI
  readiness, Calico와 orphan `calico-ipam` 부재를 다시 통과했다.
- 첫 설치에서 non-root Pod의 Secret mode, v1.35 DRA informer, CAPO template
  read와 scale subresource patch 권한 누락을 각각 진단했다. CPU나 기존 timeout을
  바꾸지 않고 `fsGroup`/`0440`과 공식 v1.35 최소 read/patch 권한으로 수정했다.
- 성공과 실패 진단 artifact에 credential, kubeconfig data나 알려진 token 패턴이
  없고 모든 M3 파일은 group/other 읽기 권한이 없다.

## 제한

- management cluster 장애 시 자동 증설 판단도 중단되지만 workload cluster의
  기존 node와 workload 실행은 유지된다.
- workload ServiceAccount token은 management Secret에 존재하므로 management
  namespace 읽기 권한은 최소화해야 한다. credential rotation은 이번 단일 M3
  실행 뒤 별도로 개선할 수 있다.
- min=1이므로 scale-from-zero capacity annotation은 필요하지 않다. CAPO의
  node template 용량을 구성하는 v1.35 실행 경로가 `OpenStackMachineTemplate`을
  조회하므로 해당 infrastructure template read 권한은 필요했다.
- 로컬 4 vCPU compute 결과는 기능 검증이며 provisioning 성능이나 적정 CPU
  sizing 결론으로 사용하지 않는다.

## 근거

- [Cluster Autoscaler version policy](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.35.0/cluster-autoscaler/README.md#releases)
- [Cluster Autoscaler v1.35.0 release and images](https://github.com/kubernetes/autoscaler/releases/tag/cluster-autoscaler-1.35.0)
- [Cluster API cloud provider configuration](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.35.0/cluster-autoscaler/cloudprovider/clusterapi/README.md)
- [Cluster API autoscaling documentation](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/autoscaling)
- image digest: 2026-08-15에 `docker buildx imagetools inspect`로 공식
  `registry.k8s.io` manifest를 확인했다.

## 재검토 조건

- workload Kubernetes minor를 변경하거나 v1.35의 새 Cluster Autoscaler patch가
  발행되어 upgrade를 검토하는 경우
- Autoscaler를 HA로 실행하거나 management cluster topology를 바꾸는 경우
- workload credential을 단기 TokenRequest 또는 외부 credential broker로
  교체하는 경우
- M4 scale-down이나 scale-from-zero를 시작하는 경우
