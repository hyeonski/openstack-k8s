# S1 서비스·부하·기준선 준비

S1의 첫 단계는 CPU 경쟁을 주입하기 전에 재현 가능한 서비스 요청과 정상 기준선을 만드는 것이다. 이 단계는 경쟁 VM 생성이나 Pod 자동 재배치를 포함하지 않는다.

## 실행 순서

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s1-prepare
make graduation-s1-verify
make graduation-s1-baseline RATE=5 ROUNDS=100000 WARMUP=60 MEASURE=300
make graduation-s1-cleanup
make graduation-env-down
```

`graduation-env-ensure`는 기존 테스트베드를 확인하고 필요한 호스트·게스트만 기동한다. S1 준비 단계는 기존 worker 제어 모드·대수를 기록하고, 실험 동안 `fixed`·worker 2대로 설정한다. 정리는 S1 namespace를 제거하고 원래 모드·대수로 복원한다. 환경 종료는 해당 환경 실행이 기동한 GCP 호스트만 중단한다.

## 서비스와 검사 위치

전용 namespace의 단일 복제본 Deployment가 `GET /work?rounds=N`에 고정 입력의 PBKDF2-SHA256 결과를 반환한다. `GET /healthz`는 가벼운 준비 검사다. `/work`는 10,000~1,000,000회만 허용한다. CPU request는 250m이고 CPU limit은 설정하지 않는다. 이미지 태그, 실제 이미지 ID, 코드 해시, Pod·Node·Machine·Nova 식별자를 실행 증거에 저장한다.

부하 생성 Job은 workload control-plane Node에서 실행하고 `http.graduation-s1.svc.cluster.local:8080`으로 직접 요청한다. 서비스 worker와 다른 Node에서 요청하므로 해당 worker의 Pod 수명에 의존하지 않는다. 요청의 지연은 부하 생성 Pod 안에서 측정한다. 이 경로는 Kubernetes API Service proxy나 일반 사용자 Ingress의 지연을 포함하지 않는다. Nova 관리자 조회로 서비스 VM, 요청 VM, 다른 worker VM의 compute 호스트를 실행 전후 확인한다. 다른 worker는 서비스와 다른 compute에 있어야 한다.

요청기는 정해진 초당 요청 수로 요청을 시작한다. 이전 요청이 늦어져도 예정된 요청량을 낮추지 않으며, 동시 요청 상한에 걸린 요청은 `inflight_limit` 실패로 남긴다. 요청별 UTC 시작 시각, 성공 여부, HTTP 상태, 지연, 오류를 JSONL 원본으로 저장한다. 워밍업 구간은 분석에서 제외한다.

## 산출물과 완료 기준

각 기준선 실행은 `artifacts/<environment>/graduation-s1-baseline-*`에 `run.json`, `job.json`, `probe-pod.json`, `http.jsonl`, `summary.json`, 앞뒤 인프라 snapshot, Nova compute 배치, compute 호스트 CPU·PSI 카운터와 Pod cgroup CPU 카운터를 남긴다. 요약에는 요청 수·누락 또는 중복·오류·성공률·초당 성공 요청·p50/p95/p99 지연·표본 시작 시각 공백·compute CPU 평균 사용률과 CPU pressure `some` 비율이 있다. 호스트 수치는 실행 전후 평균이므로 요청별 순간 피크를 나타내지는 않는다.

`complete`는 측정 요청이 모두 기록되고 오류가 없으며, 같은 Pod·Nova VM·compute 배치와 조회 가능한 인프라가 측정 전후 유지됐고 긴 요청 기록 공백이 없으며 요청 VM과 대체 worker가 서비스와 다른 compute에 있는 경우다. 이 판정은 정상 기준선의 **측정 품질**을 뜻한다. CPU 경합이 발생했다거나 S1 복구 효과를 입증하는 판정은 아니다. 부하 속도와 연산 횟수는 예비 기준선에서 조정하고, 이후 경합·재배치 비교에서는 동일하게 유지한다.
