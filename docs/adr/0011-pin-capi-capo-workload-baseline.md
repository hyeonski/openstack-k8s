# ADR-0011: Kubernetes v1.35 workload 기준선을 CAPI v1.13과 CAPO v0.14로 구성한다

- 상태: 채택됨
- 결정일: 2026-08-07
- 구현 상태: 2026-08-11 clean-room에서 provider 설치, workload cluster 생성,
  worker 수동 증설과 실패 진단 경로 검증 완료

## 맥락

M2는 기존 kind management cluster에서 OpenStack VM 기반 Kubernetes
v1.35 cluster를 만들고 `MachineDeployment`의 실제 scale-up을 검증해야 한다.
따라서 CAPI core, kubeadm bootstrap/control-plane provider, `clusterctl`, CAPO,
CNI와 OpenStack credential 전달 방식을 하나의 재현 가능한 버전 계약으로
고정해야 한다.

CAPI의 공식 version support 표는 v1.13에서 Kubernetes v1.35 management와
workload cluster를 지원한다. CAPI v1.13.4 release는 management v1.32~v1.36,
workload v1.30~v1.36을 명시한다. CAPO의 공식 compatibility 표는 v0.14가
CAPI v1.12 이상과 호환된다고 명시한다.

## 결정

- Kubernetes workload 버전은 이미지와 같은 v1.35.7로 고정한다.
- CAPI core, CABPK, KCP와 `clusterctl`은 v1.13.4로 같은 patch에 고정한다.
- CAPO는 v0.14.6, CAPO가 사용하는 OpenStack Resource Controller는
  v2.4.0으로 고정한다.
- CNI는 ARM64 image와 단일 manifest를 제공하는 Calico v3.32.1을 사용한다.
  Pod CIDR은 `192.168.0.0/16`, Service CIDR은 `10.96.0.0/12`로 둔다.
- CAPO가 `10.6.0.0/24` subnet, router와 control-plane/worker security group을
  관리한다. Calico의 node 간 BGP TCP 179와 IP-in-IP protocol 4를 두 managed
  group 사이에 허용한다.
- Octavia가 없는 로컬 OpenStack에서는 단일 control plane VM에 Floating IP를
  연결한 endpoint를 사용한다. 이 기준선은 HA control plane이 아니다.
- 기존 application credential의 `clouds.yaml`을 mode `0600`인 프로젝트 상태
  파일과 namespace-scoped Secret으로만 전달한다. provider 설치 전 kind Pod에서
  token 발급을 실제로 확인한다.
- `provider-id`는 CAPO가 cloud-init metadata로 render한 instance UUID를 kubelet
  bootstrap argument에 직접 설정한다. 이 단계에서는 OCCM을 설치하지 않으며
  `cloud-provider=external`도 설정하지 않는다. LoadBalancer, route, volume 등
  cloud provider 기능은 후속 범위다.
- ARM64 image 검증과 동일하게 control plane과 worker 모두 Nova config drive를
  사용한다. 로컬 metadata network의 준비 순서에 bootstrap 성공을 의존하지 않는다.
- global kubeconfig나 `$HOME/.cluster-api/clusterctl.yaml`을 사용하지 않는다.
  repository의 빈 `config/clusterctl.yaml`과 `.state/local-arm64/kubeconfigs` 아래의
  전용 kubeconfig만 명시적으로 전달한다.
- 모든 download는 version과 SHA-256으로 고정한다. credential 값과 workload
  kubeconfig는 Git 및 artifact에서 제외한다.
- 4 vCPU compute 위에서 세 nested VM의 최초 부팅이 겹치면 Calico exec probe가
  CPU scheduling 지연을 장애로 오인했다. 로컬 프로필에만 `calico-node` probe
  timeout 30초, failure threshold 12와 최대 15분 wait를 적용한다. 이는 성능
  개선이 아니라 제한된 feasibility 환경의 오탐 방지다.
- local compute memory는 10 GiB, control plane과 worker flavor memory는 각각
  2 GiB로 둔다. CPU 수와 고정 software 버전은 유지한다. 이는 5 GiB compute와
  1 GiB worker에서 관측된 압박을 줄이는 재현성 기준이며 성능 sizing 결론이 아니다.
- control plane과 worker managed security group의 TCP 22는 workload CIDR
  내부에서만 허용한다. controller의 프로젝트 전용 SSH keypair를 Nova에 등록하고,
  private key는 controller에만 유지한다.
- worker Available, Node 수/Ready 또는 Calico timeout이면 CAPI 상태와 controller
  log, Nova show/console, compute pressure/OOM을 자동 수집한다. 가능한 경우
  controller의 tenant qrouter namespace를 통해 workload VM에 SSH로 접속해
  cloud-init, kubeadm, kubelet과 containerd log도 수집한다. bootstrap token,
  certificate key와 application credential은 artifact 기록 전에 마스킹한다.

## 검토한 대안

- **CAPI/CAPO latest를 실행 시점에 동적으로 선택:** 새 release가 재실행 결과를
  바꾸며 검증된 조합을 재현할 수 없다.
- **이전 CAPI minor 사용:** Kubernetes v1.35 지원 범위가 더 좁거나 maintenance
  상태가 가까워진다. v1.13.4는 실행 시점 최신 v1.13 patch이며 v1.35 지원을
  release에서 직접 명시한다.
- **Cilium:** 유효한 대안이지만 M2에는 단순한 kube-proxy+Calico IP-in-IP/BGP
  경로가 이미 필요한 기능을 충족한다. eBPF dataplane 비교는 별도 실험이다.
- **OCCM으로 providerID 초기화:** OpenStack 서비스 통합에는 필요하지만 이번
  lifecycle 기준선에는 bootstrap-driven providerID가 더 작고 CAPO가 공식
  지원한다.
- **Octavia API load balancer:** HA endpoint를 제공하지만 현재 OpenStack 범위에서
  Octavia를 의도적으로 제외했고 control plane도 한 대다.
- **metadata service만 사용:** 정상 구성에서는 가능하지만 로컬 이미지의 기존
  Nova 검증도 config drive를 계약으로 사용한다. 최초 시도에서 config drive가
  빠진 VM은 ACTIVE가 된 뒤에도 cloud-init/kubeadm을 실행하지 못했다.

## 실행 및 검증 결과

다음 순서가 2026-08-11 전체 clean-room 로컬 ARM64 환경에서 다시 통과했다.

```bash
make capi-providers-install
make capi-providers-verify
make capi-credentials-verify
make workload-cluster-create
make workload-cluster-scale
make workload-cluster-verify WORKERS=2
```

- CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6, ORC v2.4.0 controller deployment가
  모두 Available이 됐다.
- application credential로 kind Pod에서 OpenStack 인증이 성공했다.
- control plane 1대와 worker 1대가 v1.35.7/ARM64/Ready가 됐고, Calico,
  CoreDNS, management-to-workload TCP 6443 probe와 Pod DNS probe가 통과했다.
- `MachineDeployment` 1→2 변경부터 최종 CNI/DNS/API 검증까지 약 2분이 걸렸다.
- 최종 상태는 CAPI `3/3 Available`, Nova server 3대 ACTIVE, Kubernetes Node
  3대 Ready다. 모든 Node는 `arm64`, v1.35.7과 `openstack:///...` providerID를
  보고했고 Calico node 3개와 DNS/CNI probe가 통과했다.
- 성공 상태에서 수동 진단을 실행해 Nova show/console 3개와 각 VM의 bootstrap
  log 3개를 수집했다. SSH 실패는 없었고 cloud-init 완료와 kubelet 시작을
  확인했으며 알려진 민감 패턴의 artifact 잔존은 0건이었다.
- 3개 workload VM이 실행 중일 때 compute는 9.7 GiB 중 7.2 GiB 사용,
  2.5 GiB available, swap 0 B였고 memory pressure와 kernel OOM 기록은 없었다.

## 알려진 제한과 남은 문제

- 2026-08-09 실행은 worker Nova VM과 OpenStackMachine이 ACTIVE/Ready였지만
  Machine Available과 Kubernetes Node 등록이 30분 안에 완료되지 않았다.
  macOS sleep이나 OpenStack/관리망 장애는 없었고 compute 메모리 압박은
  관측됐지만 당시 worker 내부 cloud-init/kubeadm log가 없어 원인은 미확정이다.
- 10 GiB compute와 2 GiB worker를 함께 적용한 clean-room 실행은 성공했으므로
  자원 압박이 기여했을 가능성은 있지만 어느 한 변경을 단일 원인으로 분리하지
  못했다. 새 진단 경로가 동일 장애의 재발 시 필요한 bootstrap 근거를 보존한다.
- 4 vCPU compute에는 최종 상태에서도 CPU pressure가 남았다. 클라우드/물리
  프로필에서는 probe 보정을 그대로 상속하지 말고 정상 자원에서 기본값을 다시
  검증하며 이 결과를 성능 자료로 사용하지 않는다.
- API endpoint는 한 control plane VM과 한 Floating IP에 의존하며 HA가 아니다.
- OCCM이 없으므로 OpenStack `LoadBalancer`, block volume과 cloud route 기능은
  검증하지 않았다.
- macOS의 `172.24.4.0/24` route는 workload API 접근에 필요하며 이번 실행 후
  의도적으로 유지했다. `local-down`이 제거할 수 있다.
- 자동 scaling 판단은 포함하지 않았다. M3에서 Cluster Autoscaler와 Pending
  Pod 기반 2→3 scale-up을 별도로 검증한다.

## 근거

- [CAPI version support](https://main.cluster-api.sigs.k8s.io/reference/versions.html)
- [CAPI v1.13.4 release](https://github.com/kubernetes-sigs/cluster-api/releases/tag/v1.13.4)
- [CAPO compatibility table](https://cluster-api-openstack.sigs.k8s.io/)
- [CAPO v0.14.6 release](https://github.com/kubernetes-sigs/cluster-api-provider-openstack/releases/tag/v0.14.6)
- [CAPO bootstrap-driven providerID](https://cluster-api-openstack.sigs.k8s.io/topics/external-cloud-provider)
- [ORC v2.4.0 release](https://github.com/k-orc/openstack-resource-controller/releases/tag/v2.4.0)
- [Calico v3.32.1 release](https://github.com/projectcalico/calico/releases/tag/v3.32.1)

## 재검토 조건

- Kubernetes minor 또는 CAPI/CAPO minor를 올리는 경우
- HA control plane 또는 upgrade 검증을 시작하는 경우
- OCCM, Cinder CSI, Octavia나 external-dns를 범위에 추가하는 경우
- cloud/bare-metal 프로필에서 Calico 대신 Cilium을 비교하는 경우
- local compute/worker 자원 또는 Calico probe 완화가 더 이상 필요하지 않은 경우
