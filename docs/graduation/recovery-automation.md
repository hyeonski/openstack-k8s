# 3·4·5번 복구 자동화 실행 계약

이 문서는 1번(S1 서비스·부하·기준선), 2번(S1 수동 재배치) 다음 작업의 구현과 실행 계약이다. 실제 통과 여부와 측정값은 별도 검증 기록으로 구분한다.

## 실행 순서

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s1-prepare
make graduation-s1-spread
make graduation-s1-auto
make graduation-s1-cleanup
make graduation-foundation
make graduation-csi
make graduation-s2
make graduation-s2-cleanup
make graduation-s3
make graduation-s3-cleanup
make graduation-env-down
```

API 터널은 실험 프로세스가 종료될 때까지 유지해야 한다. 각 시나리오는 상태 파일과 artifact 디렉터리에 단계·관계·원본 자료를 남긴다. 중단된 실행을 새 실행으로 덮어쓰지 않으며 해당 cleanup을 먼저 수행한다. 다른 실행과 소유권이 다르면 삭제나 정책 변경을 보류한다.

실험 제어 명령은 기존 controller의 OpenStack 관리자 자격증명과 호스트 SSH 경로를 사용한다. CSI에는 기존 CAPO 프로젝트의 제한된 application credential을 전달한다. 실험 전용 자원의 소유권 검사는 구현했지만, 운영용 최소 권한 서비스 계정으로 제어기를 분리·배포한 구성은 아니다.

## 3번: S1 자동 판단·목적지 선택·재배치

현재 실험 구성은 compute01 8 vCPU·32 GiB, compute02 4 vCPU·16 GiB다. workload control plane·요청 Pod와 복구 목적지 worker는 compute01에, 서비스 소스 worker와 경쟁 VM은 compute02에 둔다. 용량 변경 근거와 기존 결과의 범위는 [ADR-0017](../adr/0017-increase-recovery-target-compute-capacity.md), 실제 통과 기록은 [통합 검증](recovery-validation-2026-10-02.md)을 따른다.

`graduation-s1-spread`는 측정 전 배치를 확인한다. 두 worker가 같은 compute에 있으면 현재 prepare에서 새로 생겼으며 일반 Pod·연결 볼륨이 없는 worker만 다른 활성 compute로 live block migration한다. 기존 worker나 서비스 VM은 이 준비 조치의 대상이 아니다. S1·worker 제어 잠금을 사용하며 이동 전후 VM/Node 식별자와 Nova 배치를 기록한다. 이미 worker가 분리돼 있으면 변경하지 않는다. 이 준비 단계의 VM 이동과 장애 주입 후 제어기의 Pod 재배치를 구분한다.

- 정상 기준선과 비교해 60초 구간에서 p95 1.5배 초과 또는 실패 증가를 확인한다.
- 같은 구간의 서비스 compute CPU 사용률 70% 이상, CPU PSI 2% 이상 및 기준선의 2배 이상을 요구한다.
- 요청 누락·중복, CPU 카운터 누락·초기화, Pod throttling, 메모리·I/O 경합은 자동 조치를 보류하는 조건이다.
- 두 구간 연속으로 조건을 만족한 뒤 기존 Pod·이미지·Nova·Deployment가 바뀌지 않았는지 다시 확인한다.
- Node–Machine–Nova 관계, 다른 compute 배치, Ready·taint·affinity·nodeSelector·CPU/메모리 요청량, 목적지 호스트 부하와 자료 시각을 검사한다.
- UID와 resourceVersion을 조건으로 Deployment를 한 번 수정한다. maxSurge=1/maxUnavailable=0을 유지하고 다른 템플릿 구성은 보존한다. 자동 조치 후 15분 cooldown을 기록한다.
- 재배치 후 30초 대기하고 60초 구간을 최대 8회 관측한다. p95가 기준선 1.2배 이내이고 요청 실패·중복·표본 공백이 없는 구간이 3회 연속이어야 안정화로 판정한다. 악화 구간에서는 연속 횟수를 0으로 초기화한다. 관측 상한까지 안정화되지 않으면 needs_review이며 추가 이동이나 임계값 완화는 하지 않는다. 전체 부하 종료 전 마지막 60초에도 같은 회복 기준을 요구하고, 전체 요청이 모두 성공했는지 검사한다. 사전 시험의 고정 시점 판정과 최종 정책의 실행 기록을 구분한다.
- 경합 VM은 회복 관측과 최종 CPU 확인이 끝날 때까지 유지한다. 다른 원인으로 경합이 사라진 결과를 재배치 효과로 인정하지 않는다.

## 4번: S2 공통 출구와 Neutron QoS

시험 경로는 다음과 같다.

```text
외부 probe(namespace) → worker A Floating IP:30080 → API
API 응답 및 upload A/B → Neutron router → controller veth → 외부 sink(namespace)
                         ↑ upload B의 Neutron port egress QoS
```

전용 `s2-egress` veth에 20 Mbit/s TBF와 1 MiB 큐를 구성한다. 기존 관리 인터페이스의 속도는 바꾸지 않는다. 두 서비스의 합산 송신이 이 출구를 통과하는지는 해당 인터페이스의 byte/overlimit/drop 카운터와 외부 요청/업로드 완료 기록으로 확인한다. 실험용 20 Mbit/s 설정을 실제 인프라 전체의 용량으로 일반화하지 않는다.

API는 256 KiB 응답을 2 RPS로 전송한다. 업로드는 1 MiB 청크의 체크섬을 검증하고 외부 수신 측 파일·SQLite 기록을 fsync한 뒤 승인한다. 재전송 청크는 중복 집계하지 않으며 Pod 재배치 후 수신 측 체크포인트에서 재개한다.

무제어 연속 두 구간에서 API p95 1.5배 초과/실패 증가, 출구 80% 이상 사용, overlimit 증가, 업로드 진행을 요구한다. compute CPU 70% 미만도 확인한다. 다른 중요한 일반 Pod나 기존 QoS가 있는 목적지 포트는 사용하지 않는다.

목적지 포트에 QoS를 먼저 설치하고 OVS `ingress_policing_rate`까지 확인한 후 Recreate 방식으로 업로드를 분리한다. 고정 10 Mbit/s, 분리만 한 무제한 비교, 6/10/14/18 Mbit/s 단계 정책을 같은 API 부하에서 측정한다. 두 QoS 방식의 burst 상한은 사전 보정 후 250 kbit로 고정한다. 이는 실제 업로드 처리량을 보장하는 값이 아니므로 수신 완료 bytes도 별도로 비교한다. 단계마다 60초 관측하고 악화 시 한 단계 낮춰 두 구간 안정화를 확인한다. 무한 재시도하거나 6 Mbit/s 아래로 낮추지 않는다. API p95 1.3배 이내·실패 없음·업로드 bytes 증가가 함께 있어야 회복이다.

cleanup은 namespace, 전용 정책, 추가 보안 그룹, Floating IP, 전용 출구를 제거하고 원래 worker 수·모드를 복원한다. 정책 적용 전 기존 QoS가 없는 포트만 허용하므로 해제는 원래의 무정책 상태로 돌아가는 것이다.

## 5번: S3 Cinder·CSI와 PostgreSQL 복구

Cinder LVM은 controller의 전용 20 GiB 파일에 생성한다. `graduation-cinder` VG와 systemd loop 연결을 사용하며 일반 디스크를 초기화하지 않는다. 단일 controller 저장소이므로 worker 장애에서 독립적이지만 스토리지 고가용성은 제공하지 않는다. 기반 저장소는 cleanup 후에도 유지한다.

Cinder CSI v1.35.0의 공식 매니페스트를 저장소에 고정했다. controller plugin은 workload control plane에 두고, Secret은 기존 제한된 CAPO application credential에서 메모리로 구성한다. 비밀 값을 실행 증거에 기록하지 않는다. `graduation-cinder` StorageClass는 WaitForFirstConsumer와 Delete 정책을 사용한다.

- 단일 PostgreSQL 16.10과 1 GiB PVC에 PGDATA 및 WAL을 저장한다. fsync·synchronous_commit·full_page_writes가 모두 켜져 있는지 확인한다.
- 1,000개 커밋 완료 레코드의 개수·내용 해시를 DB 외부에 보존한다.
- 해당 Machine에 소유 토큰이 있는 skip-remediation annotation을 설치하고 worker를 fixed 모드로 둔다.
- 실험 중 controller-manager의 시간 초과 강제 분리를 비활성화한다. 원래 파일과 해시를 기록하고 테스트 자원이 제거된 뒤 원래 정책을 복원한다. 기본 정책과 시험 정책을 혼동하지 않는다.
- 소스 worker의 kubelet API 통신과 DB 클라이언트 경로를 전용 iptables chain으로 차단한다. `crictl`로 기존 DB 컨테이너가 여전히 실행 중임을 확인한다.
- Node 이상과 지속적인 실제 DB 요청 실패가 함께 있어야 복구를 시작한다.
- Nova SHUTOFF, task_state 없음, power_state=4, libvirt `shut off`를 모두 확인한다. ACTIVE 응답은 거절하는 검증도 수행한다.
- 종료 확인 직후 같은 관계를 다시 확인하고 소유 토큰으로 out-of-service taint를 부여한다. Pod 강제 삭제, Cinder 강제 detach, finalizer 제거는 사용하지 않는다.
- CSI의 detach/attach와 StatefulSet Pod 변경을 기록하고, 동일 PVC UID/PV/volume ID가 다른 worker VM에 단독 연결됐는지 검증한다.
- 기존 1,000개 커밋 데이터 보존, 새 트랜잭션의 커밋·조회, 60회 연속 서비스 성공을 확인한다. 응답이 불명확한 진행 중 트랜잭션까지 보존됐다고 주장하지 않는다.
- cleanup은 DB/PVC 제거와 볼륨 삭제 확인 후에만 기존 VM을 다시 시작한다. 네트워크 규칙·taint·MHC annotation·controller 설정·worker 상태를 복원한다.

## 공식 동작 근거

- [Kolla 2025.2 Cinder LVM](https://docs.openstack.org/kolla-ansible/2025.2/reference/storage/cinder-guide.html)
- [Kolla Neutron QoS](https://docs.openstack.org/kolla-ansible/2025.2/reference/networking/neutron.html)
- [Cinder CSI v1.35.0 매니페스트](https://github.com/kubernetes/cloud-provider-openstack/tree/v1.35.0/manifests/cinder-csi-plugin)
- [Kubernetes 비정상 노드 종료와 out-of-service](https://kubernetes.io/docs/concepts/cluster-administration/node-shutdown/)
- [Cluster API remediation 제외](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking.html)
