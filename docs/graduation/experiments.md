# S1~S4 실험 운영

현재 코드의 실행 전제·순서·복원 경계를 설명한다. 시나리오의 목적은
[장애 정의서](failure-scenarios.md), 고정 반복 평가의 조건·비교군·해석은
[평가 계약](final-evaluation.md), 실측 결과는 [최종 평가](final-evaluation-results-2026-10-03.md)를 따른다.

## 공통 준비와 코드 기준

기존 테스트베드에서 올바른 환경 override와 API 터널을 유지하는 실행 세션을 사용한다.
환경이 없으면 [최초 구축](../../README.md)을 먼저 수행한다. 실험끼리 동시에 실행하지 않는다.

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
```

준비는 원래 worker 모드·대수를 기록하고 시험에 필요한 `fixed`·2대로 전환한다.
정리는 해당 실행 소유 자원만 제거한 뒤 원래 모드·대수를 복원한다.
모든 실험 정리가 끝난 뒤 `make graduation-env-down`으로 환경 실행이 기동한 호스트만 종료한다.
실행 ID·UID·조회 결과가 불명확하면 새 실행으로 덮어쓰거나 강제로 정리하지 않는다.

| 확인할 설정·동작 | 코드 기준 |
|---|---|
| 명령 인자와 기본값 | [Makefile](../../Makefile) |
| S1 서비스·요청·기준선 | [app.py](../../kubernetes/graduation-s1/app.py), [loadgen.py](../../kubernetes/graduation-s1/loadgen.py), [graduation_s1.py](../../scripts/graduation_s1.py) |
| S1 경합·자동 진단·회복 정책 | [경합 실행기](../../scripts/graduation_s1_contention.py), [자동 대응의 POLICY·판정 함수](../../scripts/graduation_s1_auto.py) |
| S2 경로·QoS 단계·판정 | [S2 실행기](../../scripts/graduation_s2.py), [네트워크 준비](../../scripts/graduation-s2-network.sh) |
| S3 저장소·fencing·데이터 검증 | [foundation](../../scripts/graduation-foundation-remote.sh), [CSI 설정](../../kubernetes/graduation-s3/csi/kustomization.yaml), [S3 실행기](../../scripts/graduation_s3.py) |
| S4 교체·서비스·시간 상한 | [MHC](../../kubernetes/graduation-s4/machine-health-check.yaml.tpl), [HTTP 서비스](../../kubernetes/graduation-s4/http-service.yaml), [실행기](../../scripts/graduation_s4_run.py), [workflow](../../scripts/graduation_s4_workflow.py) |
| 반복 평가의 고정 부하·횟수·사양 | [graduation-evaluation.json](../../config/graduation-evaluation.json) |

수치 정책을 바꾸면 과거 측정 결과의 조건도 같다고 간주하지 않는다. 평가 중 조건 변경은
별도 cohort로 분리한다. 클러스터 제어·자동 증감 시험의 수명주기는 [운영 가이드](../operations.md)를 따른다.

<a id="s1-baseline"></a>

## S1 기준선과 배치

```bash
make graduation-s1-prepare
make graduation-s1-spread
make graduation-s1-verify
make graduation-s1-baseline
```

기준선만 측정할 경우 `graduation-s1-cleanup`으로 마친다. 경합·복구를 시험할 경우에는
준비된 환경에서 아래 두 경로 중 하나를 선택한다.

서비스는 CPU 연산을 수행하고 요청 Job은 workload control plane에서 ClusterIP Service에
직접 접근한다. 요청 VM·목적지 worker와 서비스 worker의 compute 배치를 구분한다.
`spread`는 같은 compute에 모인 worker 중 이번 준비에서 생성한 일반 Pod·연결 볼륨 없는
worker만 이동하며, 기존 VM이나 장애 후 서비스 Pod 이동을 대신하지 않는다.

기준선 `complete`는 요청·CPU 카운터·배치·이미지·인프라 snapshot의 측정 품질 판정이다.
부하 생성기는 느린 요청에 맞춰 목표 요청량을 낮추지 않고 동시 요청 상한 초과를 실패로 남긴다.
이 단계의 통과 자체가 CPU 경합이나 복구 효과를 입증하지 않는다.

<a id="s1-contention"></a>

## S1 지정 목적지 재배치

```bash
make graduation-s1-contention
make graduation-s1-contention-cleanup
make graduation-s1-cleanup
```

별도 VM으로 같은 compute에 CPU 경쟁을 만들고 미리 정한 다른 compute의 worker로 Pod를 옮긴다.
인간 운영자의 인지·반응 시간을 측정하는 비교군은 아니다. 같은 요청 부하에서 정상·경합·회복을
비교하고, 회복 관측이 끝날 때까지 경쟁 VM의 부하가 유지됐는지 확인한다.

중단 시 `make graduation-s1-contention-status`의 실행·VM·Job 식별자를 확인한다.
동일 환경에서 contention cleanup으로 경쟁 VM·flavor·Job을 먼저 정리하고,
S1 cleanup으로 namespace와 원래 worker 상태를 복원한다. 한쪽 정리 실패도 기록한다.

<a id="s1-auto"></a>

## S1 자동 판단·재배치

```bash
make graduation-s1-auto
make graduation-s1-auto-cleanup
make graduation-s1-cleanup
```

서비스 지연·오류와 compute CPU·PSI를 함께 보고 연속 관측으로 경합을 판단한다.
요청·카운터 누락, throttling, 메모리·I/O 경합이나 목적지 자원·배치 제약은 조치 보류 근거다.
Pod–Node–Nova 관계와 자료 신선도를 재확인한 뒤 UID·resourceVersion 조건으로 한 번만
재배치하고 cooldown을 기록한다. 회복은 연속 안정 구간과 전체 부하의 마지막 구간을 모두
확인하며, 시간 상한 내 안정화하지 못하면 추가 이동이나 임계값 완화 없이 `needs_review`다.

중단 시 `make graduation-s1-auto-status`로 기록을 확인한 뒤 동일 실행의 cleanup을 사용한다.
Job이 남은 상태에서 새 측정을 시작하지 않는다. worker 복원이 실패하면 정리 실패 기록을
보존하고 수렴 후 다시 cleanup한다. [초기 S1 기록](s1-validation-2026-09-26.md)은 당시 조건으로 보존한다.

<a id="foundation"></a>

## S2·S3 기반 준비

S1 등 진행 중인 실험을 정리한 뒤 다음을 실행한다. foundation은 네트워크·스토리지 서비스를
재배포하므로 측정 도중 적용하지 않는다.

```bash
make graduation-foundation
make graduation-csi
```

Neutron QoS와 controller 파일 기반 Cinder LVM을 추가하고 Cinder CSI를 배포한다.
기존 디스크를 초기화하지 않으며 기반 저장소는 실험 cleanup 후에도 유지한다.
단일 controller 저장소여서 worker 장애에는 독립적이지만 스토리지 HA를 제공하지 않는다.
제어 명령은 기존 관리자 자격증명·SSH를, CSI는 제한된 CAPO application credential을 사용한다.
운영용 최소 권한 제어기를 별도 배포한 구성은 아니다.

<a id="s2"></a>

## S2 공유 출구와 QoS

```bash
make graduation-s2
make graduation-s2-cleanup
```

전용 probe·sink와 제한된 veth 출구에서 API 응답과 업로드가 같은 병목을 통과하는지
카운터·요청 원본으로 확인한다. 기존 관리 인터페이스의 속도를 바꾸지 않는다.
목적지에 기존 QoS나 중요한 일반 Pod가 있으면 사용하지 않는다. QoS·OVS 적용을 확인한
뒤 업로드를 분리하며, 고정 제한과 동적 단계 정책을 API 지연·업로드 진행으로 함께 비교한다.

업로드는 체크섬과 수신 측 영속 체크포인트로 재개·중복 집계를 검증한다. 설정 대역폭을
실효 처리량이나 전체 인프라 용량으로 해석하지 않는다. 악화 시 제한된 단계만 낮추고
무한 재시도하지 않는다. 정리는 namespace·전용 정책·추가 보안 그룹·Floating IP·출구를
제거하고 기존 무정책 상태와 worker 상태를 복원한다.

<a id="s3"></a>

## S3 DB·볼륨 복구

```bash
make graduation-s3
make graduation-s3-cleanup
```

PostgreSQL의 커밋 완료 데이터와 PVC/PV/Cinder 관계를 보존하고 Node 제어 통신·DB 접근
장애를 주입한다. 통신 두절만으로 기존 DB가 멈췄다고 가정하지 않는다. Nova SHUTOFF,
전환 작업 없음, power state와 libvirt 종료 상태를 확인한 뒤에만 out-of-service를 적용한다.

시험 중 MHC remediation 예외를 설정하고 controller-manager의 시간 초과 강제 분리를
비활성화한다. 원래 정책을 기록하고 시험 자원 제거 후 복원한다.
Pod 강제 삭제·Cinder 강제 detach·finalizer 제거를 사용하지 않는다. 동일 볼륨의 목적지 단독
연결, 기존 커밋 레코드 전체, 새 트랜잭션과 안정 요청을 검증한다. 불명확한 진행 중
트랜잭션까지 보존했다고 주장하지 않는다.

cleanup은 DB/PVC·볼륨 제거 확인 후 기존 VM을 다시 시작하고, 네트워크 규칙·taint·MHC 예외·
controller 설정·worker 상태를 복원한다. fencing이나 소유권 확인 실패 시 후속 변경을 강행하지 않는다.
S2·S3 중단 뒤에는 각 cleanup을 먼저 수행하고 기록을 새 실행으로 덮어쓰지 않는다.
[통합 검증](recovery-validation-2026-10-02.md)과 최종 평가의 사양·표본을 구분한다.

<a id="s4"></a>

## S4 VM 중단·서비스와 용량 복원

공통 환경 준비 후 `make graduation-s4-run`으로 준비→주입→관측→분석→정리를 실행한다.
`graduation-s4-run` 후에는 환경이 유지되며, 별도 `graduation-env-down`이 그 환경 실행이
기동한 호스트만 종료한다. 환경 준비·실험·종료를 묶으려면 공통 환경 준비부터의 명령 대신
`make graduation-s4-e2e`를 사용한다.

장애 없이 준비만 확인하려면 `graduation-s4-prepare` → `graduation-s4-verify` →
`graduation-s4-status` → `graduation-s4-cleanup` 순서로 실행한다.
worker 전용 MHC·영구 볼륨 없는 서비스·대상 관계·HTTP 기준선과 운영 시간 여유를 확인하고,
실험 중 fixed 모드와 WorkerControl 잠금으로 CA·수동 변경을 제어한다.

서비스 안정화와 새 worker의 합류·실행 가능성은 별도 완료 조건이다. stop 요청과
SHUTOFF 확인도 다른 사건이다. HTTP는 Kubernetes API Service proxy 경로이므로 일반
Ingress 중단시간으로 해석하지 않는다. 정상 응답 한 번이나 Node Ready만으로 완료하지 않는다.

```bash
make graduation-s4-workflow-status
make graduation-s4-run-status
make graduation-s4-status
# 기존 실행·대상·주입 결과를 확인한 뒤 재개
make graduation-s4-resume
# 보존한 원본은 호스트가 정지되어 있어도 재분석 가능
EVIDENCE_DIR=/absolute/path/to/graduation-s4-experiment make graduation-s4-analyze
```

재개는 기존 기록을 대조하며 이미 주입한 장애에 stop을 다시 보내지 않는다. stop 결과가
불명확하면 중단한다. 관측 공백은 `incomplete`/`completed_with_gap`으로 보존하며 무중단
관측으로 바꾸지 않는다. 정리도 UID·소유권을 확인하고 원래 worker 상태를 복원한다.

[초기 S4 검증](s4-validation-2026-09-26.md), [중간보고서 재측정](interim-report/s4-rerun-2026-09-27.md),
[최종 평가](final-evaluation-results-2026-10-03.md)의 코드·사양·조건이 다르므로 같은 반복 집합으로 합산하지 않는다.

## 증거와 동작 근거

각 실행은 `artifacts/<환경 이름>/` 아래 실행별 디렉터리에 요청 원본·상태 snapshot·식별자·
판정·정리 상태를 보존한다. 실패한 측정을 새 실행으로 숨기지 않고 원본과 코드 해시를 함께 남긴다.
S4 분석은 원본 SHA-256, 요약·요청·인프라 시간선·이벤트·보고서 표를 생성하며 원본을 수정하지 않는다.
GCS publish가 모든 졸업작품 원본을 반출한다고 가정하지 않는다. [관측 가이드](../../observability/README.md)를 따른다.

공식 동작 근거: [Kolla Cinder LVM](https://docs.openstack.org/kolla-ansible/2025.2/reference/storage/cinder-guide.html),
[Neutron QoS](https://docs.openstack.org/kolla-ansible/2025.2/reference/networking/neutron.html),
[CSI 출처](../../kubernetes/graduation-s3/csi/SOURCE.md),
[비정상 노드 종료](https://kubernetes.io/docs/concepts/cluster-administration/node-shutdown/),
[CAPI remediation 예외](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking.html).
