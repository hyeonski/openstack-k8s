# GCP OpenStack Kubernetes Testbed

GCP의 중첩 가상화 VM에 OpenStack을 배포하고, CAPI·CAPO·Cluster Autoscaler로
Kubernetes worker 자동 증감과 S1~S4 장애 대응·복구를 검증하는 테스트베드다.
현재 운영·설계·과거 결과는 [문서 안내](docs/README.md)에서 구분한다.

## 처음 열었다면

**기반 구축은 `scripts/`, 장애 실험은 `experiments/`부터 읽는다.**
반복 평가와 상시 관측은 필요한 경우에만 사용하는 별도 기능이다.

| 하고 싶은 일 | 먼저 볼 코드 | 읽는 순서 |
|---|---|---|
| 테스트베드가 어떻게 만들어지는지 이해 | [lab-up.sh](scripts/lab-up.sh) | GCP → OpenStack → 이미지 → management → workload → Autoscaler |
| 기존 환경을 켜고 끄는 동작 이해 | [graduation_env.py](scripts/graduation_env.py) | `ensure()` → 서비스·게스트 확인 → `down()`의 소유 호스트 종료 |
| 장애 실험 하나 실행·이해 | [run.sh](experiments/run.sh) | 시나리오 선택 → 아래 시나리오 실행기 → 정리 |
| 공통 환경·OpenStack 접근 이해 | [runtime.py](scripts/lib/runtime.py) | 환경 정체성·worker 상태·관리 명령. 특정 시나리오를 import하지 않음 |
| 네 시나리오 반복·비교 평가 | [평가 실행기](evaluation/graduation_evaluation.py) | 선택 기능. 조건 고정 → 실행 집합 → 독립 검증 |
| 클라우드 상시 관측 설치 | [관측 가이드](observability/README.md) | 선택 기능. 수집·전송·조회. 로컬 실험 증거와 별개 |

시나리오별 중심 코드는 [S1 자동 재배치](experiments/graduation_s1_auto.py),
[S2 QoS](experiments/graduation_s2.py), [S3 DB 복구](experiments/graduation_s3.py),
[S4 실행 순서](experiments/graduation_s4_workflow.py)다. 테스트는 `tests/`, 실제 배포할
서비스·CAPI 매니페스트는 `kubernetes/`, GCP 선언은 `infra/`, OpenStack 호스트 준비는
`ansible/`·`kolla/`에 있다. 과거 검증 기록은 처음 코드를 읽을 때 모두 읽을 필요가 없다.

## 기존 환경에서 가장 자주 쓰는 명령

실제 배포의 override를 지정한 뒤 시작한다. 환경이 없다면 아래 **최초 구축** 절차를 따른다.

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make lab-start
make lab-status
make experiment SCENARIO=s1
make lab-stop
```

`SCENARIO=s1|s2|s3|s4`로 선택한다. S1은 자동 재배치 실험이다. S2·S3는 먼저
`make experiment-foundation`으로 QoS·Cinder·CSI를 준비해야 한다. 이 준비는 서비스 재배포를
포함하므로 다른 실험이 남아 있으면 실행하지 않는다.

실험 성공 후에는 해당 자원을 정리한다. 실패하면 증거와 상태를 보존하고 중단하므로
`make experiment SCENARIO=s1 ACTION=status`로 확인한 뒤 `ACTION=cleanup`을 사용한다.
S4의 동일 실행 재개는 `ACTION=resume`이다. `lab-stop`은 미완료 실험이 있으면 거부한다.

`make help`는 이 기본 흐름만 표시한다. 세부 절차는 `help-experiments`, 관측·반복 평가는
`help-observability`·`help-evaluation`, 기존 저수준 명령은 `help-all`에서 찾는다.
루트 [Makefile](Makefile)은 진입점이고 상세 연결은 [인프라](make/infrastructure.mk),
[실험](experiments/commands.mk), [관측](observability/commands.mk), [평가](evaluation/commands.mk)에 있다.
기존 `graduation-*` 등의 명령 이름도 유지한다.

## 테스트베드 구조

```text
운영 클라이언트 ─ IAP ─ GCP controller
                       ├─ OpenStack 관리·네트워크 서비스
                       └─ kind management: CAPI·CAPO·Autoscaler
GCP compute 2대 ─ nested KVM ─ OpenStack Nova VM
                              └─ workload Kubernetes: control plane·worker
```

management는 workload 클러스터를 관리하고, workload에서 실험 서비스를 실행한다.
GCP 호스트와 workload control plane은 고정이며 worker Nova VM만 증감한다.
공개 Kubernetes API 방화벽을 만들지 않고 IAP를 사용한다. Autoscaler는
management 내부에서 workload control-plane Floating IP에 직접 접근한다.

## 설정과 명령의 기준

상세 버전·IP·VM 사양·옵션은 아래 코드에서 확인한다. 문서의 과거 측정 조건은
해당 검증 당시의 값이므로 현재 설정으로 소급 바꾸지 않는다.

| 확인할 내용 | 기준 파일 |
|---|---|
| 명령 목록·인자·스크립트 연결 | [Makefile](Makefile), 위의 영역별 `.mk`, `make help-all` |
| 고정 버전·이미지 digest·API 포트·worker 범위 | [기본 환경 설정](config/environments/cloud-gcp-amd64.env) |
| 환경별 project·사용자·state 분리 | [override 예제](config/environments/local.env.example), [공통 로더](scripts/lib/common.sh) |
| GCP 호스트·주소·방화벽·자동 STOP | [main.tf](infra/gcp/main.tf), [variables.tf](infra/gcp/variables.tf) |
| 기본 OpenStack 서비스 | [Kolla 템플릿](kolla/globals-cloud-gcp-amd64.yml.tpl) |
| workload 노드·네트워크 선언 | [CAPI 템플릿](kubernetes/capi/workload-cluster.yaml.tpl) |
| Autoscaler 정책 | [management 매니페스트](kubernetes/cluster-autoscaler/management.yaml.tpl) |
| 전체 구축 순서 | [lab-up.sh](scripts/lab-up.sh) |

기본 Kolla 배포와 별도로 졸업작품 foundation은 Neutron QoS·Cinder LVM을 추가한다.
[실험 운영 가이드](docs/graduation/experiments.md)의 S2·S3 준비 절차를 따른다.
kind 전용 bridge/NAT는 systemd가 관리하며 Kolla Docker daemon의 네트워크 설정을
임의로 바꾸지 않는다. 구성 선택 이유는 [ADR](docs/adr/README.md)에 있다.

## 최초 구축

운영 클라이언트에는 인증된 `gcloud`, OpenTofu 또는 Terraform, `kubectl`, Python 3,
`curl`, `rsync`, `tar`, `ssh-keygen`이 필요하다. 개발 검사에는 ShellCheck·ripgrep도 사용한다.
Google 계정 인증, project 생성과 Billing 연결은 먼저 준비한다.

```bash
cp config/environments/local.env.example /tmp/openstack-k8s.env
# 예제의 project·사용자를 실제 환경에 맞게 수정
export ENV_OVERRIDE_FILE=/tmp/openstack-k8s.env
make bootstrap-preflight
make gcp-bootstrap CONFIRM=cloud-gcp-amd64-greenfield
make gcp-iac-init
make gcp-iac-validate
make gcp-foundation-plan
make gcp-foundation-show-plan
```

저장된 plan을 검토한 뒤 다음 단계로 진행한다. 위 확인값은 예제 환경 이름이며
`CONFIRM`은 선택한 override의 `ENVIRONMENT_NAME`과 일치해야 한다.

```bash
make gcp-foundation-apply CONFIRM=cloud-gcp-amd64-greenfield
make lab-up CONFIRM=cloud-gcp-amd64-greenfield
```

foundation validator는 지속 리소스의 create만 허용하며 update·replace·delete와
일회성 image builder·Floating IP route 변경을 거부한다. route는 호스트 외부 네트워크와
OpenStack bootstrap 이후에 별도로 적용한다. 수동으로 단계를 진행한다면
`gcp-floating-ip-route-plan` → `gcp-floating-ip-route-show-plan` →
`gcp-floating-ip-route-apply` 순서로 확인한다. 상세 단계는 `lab-up.sh`를 따른다.

`lab-up`은 기존 foundation과 checksum이 맞는 이미지 산출물을 재사용하지만,
기존 workload 클러스터와 worker 제어 기록 또는 CA가 있으면 생성 재적용을 거부한다.
실패 시 로그·상태를 보존하며, 구축 완료 환경의 일반 재기동에 사용하지 않는다.
이미지 빌더는 격리된 plan으로 관리하고 삭제 후에도 QCOW2·checksum·metadata를 보존한다.

## 기존 환경 운영

매 세션에서 실제 배포와 일치하는 `ENV_OVERRIDE_FILE`을 먼저 지정한다.
기동·복구·검증은 `make lab-start`를 사용한다(`graduation-env-ensure`와 같은 동작).
없는 기반 인프라를 새로 만들지 않으며 종료는 해당 실행이 기동한 호스트만 대상으로 한다.

| 작업 | 실행 절차 |
|---|---|
| 기존 인프라를 처음 state로 채택 | `gcp-iac-init` → `gcp-iac-validate` → `gcp-iac-import` → `gcp-iac-plan` → `gcp-iac-show-plan` |
| 평상시 IaC 대조 | `make gcp-iac-plan`의 정상 기대값은 `No changes`. 예상하지 않은 교체·삭제 시 apply하지 않음 |
| 상태만 조회·수렴 대기 | `workload-cluster-status` / `workload-cluster-verify`. 기존 kubeconfig·터널을 사용하며 설정·시험 자원을 변경하지 않음 |
| 의도한 설정 적용·능동 통신 검사 | `workload-cluster-prepare` / `workload-cluster-probe`. probe는 소유 임시 Pod를 사용하고 실패 증거를 보존 |
| worker 수동·자동 제어 및 시험 복구 | [worker 운영 가이드](docs/operations.md) |
| 장애 실험·최종 평가 | [S1~S4 운영](docs/graduation/experiments.md), [평가 계약](docs/graduation/final-evaluation.md) |
| 관측 배포·조회 | [관측 가이드](observability/README.md) |

`gcp-host-verify` 외에 controller→compute SSH와 실제 nested kernel boot 검사가 필요하다.
`gcp-openstack-recover`는 OpenStack 서비스 준비를 확인하지만 Nova guest를 시작하지 않는다.
관리 IP inventory는 IaC의 `host_internal_ips` output으로 생성한다.

## 상태·삭제 경계

비밀·생성 상태는 `.state/<환경 이름>`에 두고 secret 디렉터리 `0700`, 파일 `0600`을 유지한다.
기존 기본 환경의 IaC state 위치는 보존하며 새 환경은 `.state/<환경 이름>/tofu`로 분리한다.
state·backup·saved plan·비밀·실험 원본 `artifacts/`는 Git에 넣지 않는다.

관리 네트워크·내부 주소·지속 호스트는 `prevent_destroy`로 보호한다. 삭제 명령은
환경 확인값을 요구하며, workload 삭제는 클러스터 이름도 확인한다. 삭제 범위는 각각
kind와 전용 네트워크·클라이언트 kubeconfig, 지정 CAPI Cluster와 CAPO 소유 리소스,
일회성 image builder다. controller·compute·OpenStack persistent state·project secret은 보존한다.
실행 소유 자원 정리와 실패 시 복원은 [운영 가이드](docs/operations.md)를 따른다.

## 검증

`make secrets-check`는 비밀 권한·Git 제외를, `make lint`는 Shell 구문·ShellCheck·Python
테스트와 제거된 자동화의 재유입을 검사한다. `make preflight`는 기존 기반의 준비 상태를
확인한다. 로컬 검사의 통과와 실환경 수용을 구분한다.

자동 증감 시험은 Pod CPU requests와 replica를 바꿔 CA의 확장·축소와 자원 회수를 검증한다.
실제 CPU 사용량에 따른 성능·고객 HTTP 무중단 보장은 별도다. 최신 종합 실험 결과는
[2026-10-04 마감 평가](docs/graduation/final-evaluation-results-2026-10-03.md),
남은 구현·운영 과제는 [기반 우선순위](docs/product/infrastructure-priorities.md)를 따른다.

향후 고객용 제품 아이디어는 [기획 한 문서](docs/product/plan.md)에 보관한다. 현재 테스트베드의 필수 구현 범위는 아니다.
