# M3 readiness verification report — 2026-08-14

## Verdict

**NO-GO for M3 until workload guest clock recovery and the workload verification gate are fixed.**

The OpenStack data plane, management cluster, CAPI/CAPO providers, worker
Machines, Kubernetes Nodes, CNI and DNS are functional. However, all three
workload VMs are approximately 44 hours and 32 minutes behind the macOS host.
KubeadmControlPlane cannot inspect etcd because its TLS client connection is
rejected, so CAPI reports the control plane as `Available=Unknown` and
`Ready=Unknown`.

## Scope and immutable reference

- Environment: `local-arm64`
- Git commit: `b72a022dcfbff0b34f84a4ae9b1d511fc6b0178a`
- Branch state before verification: clean, `main` aligned with `origin/main`
- Verification run: `artifacts/local-arm64-20260814T091323Z-80679`
- Existing workload cluster was preserved.
- No clean-room deletion or repeated scale mutation was performed after the
  control-plane health failure was discovered.

## Results

| Gate | Result | Evidence |
|---|---|---|
| Host preflight | PASS with warning | 16 GiB RAM, 223 GiB available disk, Lima/socket_vmnet ready, expected management CIDR already present |
| Secret handling | PASS | `.state` ignored; secret directories/files have 0700/0600 permissions; no state or artifact files tracked by Git |
| Static tests | PASS with warning | 4 Python tests, Bash syntax and guest-clock self-test passed; ShellCheck is not installed |
| Inventory generation | PASS | controller `192.168.107.2`, compute `192.168.107.3` |
| Host clocks and management network | PASS | controller/compute skew 0 seconds; bidirectional management traffic passed |
| Nested KVM | PASS | compute booted the host kernel with `accel=kvm` |
| Kolla rendered configuration | PASS | controller `failed=0`, compute `failed=0` |
| Nova/Neutron control plane | PASS | scheduler, conductor, compute and all DHCP/L3/metadata/OVS agents were up |
| OpenStack guest/data path | PASS | CirrOS and Ubuntu boot, DHCP, Floating IP, SSH, outbound, host/Docker API and TCP 6443 probes passed; verification VM/FIP were removed |
| Kubernetes image in live workload | PASS for initial boot contract | three Nova VMs use `ubuntu-2204-kube-v1.35.7-arm64`; all Nodes report v1.35.7 and valid OpenStack provider IDs |
| Management kind cluster | PASS | v1.35.0 node and system Pods Ready; in-cluster OpenStack API probe passed |
| CAPI/CAPO providers | PASS | CAPI/CABPK/KCP v1.13.4, CAPO v0.14.6 and ORC v2.4.0 deployments Available |
| OpenStack application credential | PASS | token issue succeeded from a management-cluster Pod |
| Worker machine lifecycle state | PASS | MachineDeployment desired/current/ready/available = 2/2/2/2; Nova workload VMs ACTIVE |
| Workload Kubernetes function | PASS | control plane and two workers Ready; Calico, API, CNI and DNS probes passed |
| CAPI control-plane health | **FAIL** | KubeadmControlPlane `InspectionFailed`; etcd TLS connection reports an expired/not-yet-valid certificate condition |
| Workload VM clock persistence | **FAIL** | all three VMs reported `2026-08-12 12:54 UTC` while macOS reported `2026-08-14 09:27 UTC` |
| Verification gate strictness | **FAIL** | `make workload-cluster-verify WORKERS=2` exited 0 even though Cluster/KCP control-plane v1beta2 conditions were Unknown |
| Repeated 1→2→1→2 lifecycle | NOT RUN | stopped to avoid an uninterpretable bootstrap failure and extra resource pressure while clocks were invalid |
| Full clean-room rebuild | NOT RUN | destructive rebuild deferred until the blocking clock/readiness issue is corrected |

## Blocking defect: nested workload clocks do not recover after host suspension

Observed on every workload node:

```text
osk8s-workload-control-plane-vck8z  Wed Aug 12 12:54 UTC 2026
osk8s-workload-md-0-22v6h-7hbg2   Wed Aug 12 12:54 UTC 2026
osk8s-workload-md-0-22v6h-l92st   Wed Aug 12 12:54 UTC 2026
macOS                               Fri Aug 14 09:27 UTC 2026
```

On the control-plane VM, the RTC was correct (`2026-08-14 09:28 UTC`) while
the system clock was stale. Chrony was active and had valid sources, but
reported the system approximately 160,365 seconds slow. The image contains
the default `makestep 1 3`, which permits large steps only during the first
three updates and does not repair this post-suspend jump.

The local automation currently validates and repairs controller/compute Lima
guest clocks, but does not apply an equivalent readiness gate to the nested
CAPO workload VMs.

The resulting KCP controller error is:

```text
Failed to get etcd status: context deadline exceeded
remote error: tls: expired certificate
```

Etcd itself is healthy when checked locally inside the etcd Pod; this is a
cross-clock TLS failure, not an etcd quorum/storage failure.

## Secondary risks

- Controller memory was under pressure: about 1.1 GiB available and the 2 GiB
  swap was almost fully used. Compute had about 2.0 GiB available with three
  workload VMs. The first automated scale test should therefore be worker
  1→2, not 2→3.
- Recent workload events contain intermittent API, Calico, CoreDNS and etcd
  probe timeouts consistent with the constrained local CPU/memory environment.
- The MachineDeployment does not yet have Cluster Autoscaler min/max
  annotations. This is expected M3 work, not an M2 defect.
- ShellCheck has not been run on this host.

## Required fixes before M3

1. Add a bounded workload-node clock check against the host or RTC before any
   workload verification or scale operation.
2. Add an explicit recovery path for large post-suspend jumps, scoped to the
   local profile (for example a controlled chrony step on existing workload
   VMs after outer-host recovery).
3. Make workload verification fail unless the Cluster and
   KubeadmControlPlane v1beta2 `Available` condition is `True`, control-plane
   desired/ready/available counts match, and no `InspectionFailed` condition
   remains.
4. Re-run workload verification after clock repair and wait until KCP/Cluster
   conditions recover.
5. Reset to one worker and run 1→2→1→2 lifecycle verification, checking Nova,
   CAPI and Kubernetes for orphan resources after each transition.
6. Run a clean-room rebuild only after the non-destructive gates pass.
7. Install ShellCheck and record a full lint pass.

## M3 entry criteria

M3 can proceed when the above fixes are implemented and a new report shows:

- workload node clock skew within the configured bound after host sleep/resume;
- Cluster and KubeadmControlPlane Available/Ready conditions true;
- repeatable manual 1→2 scale and 2→1 cleanup without orphan resources;
- all existing OpenStack, management-provider and workload probes still pass.
