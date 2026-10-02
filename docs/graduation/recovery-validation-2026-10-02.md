# 3·4·5번 통합 검증 기록 — 2026-10-02

상태: 3·4·5번의 최종 구성별 실환경 복구 검증 통과. 사전 실패 실행과 최종 통과 실행은 아래에서 구분한다. 각 최종 구성은 1회 검증이며 반복 성공률을 확정한 결과는 아니다.

| 작업 | 최종 검증 | 핵심 결과 |
|---|---|---|
| 3번 S1 자동 진단·재배치 | 통과 — compute01 8 vCPU 구성 | 5,400/5,400 성공, p95 74.569→165.796→72.320ms, 연속 3개 안정 구간 및 종료 구간 통과 |
| 4번 S2 분리·QoS | 통과 — 두 compute 각각 4 vCPU 구성 | 1,440/1,440 성공, 무제어 약 453~477ms에서 최종 약 107~111ms, 730MiB 업로드 무결성 확인 |
| 5번 S3 fencing·볼륨 복구 | 통과 — 두 compute 각각 4 vCPU 구성 | 같은 Cinder 볼륨에서 커밋 1,000개 보존, 새 쓰기·조회 및 60회 연속 DB 요청 성공 |

## 환경과 범위

- `cloud-gcp-amd64-greenfield`, Kubernetes v1.35.7, Kolla 2025.2, Neutron OVS.
- 3번: S1 증거 기반 자동 재배치. 4번: S2 업로드 분리·QoS. 5번: S3 Cinder·CSI·PostgreSQL fencing 복구.
- 서비스 기준과 실행 계약은 [복구 자동화](recovery-automation.md)에 기록한다.

## 기반 서비스 확인

controller의 전용 20 GiB 파일과 `graduation-cinder` VG를 만들고, 부팅 시 loop 장치와 VG를 복원하는 systemd unit을 활성화했다. Cinder scheduler·volume 서비스가 모두 `enabled/up`이며 API·scheduler·volume 컨테이너가 healthy인 것을 확인했다.

Neutron QoS extension 및 `bandwidth_limit` 규칙 지원을 확인했다. controller와 두 compute의 OVS agent가 모두 살아 있다. Cinder CSI v1.35.0 controller는 5/5, 기존 두 Node의 node plugin은 각각 3/3 Ready였으며, 이후 worker 증설 시 세 번째 node plugin도 자동 배치됐다.

첫 Kolla 실행은 root만 읽을 수 있는 globals.d 파일을 배포 사용자가 건너뛰어 기능이 활성화되지 않았다. 비밀 값이 없는 기능 설정 파일을 읽을 수 있게 수정하고 다시 배포했다. 배포 종료 코드 외에 Cinder 상태와 QoS capability를 검사하는 후속 검증도 추가했다.

근거: `artifacts/cloud-gcp-amd64-greenfield/graduation-foundation-20261002/verification.json`, `deploy.log`.

## 사전 시험과 수정

### S1 첫 자동 실행

`s1c-1803d429517a`는 연속 두 CPU 경합 구간을 진단하고, 다른 compute의 적격 worker에 한 번 재배치했다. 경합 VM과 소스 CPU 압력은 최종 측정까지 유지됐다.

| 지표 | 기준선 | 경합 | 초기 회복 구간 |
|---|---:|---:|---:|
| p95(ms) | 76.359 | 171.657 | 92.374 |
| 해당 60초 요청 성공 | 300/300 | 300/300 | 300/300 |

첫 회복 구간은 기준선의 약 1.21배로 1.2배 기준을 넘었다. 다음 구간 p95는 87.486ms였다. 첫 실행은 `needs_review`로 보존했다. 이후 판정 임계값은 그대로 두고 고정된 360초 관측 기간의 마지막 연속 두 구간을 평가하도록 정책을 수정했다. 이 정책의 별도 실행 결과는 아래 추가 시험 절에 기록했다.

근거: `graduation-s1-contention-20261002T063925Z-22ded6cc`의 `summary.json`, `decisions.jsonl`, `http.jsonl`.

### S2 준비 실패와 burst 사전 보정

첫 준비에서는 OSC의 보안 그룹 추가 동작이 기존 목록에 더하는 방식임을 확인했다. 기존 그룹을 반복 전달하면 중복으로 거절된다. 새 그룹만 추가하고 보존 여부를 읽어 확인하도록 수정했다. 실제 붙지 않은 그룹의 정리 경로도 검증·수정했다.

두 번째 실행은 준비·기준선·경합 진단·분리에 성공했다. QoS 해제 명령은 설치 버전이 지원하는 `port unset --qos-policy`로 수정했다.

| 구간 | p95(ms) | API 성공 | 60초 업로드 증가 | 공통 출구 평균 |
|---|---:|---:|---:|---:|
| 기준선 | 101.284 | 120/120 | 0 | 4.43Mbps |
| 무제어 1 | 482.177 | 120/120 | 105MiB | 19.86Mbps |
| 무제어 2 | 466.937 | 120/120 | 106MiB | 19.89Mbps |
| 10Mbps / burst 1000kbit 1 | 213.957 | 120/120 | 48MiB | 11.42Mbps |
| 10Mbps / burst 1000kbit 2 | 213.438 | 120/120 | 47MiB | 11.30Mbps |
| 보정: burst 100kbit | 103.628 | 120/120 | 5MiB | 5.12Mbps |
| 보정: burst 250kbit | 105.046 | 120/120 | 12MiB | 6.09Mbps |

평균 송신량만 줄여도 tail latency가 목표를 만족하는 것은 아니었다. 고정·자동 QoS 양쪽의 burst를 250kbit로 고정하여 아래 최종 비교를 수행했다. 명목 제한값을 실제 업로드 속도로 간주하지 않으며, 수신된 bytes와 파일 무결성을 별도로 평가한다. 위 보정 값은 실패 실행에 이어 수행한 사전 측정이며 최종 통과 결과가 아니다.

근거: `graduation-s2-20261002T073426Z-475f8f36`의 구간별 JSON 및 `run.json`.

## S2 최종 검증

실행 `s2-540f4f0a3b69`, 근거 `graduation-s2-20261002T075940Z-7f01af23`. burst 250kbit를 고정한 새 실행에서 모든 완료 조건을 통과했다.

| 구간 | p95(ms) | API 성공 | 60초 업로드 증가 |
|---|---:|---:|---:|
| 기준선 | 101.493 | 120/120 | 0 |
| 무제어 1 / 2 | 476.791 / 452.786 | 240/240 | 106 / 105MiB |
| 분리 + 고정 10Mbps 1 / 2 | 104.613 / 104.994 | 240/240 | 11 / 12MiB |
| 분리만 적용, QoS 없음 | 447.940 | 120/120 | 105MiB |
| 동적 6Mbps | 104.643 | 120/120 | 10MiB |
| 동적 10Mbps | 105.096 | 120/120 | 11MiB |
| 동적 14Mbps | 114.183 | 120/120 | 16MiB |
| 동적 18Mbps | 114.181 | 120/120 | 22MiB |
| 18Mbps 안정화 1 / 2 | 110.588 / 107.462 | 240/240 | 23 / 23MiB |

12개 구간의 총 1,440개 요청이 모두 성공했다. 요청별 원본으로 p95를 독립 재계산하고 각 구간의 120개 인덱스, 업로드 byte 차이, qdisc byte 차이/실측 시간의 전송률을 대조해 요약과 일치함을 확인했다. 수신된 730개 청크(730MiB)는 중복 ID 없이 파일 크기·SHA-256이 manifest와 모두 일치했다. 업로드 체크포인트는 이동 후에도 증가했고 API Pod UID는 바뀌지 않았다.

공통 출구가 무제어 상태에서 약 19.9Mbps로 포화되므로 업로드 Pod 분리만으로 회복되지 않는다. 이번 부하에서는 고정 제한과 동적 제한 모두 API 목표(기준선 1.3배 이내)를 만족했고, 동적 정책의 최종 구간은 고정 구간보다 수신 완료량이 약 두 배였다. 한 실행의 비교 결과이며 모든 부하에서 동적 정책이 우월하다는 주장은 하지 않는다. 18Mbps는 정책 상한이고 실제 수신 업로드 처리량은 약 3.2Mbps였다. 작은 burst와 TCP 재전송 영향이 있으므로 두 값을 구분한다.

근거: `summary.json`, 구간별 JSON, `upload-integrity.json`, `independent-verification.json`. 소스 스냅샷과 SHA-256은 `source/`, `run.json`에 저장했다. 최종 실행 중 S3 관련 환경 기동 보호를 추가했으므로 저장소 전체가 실행 시작 시점과 동일하다고 주장하지 않는다. S2 측정·제어·부하 코드는 최종 실행 동안 변경하지 않았다.

S2 정리는 `cleanup_errors: []`, `phase: cleaned`로 완료됐다. namespace와 임시 worker를 제거하고, 기존 포트의 `qos_policy_id: null`, worker `auto` 1대로 복원했다. 전용 정책·Floating IP·보안 그룹·외부 출구 제거도 정리 절차에서 성공했다.

## S3 최종 검증

실행 `s3-fd182b65e830`, 근거 `graduation-s3-20261002T082909Z-629463ee`. Cinder의 실제 생성·연결부터 PostgreSQL 복구까지 첫 실환경 실행에서 모든 완료 조건을 통과했다.

| 사건·검사 | 관측 결과 |
|---|---|
| 기준선 | DB 요청 30/30 성공, 커밋 완료 레코드 1,000개 |
| DB 내구성 | fsync / synchronous_commit / full_page_writes 모두 on, PGDATA·WAL은 PVC 내부 |
| 통신 장애 | 기존 컨테이너 `CONTAINER_RUNNING`, Node 이상 및 DB 요청 15회 연속 실패 |
| 종료 미확인 보호 | 실제 Nova ACTIVE 응답을 거절, 기존 Pod UID 유지 |
| 실제 fencing | Nova SHUTOFF, task_state null, power_state 4, libvirt shut off |
| 볼륨 | `d98a43a1-5269-4d28-b6e9-cac7b33f43bf` 유지, 이전 VM 단독 연결에서 대상 VM 단독 연결로 변경 |
| 데이터 | 1,000개 ID·내용 전부 일치, 개수·집계 MD5도 일치 |
| 새 트랜잭션 | id=1001 커밋 후 조회 성공 |
| 안정화 | DB 요청 60/60 연속 성공, 이전 VM은 계속 종료 상태 |
| 이미지·배치 | DB 이미지 ID 유지, 새 Pod UID와 다른 worker 배치 |

시각은 UTC이며 KST는 9시간을 더한다.

| 사건 | 시각 |
|---|---|
| 장애 주입 의도 기록 | 08:35:43.335 |
| VM 종료 확인 완료 | 08:37:17.347 |
| out-of-service 조치 의도 기록 | 08:37:24.482 |
| 새 DB Ready 확인 | 08:37:59.017 |

주입 의도에서 Ready 확인까지 135.682초, 종료 확인에서 Ready 확인까지 41.670초, out-of-service 의도에서 Ready 확인까지 34.535초였다. CLI·원격 호출과 폴링 간격이 포함된 관측 시간이며 실제 장애 시작/회복 순간의 정밀 측정이나 모든 시간대의 연속 클라이언트 RTO는 아니다. 기준선·장애·안정화의 DB 요청 원본은 각각 보존했다.

기존 VM은 `02bc389b-573a-4c9c-8772-9ef8fcf1e2f4`, 대상 VM은 `96668a05-a5ce-4529-aaca-327bcde27e4e`였다. `recovery-timeline.json`에 Pod·VolumeAttachment 변경을 남겼다. Cinder volume ID와 양쪽 연결 대상을 독립 대조하고, 외부에 저장한 레코드 전체와 집계 해시를 재계산했다. fencing 확인 기록이 out-of-service 조치보다 앞서는 것도 확인했다.

실험에서는 controller-manager의 시간 초과 강제 분리를 비활성화했고 소스 Machine의 자동 remediation을 제외했다. 기본 설정과 동일한 동작이라고 해석하지 않는다. 미완료 트랜잭션은 주입하지 않았으며, 보존 주장은 성공 응답을 받은 커밋에 한정한다. controller 한 대의 Cinder LVM이므로 스토리지 노드 자체 장애 복구나 저장소 HA를 검증한 결과도 아니다.

근거: `summary.json`, `committed-records-before.json`, `committed-records-after.json`, `fence.json`, `fence-negative-check.json`, `volume-before.json`, `volume-after.json`, `recovery-timeline.json`, `independent-verification.json`. 소스 스냅샷 18개의 SHA-256도 모두 일치했다.

첫 S3 정리에서는 Node Ready 이후 MachineDeployment 가용 상태가 늦게 반영되어 worker 축소가 거절됐다. DB/PVC 삭제·소스 VM 재시작·controller 정책 복원은 완료된 상태였으며, 소유권과 모드를 재확인하면서 최대 600초 동안 MD 안정화를 기다리도록 공통 정리를 보완했다. 해당 회귀 테스트를 추가하고 같은 실행의 정리를 재개했다. 이 보완은 S3 복구 측정이 끝난 뒤의 정리 코드 변경이다.

S3 정리는 08:51:06 UTC에 `phase: cleaned`로 완료됐다. DB/PVC와 Cinder 볼륨 제거 후 소스 VM을 재시작했고, 전용 차단 규칙·격리 taint·remediation 제외·controller 정책을 복원했다. 최종 worker는 `auto` 1대다. 정리 재시도에 사용한 소스와 해시는 `cleanup-source/`에 별도 보존했다.

## S1 고정 시점 판정의 추가 시험과 보완

`s1c-1defffa82839` (`graduation-s1-contention-20261002T085639Z-c85f515c`)에서는 5,400/5,400 요청 성공, p95 78.161→174.285→95.732ms였다. 자동 진단 2회·다른 compute로 한 번 이동·구성 보존·최종 시점까지 소스 경합 유지 조건은 통과했다. 그러나 고정된 두 회복 구간은 91.690/95.732ms로 두 번째가 93.793ms 상한을 넘어 `needs_review`였다. 목적지의 회복 관측 중 CPU는 30.706%, CPU PSI는 1.373%였고, 두 compute는 같은 n2-standard-4 / Intel Cascade Lake였다. 특정 하드웨어 차이가 원인이라고 단정하지 않는다. 추가 분석에서 마지막 300개 요청의 p95도 99.046ms로 높았다. 새 정책의 종료 구간 검사도 필요한 근거이며, 앞선 실행을 성공으로 재분류하지 않는다.

고정된 두 시점만 검사하는 대신 제어기가 제한 시간 안에서 안정 상태를 연속 확인하도록 보완했다. p95 1.2배 기준은 유지하며, 60초 구간 3회 연속 통과를 요구하고 실패 구간은 연속 횟수를 초기화한다. 최대 8개 구간까지만 기다린다. 전체 부하의 마지막 구간에도 회복 기준을 요구하고 전체 요청 성공도 검사한다. 이 변경은 앞선 실패 결과를 재분류하는 데 사용하지 않았으며, 아래 별도 실행으로 검증했다. 연속 횟수 초기화와 관측 상한의 회귀 테스트를 추가했다.

### 연속 안정화 정책의 4 vCPU 목적지 시험

`s1c-dc2abdbb5971` (`graduation-s1-contention-20261002T092841Z-0b7cbe3f`)도 5,400/5,400 요청이 성공했다. 기준선 p95는 79.439ms, 경합 구간은 170.199ms였다. 이동 후 8개 구간의 p95는 90.675 / 92.983 / 99.906 / 96.516 / 91.718 / 98.220 / 94.536 / 92.291ms였고, 상한 95.327ms를 넘을 때 연속 횟수가 실제로 초기화됐다. 최대 연속 성공은 2회로 관측 상한에서 `needs_review`였다. 마지막 60초 구간은 299개 요청, p95 92.744ms로 통과했다. 마지막 구간이나 평균 개선만으로 전체를 성공 처리하지 않았음을 확인했다.

요청 원본 재계산과 코드 스냅샷 검증은 `independent-verification.json`, 기존·신규 worker의 동일한 2 vCPU / Cascadelake-Server 설정 확인은 `cpu-model-comparison.json`에 남겼다. 이 결과는 자동 진단·재배치와 악화 시 연속 횟수 초기화·관측 상한 보류의 실환경 검증이며, 안정화 성공 결과는 아니다.

다음 대조 구성에서는 control plane과 목적지 worker가 함께 있는 compute01만 n2-standard-4에서 n2-standard-8로 변경했다. compute02, 경쟁 VM, 서비스 5 RPS·100,000회 연산, 지연 비율과 안정화 정책은 유지한다. 증설이 tail latency 여유를 개선하는지 확인하는 별도 환경 조건이며, 4 vCPU 결과와 합산해 반복 성공으로 주장하지 않는다.

증설 후 환경은 `env-884d968bcb18`이다. compute01의 인스턴스 ID와 Intel Cascade Lake 플랫폼, 36,000초 자동 종료 제한을 유지하면서 8 vCPU·32GiB로 변경했다. 선언 검증과 실제 클라우드 비교 계획은 통과(`No changes`)했다. 호스트 전체 재기동 후 Cinder 서비스 enabled/up, 전용 loop/VG 자동 복원, CSI controller·node 준비 상태도 확인했다. 근거는 `graduation-capacity-20261002/`에 보존했다. 재기동과 worker 재생성이 동반되므로, 증설 후 결과를 CPU 증설만의 효과를 분리한 인과 실험으로 해석하지 않는다.

증설 뒤 준비된 두 worker가 모두 compute01에 놓여 최초 실행 진입 검사가 부하 주입 전에 거절했다. 새 `graduation-s1-spread` 준비 명령으로 이번 prepare에서 만든 일반 Pod·연결 볼륨이 없는 worker만 compute02로 live block migration했다. VM UUID와 Node UID를 유지했고, 이동 후 Nova ACTIVE·task_state null과 Node Ready를 확인했다. 이는 측정 전 배치 준비이며 자동 장애 대응의 Pod 재배치 횟수에 포함하지 않는다. 근거: `graduation-s1-placement-20261002T102332Z-76224e40/run.json`, `source/`. 기존 worker·일반 Pod·연결 볼륨·진행 중 작업을 보호하는 테스트를 추가했다.

## S1 최종 검증 — 8 vCPU 목적지

실행 `s1c-abc22ceb842f`, 근거 `graduation-s1-contention-20261002T102642Z-76d024bb`. 최종 자동 제어 정책과 8 vCPU 목적지 구성의 첫 부하 실행에서 모든 완료 조건을 통과했다. 5 RPS·100,000회 연산·1,080초로 요청 5,400개가 모두 성공했고 인덱스 누락·중복이 없었다.

| 측정 구간 | p95(ms) | 성공/전체 요청 |
|---|---:|---:|
| 기준선 | 74.569 | 300/300 |
| 경합 | 165.796 | 300/300 |
| 안정화 1 | 77.071 | 300/300 |
| 안정화 2 | 75.331 | 301/301 |
| 안정화 3 | 72.320 | 300/300 |
| 전체 부하의 마지막 60초 | 74.147 | 299/299 |

60초 경계와 요청 시각에 따라 299~301개 표본이 포함된다. 5,400개 전체 요청의 성공과 누락·중복 검사는 별도로 수행했다. 회복 상한은 기준선의 1.2배인 89.483ms로, 앞선 4 vCPU 실패 실행과 같은 비율이다.

두 번 연속 진단을 충족한 시각은 10:31:51.621 UTC, 다른 compute의 worker로 재배치를 확인한 시각은 10:32:25.167, 세 구간 안정화 확인은 10:36:01.485였다. 조치는 한 번만 수행했다. source worker는 `b66574ce-1e8d-46a4-8840-e11062e1809f`/compute02, target worker는 `19e09585-d931-4ff5-a03d-8b07c07f700b`/compute01이었다. 이미지 ID와 Deployment의 나머지 구성을 보존했다.

소스 CPU 사용률·CPU PSI는 경합 구간 99.844%·24.002%, 재배치 후 99.972%·9.456%, 부하 종료 후 99.979%·8.736%였다. 경쟁 VM의 ACTIVE와 원래 compute 배치도 최종 확인했다. 경합 제거로 자연 회복한 결과가 아니며 Pod CPU throttling 증가는 없었다. 목적지의 재배치 후 CPU 사용률·PSI는 12.962%·0.435%였다.

요청 원본으로 기준선·경합·온라인 안정 구간·최종 구간 p95를 각각 독립 재계산해 요약과 일치함을 확인했다. 소스 스냅샷 4개의 해시와 실행 중 저장소 파일도 일치했다. 근거는 `summary.json`, `http.jsonl`, `decisions.jsonl`, `run.json`, `independent-verification.json`, `source/`다. 실행 종료 코드는 0, `summary_state: passed`, `phase: completed`였으며 경쟁 VM·flavor·요청 Job 제거까지 완료됐다.

최종 통과는 증설한 구성에서의 1회 결과다. 목적지 하드웨어 변경과 재기동·worker 재생성을 동반했으므로, 이전 실패와 비교해 CPU 증설만의 효과나 장시간 반복 신뢰도를 확정하지 않는다. 현행 용량 결정과 원복 조건은 [ADR-0017](../adr/0017-increase-recovery-target-compute-capacity.md)에 기록했다.

## 코드와 기반 구성 검증

- 최종 `make lint`: 176개 테스트 및 셸 정적 검사 통과.
- `git diff --check`: 통과.
- OpenTofu 구성 검증 통과 및 실제 클라우드 비교 계획 `No changes` 확인.
- S2·S3 최종 원본, 무결성·연결 대상·fencing 순서, 저장된 코드 해시와 별도 정리 결과 확인.
- CSI 공식 배포 파일의 Apache 2.0 LICENSE와 출처를 보존했다. LICENSE 문서는 S3 실행 후 추가했으며 당시 측정 코드·manifest 스냅샷과 구분한다.

## 최종 정리

S1 준비 상태는 10:50:51 UTC에 `restored`가 됐다. 10:52:28 UTC의 별도 조회에서 S1 경쟁 VM·flavor와 세 시나리오의 namespace가 없고, S2·S3도 `cleaned`, worker는 `auto` 1대임을 확인했다. 근거는 S1 최종 실행의 `cleanup-verification.json`이다. S2 전용 QoS·Floating IP·보안 그룹·외부 출구와 S3 PVC·PV·Cinder 볼륨은 앞선 별도 정리 검사에서도 제거를 확인했다.

전체 실행 식별자와 최종 로컬 검사 로그는 `artifacts/cloud-gcp-amd64-greenfield/graduation-recovery-final-20261002/`에 모았다. 상세 요청·장애 원본은 위 각 실행 디렉터리에 보존하며 Git에는 코드를 비롯한 재실행 절차와 검증 보고서를 커밋한다.

환경은 10:58:28 UTC(19:58:28 KST)에 `stopped`가 됐다. 이후 별도 GCP 조회로 controller·compute01·compute02 세 인스턴스의 기존 ID와 `TERMINATED` 상태를 확인했다. API 터널도 종료했다. 근거는 위 최종 디렉터리의 `environment-stopped.json`, `hosts-stopped.json`이다. 기반 Cinder 파일·CSI 설치와 compute01의 8 vCPU 선언은 다음 실행을 위해 유지한다.
