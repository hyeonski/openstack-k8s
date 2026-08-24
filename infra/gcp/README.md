# GCP infrastructure

이 디렉터리는 기존 `openstack-k8s` GCP 리소스를 OpenTofu/Terraform으로 선언하고
안전하게 채택·검증한다. 기본 경로는 기존 인프라와 선언이 일치하는지 확인하는
것이며, plan을 검토하지 않은 apply는 허용하지 않는다.

## 고정 리소스

- project/zone: `openstack-k8s`, `asia-northeast3-a`
- VPC/subnet: `osk8s-mgmt`, `osk8s-seoul` (`10.20.0.0/24`)
- controller: `10.20.0.10`
- compute01/02: `10.20.0.21`, `10.20.0.22`
- Kolla alias VIP: `10.20.0.250`
- Floating IP route: `172.24.4.0/24 → osk8s-controller`
- 모든 지속 호스트: 36,000초 후 `STOP`

Network, subnetwork, 내부 주소와 지속 호스트에는 `prevent_destroy`가 적용된다.

## 초기 채택

```bash
make gcp-iac-init
make gcp-iac-validate
make gcp-iac-import
make gcp-iac-plan
make gcp-iac-show-plan
```

정상 결과는 `No changes`다. replacement 또는 destroy가 표시되면 apply하지 않는다.
state, backup과 saved plan은 Git에서 제외된다.

## 일회성 Kubernetes image builder

```bash
make kubernetes-image-builder-create
make kubernetes-image-build
make kubernetes-image-upload
make kubernetes-image-verify
make kubernetes-image-builder-destroy CONFIRM=cloud-gcp-amd64
```

builder 생성/삭제 validator는 `osk8s-image-builder` 한 대 이외의 plan을 거부한다.
빌더도 36,000초 자동 STOP 계약을 사용한다.

## Controller management network

```bash
make gcp-controller-management-prepare
make management-cluster-create
make management-cluster-verify
```

controller에는 management API용 network tag와 IAP TCP 16443 접근만 허용한다.
public Kubernetes API firewall은 생성하지 않는다. kind network와 NAT lifecycle은
controller의 systemd unit이 담당한다.

## 안전 확인

```bash
make gcp-iac-plan
make gcp-status
```

검토 항목은 다음과 같다.

- 전체 plan `No changes`
- controller와 compute 두 대의 정확한 이름·내부 IP
- `canIpForward=true`
- compute nested virtualization
- `maxRunDuration=36000s`, termination action `STOP`
- Floating IP route의 destination과 controller next hop
