# 기반작업 1-4 라이브 배포·검증 — 2026-09-24

이 문서는 최초 배포 당시의 기록이다. 이후 수정과 확대된 수용 시험은 [기반작업 1순위 종합 검증](../docs/foundation-priority1-final-validation-2026-09-24.md)에 별도로 기록한다.

## 적용 결과

- GCP 프로젝트 `openstack-k8s`, 서울 리전. `osk8s-telemetry` 서비스 계정에 Logging writer·Monitoring metric writer, 증거 bucket의 object creator 권한을 부여하고 GCE 3대에 연결했다.
- Cloud Logging 서울 `osk8s-observability` bucket은 검색 보존 30일이다. `osk8s-otel` 전용 sink 유입을 확인한 뒤 `_Default`에 `osk8s-otel-dedup` 제외 규칙을 넣었다. 기존 다른 로그의 기본 sink 필터는 유지했다.
- `gs://osk8s-724098042704-evidence/`에 공개 접근을 막고, 기존 실행 `autoscaler-cycle-20260923T130704Z-c167db10`의 manifest·result 두 객체를 업로드해 목록으로 확인했다. manifest는 8단계, Machine 5개, 실행 소유 Pod 4개를 인덱싱하며 과거 `nova` 조회 누락을 보존한다. 이 과거 실행은 수집기 설치 전이므로 당시의 Cloud Monitoring 시계열과 연결됐다고 주장하지 않는다.
- controller와 compute 2대에 호스트 OTel Collector·heartbeat를 systemd로, management kind에 node-agent 1/1·cluster-state 1/1, workload Kubernetes에 node-agent 2/2·cluster-state 1/1을 배포했다. 클러스터 수집기는 mTLS로 controller gateway에 전송한다.
- controller의 기존 기본 Ops Agent는 새 수집기와 지표·syslog가 겹쳐 비활성화하고 자동 설치 정책 label을 제거했다. Terraform의 controller label 선언도 수정했다.

## 실측

`make observability-verify`는 **2026-09-24 01:56:09–02:26:09 UTC** 구간에서 `state=complete`, `missing=[]`를 반환했다. 세 GCE 호스트와 management·workload의 CPU·메모리·디스크·네트워크가 조회됐고, Kubernetes Node·Pod·container의 지표와 두 클러스터 각각의 `k8s_node_condition_ready`, `k8s_pod_phase`, `k8s_deployment_available` 지표도 조회됐다. 모든 선택 지표의 마지막 샘플은 구간 종료에서 5분 이내였다.

전용 Logging bucket에서는 세 호스트의 JSON heartbeat, Nova compute·hypervisor·server 상태, 실제 Nova API 로그, workload Pod 로그의 namespace·Pod UID 라벨, kubelet/containerd journal, Kubernetes Events를 조회했다. 구조화된 Nova 로그에서 control plane 서버 `1a7694df-3fca-4120-b693-fc17c82c44a2`가 `osk8s-compute01`, worker 서버 `b8e678a7-a463-4e90-b54e-bb98c586f63f`가 `osk8s-compute02`에 `ACTIVE`로 배치된 것을 확인했다. 검색 예:

```text
log_id("osk8s-otel") AND jsonPayload.kind="nova_server"
log_id("osk8s-otel") AND labels."k8s.pod.uid":*
log_id("osk8s-otel") AND labels."event.domain"="k8s"
```

수집기 실제 설치 과정에서 management kubeconfig의 오래된 CA, 워크로드 VM `SHUTOFF`, workload kubeconfig의 오래된 CA, OTel receiver 이름·옵션, kubelet 이름 DNS 해석, `k8s_cluster` RBAC 누락, Kolla 로그 심볼릭 링크, heartbeat의 잘못된 JSON을 발견해 수정했다. 최종 `make lint`는 66개 테스트와 shell 정적 검사를 통과했다.

## 아직 수용하지 않은 범위

- 최종 구성으로 **끊김 없는 정상 30분** 전체의 샘플 간격·큐 드롭·수집 지연 분포는 검증하지 않았다. 위 30분 조회는 중간에 수집기 재배포가 포함된 구간이다.
- 수집기를 켠 상태에서 새 worker의 `1→2→3→2→1→2→1` 자동 증감, 삭제된 worker의 과거 시계열·Pod UID 검색은 아직 재실행하지 않았다. 업로드한 실행 manifest는 수집기 설치 전의 기존 결과다.
- worker NotReady, Pod 반복 실패, Ingress 경로 실패 및 collector/controller 전송 장애의 전·중·후 수용 시험을 하지 않았다. Ingress 능동 경로는 기반작업 9번에 의존한다.
- CAPI/Cluster Autoscaler 내부 reconcile Prometheus endpoint, Grafana 대시보드·경보는 미구현이다. 현재 CAPI/CA의 Pod 상태·로그·Events와 Kubernetes 상태 지표는 수집한다.
- 고객 로그를 넣기 전에 세부 비밀정보 차단, 접근 분리·보존·삭제 정책과 kubelet TLS CA 검증을 강화해야 한다. 현재 GCS 증거 bucket에는 자동 삭제가 없다.

GCE 호스트에는 기존 최대 10시간 자동 STOP이 적용된다. 호스트가 중지되면 수집도 중지되며, 다음 기동 시 `make gcp-openstack-recover`, `make observability-workload-guests-start` 순서로 OpenStack과 현재 CAPI VM을 복구한다. 수집기와 Kubernetes DaemonSet/Deployment는 실행 환경이 켜지면 자동 시작한다.

검증 후 작업 전 상태를 복원하기 위해 GCE controller·compute 3대를 중지했으며, 각각 GCP에서 `TERMINATED`를 확인했다. 중앙 Logging·Monitoring·GCS 자료와 설치된 수집기 설정은 유지된다.
중지 후에도 같은 과거 구간을 다시 조회한 결과, 지표 10개 범주와 heartbeat·Nova·Kolla·Pod·Event 로그 출처가 모두 `state=complete`, `missing=[]`로 조회됐다.
