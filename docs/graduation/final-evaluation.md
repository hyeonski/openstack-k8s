# 최종 반복·비교 및 실패 경로 평가 계약

작성: 2026-10-02. 이 문서는 실행 계약이며, 실행 성공이나 반복 신뢰도를 선언하지 않는다. 결과는 실행별 원본과 독립 검증 파일로 확인한다.

## 고정 조건

설정은 `config/graduation-evaluation.json`, 실행 코드는 `scripts/graduation_evaluation.py`와 `scripts/graduation_evaluation_case.py`에 있다. `freeze`는 코드·매니페스트·공개 환경 설정의 SHA-256과 사본, 비공개 로컬 override의 해시, 예정된 34개 실행을 보존한다. 실행 전후 해시가 달라지면 같은 cohort를 계속하지 않는다. 정책이나 환경을 수정한 경우 이전 시도를 남기고 별도 cohort를 만든다.

- GCP: controller `e2-standard-4`, compute01 `n2-standard-8`, compute02 `n2-standard-4`.
- workload control plane과 worker: 각각 2 vCPU, 2 GiB, 20 GB. Kubernetes v1.35.7.
- control plane과 복구 목적지: compute01. 장애 대상 서비스·DB의 소스: compute02.
- 각 실행 시작과 종료: worker `auto` 1대. 실험 중에는 `fixed` 2대.
- 두 worker가 같은 compute에 배치되면 이번 실행 준비에서 생성된 일반 Pod·연결 볼륨 없는 worker만 측정 전에 live block migration한다. 기존 VM과 control plane은 이동하지 않는다.
- 런타임 이미지 ID를 원본에 보존하고 실행 간 일치 여부를 검사한다.
- 관측 창, 부하, CPU/PSI·지연 임계값은 기존 복구 계약을 유지한다. 반복 결과에 맞춰 임계값을 바꾸지 않는다.

## 예정 비교

| 대상 | 횟수 | 조건과 판정 |
|---|---:|---|
| S1 자동 / 무조치 | 각 5회 | 5 RPS, 요청당 연산 100,000회, 1,080초. 두 구간의 동일한 자동 진단 후 조치 유무만 달리한다. 무조치의 `control_valid`는 비교 자료가 유효하다는 뜻이며 복구 성공이 아니다. |
| S2 고정 / 동적 QoS | 5회 안에서 두 정책 비교 | API 2 RPS, 256 KiB 응답, 전용 출구 20 Mbit/s, burst 250 kbit. 고정 10 Mbit/s와 동적 6/10/14/18 Mbit/s를 비교한다. 실행별로 fixed-first / dynamic-first 순서를 교대한다. |
| S3 자동 / 단계별 런북 | 각 5회 | 동일한 1,000개 커밋 데이터와 장애 조건. 런북군은 fencing과 복구를 별도 CLI 단계로 호출한다. 사람의 인지·반응 시간은 측정하지 않으며 인간 운영자 대비 시간 단축을 주장하지 않는다. |
| S4 정상 전체 경로 | 5회 | 같은 환경에서도 이전 fixture의 정리 완료, 새 준비 ID·새 MHC UID를 확인한 후 별도 장애를 허용한다. 서비스와 worker 용량을 각각 판정한다. |

시험 도구의 실환경 검증을 위해 S4 정상 1회 → S4 중단·재개 → S1/S2/S3 거절 시험을 먼저 실행한다. S4 정상 첫 실행도 예정된 5회에 포함하며, 거절·중단 시험은 정상 성공률에 섞지 않는다. 이어서 S1과 S3는 회차마다 조건 순서를 교대한다. S2에서 고정 제한은 2개 구간, 동적 정책은 탐색과 마지막 안정 구간 2개를 별도로 기록한다. 같은 실행의 구간을 독립 반복 횟수로 세지 않는다.

S1의 회복 판정에 선택된 구간은 조치 시각에 따라 달라질 수 있다. 자동/무조치의 고정 시점 비교에는 전체 1,080초 부하의 마지막 60초를 별도로 재계산한다. 기준선 대비 p95 비율, 실패 수와 표본 수를 함께 제시한다. 자동 실행에는 진단→안정화 시간도 제시한다. S3의 주입 의도→DB Ready는 CLI·폴링이 포함된 관측 시간이며 연속 클라이언트 기반의 정밀 RTO가 아니다. S4는 Kubernetes API Service proxy 경로이며 일반 ingress의 중단시간이 아니다.

S2 집계 CSV의 `fixed_p95_ms`와 `dynamic_p95_ms`는 각 조건의 두 안정 구간 p95를 평균한 값이다. 합친 요청 전체의 p95로 해석하지 않는다. 업로드 byte 비교도 동일한 60초 구간별 수신량의 평균을 사용하며, 각 원본 구간의 개별 값도 보존한다.

S1 수동 대응은 실제 인간 운영자가 참여하지 않아 이번 반복에서 제외한다. S3 런북 비교 역시 자동 실행과 명시적 명령 단계의 차이를 다루며, 인간의 수동 대응 결과로 바꾸어 표현하지 않는다.

## 실제 실패·중단 검증

각 1회씩 별도로 수행하며 정상 복구 성공률의 분모와 구분한다.

1. S1: 목적지 worker에 실행 소유의 임시 NoSchedule taint를 적용한다. 목적지 없음 판정, Deployment·Pod 보존, 재배치 0회와 taint 제거를 확인한다.
2. S2: 실제 Neutron QoS 경로에 잘못된 제한값을 요청한다. 오류가 상위 실행까지 전달되고 업로드가 이동하지 않으며 기존 포트 정책과 원래 규칙이 보존되는지 확인한다.
3. S3: 통신 장애를 주입했지만 VM이 ACTIVE인 상태에서 실제 out-of-service 진입을 시도한다. 종료 확인 보호가 조치를 거절하고 기존 Pod·볼륨 연결이 유지되는지 확인한다.
4. S4: VM 정지 확인과 첫 관측 기록 후 실행 프로세스를 SIGKILL한다. 같은 실행 ID·대상·stop 의도로 재개한다. 관측 공백은 `incomplete` / `completed_with_gap`으로 남기고 새 장애를 주입하지 않는다.

## 실행과 보존

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-evaluation-freeze
# 출력된 절대 경로를 사용한다.
make graduation-evaluation-run CAMPAIGN=/absolute/path/to/campaign
make graduation-evaluation-status CAMPAIGN=/absolute/path/to/campaign
make graduation-evaluation-verify CAMPAIGN=/absolute/path/to/campaign
```

`campaign.json`은 예정된 시도와 측정 실패·보류를 모두 보존한다. 측정에 실패한 시도를 조용히 재시도해 성공만 남기지 않는다. 준비 중 중단은 실제 상태를 확인하고 정리한 후 다음 cohort 또는 명시적으로 검토한 실행으로 이어간다. 이미 시작된 장애를 신규 실행으로 덮어쓰지 않는다.

각 실행은 별도 로그, 실제 배치, 원본 run/summary, 정리 검증과 정리 완료 시점 원본 파일 SHA-256을 남긴다. 중단 시험은 새 실행 ID·생성 시각·주입 단계·첫 관측 파일을 모두 확인하므로 이전 시험 기록으로 현재 프로세스를 중단하지 않는다. 호스트의 자동 종료까지 2시간 이상 남았는지 확인하며, 부족하면 모든 시험 자원이 정리된 시점에 소유 호스트를 종료·재기동한다. 전체 완료 뒤에도 이번 환경 실행이 기동한 호스트만 종료한다.

## 자체 재검증

`graduation_evaluation_verify.py`는 실행 제어기의 집계 함수를 호출하지 않고 요청 원본에서 지연과 개수를 다시 계산한다. S2의 수신 byte 차이·출구 카운터·청크 체크섬, S3의 전체 커밋 레코드·단독 볼륨 연결·fencing 순서, S4의 요청 실패 수와 정리 상태도 대조한다. 거절 시험도 조치 전후 실제 Pod·Node·Neutron 포트/규칙·Cinder 연결 원본과 대조한다. S3는 controller-manager 설정 파일의 바이트 단위 복원과 remediation 예외 제거를 확인한다. 결과는 `independent-verification.json`과 `results.csv`에 보존한다.

중앙값·최솟값·최댓값과 각 회차의 결과를 제시한다. 5회 통과를 운영 환경에서의 100% 신뢰성으로 해석하지 않는다. 이전 4 vCPU 구성과 현재 구성을 같은 반복 집합에 합산하지 않는다.
