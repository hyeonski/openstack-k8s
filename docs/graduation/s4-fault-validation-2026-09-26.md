# S4 단일 worker VM 중단 실험 검증 (2026-09-26)

이 문서는 S4의 첫 실환경 장애 주입 결과다. 공통 환경 준비와 S4 사전 조건은 별도 실행했다. **한 번의 성공 실험이므로 반복 성공률이나 일반 서비스 ingress 성능을 의미하지 않는다.** 모든 시각은 UTC다.

## 실행과 대상

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s4-prepare
make graduation-s4-run
make graduation-s4-cleanup
make graduation-env-down
```

- 환경 실행 ID: `env-ea29d76bad1d`; S4 실행 ID: `s4-e7a4fd084e56`.
- worker 목표 2대와 MHC `expectedMachines=2`, `currentHealthy=2`를 확인했다. Pod–Node–Machine–Nova 매핑과 HTTP 사전 검사 5/5, 전체 baseline snapshot의 조회 오류 없음, GCP 호스트 ID 및 자동 STOP 잔여 시간을 확인한 뒤 주입했다.
- 대상 HTTP Pod UID: `85e601fb-2d1a-431d-97fb-6b3c723a669e`; 대상 Machine UID: `0269c8f2-bedd-4600-9e19-50c82e2e6131`; 대상 Nova VM: `e205ace2-f83e-4d9f-891d-e69cdc753706`.
- Nova `server stop` 명령을 이 UUID에만 실행하고 `SHUTOFF`를 별도 조회로 확인했다. 다른 worker와 control plane VM은 중단 대상에서 제외했다.

## 관측 결과

| 사건 | UTC 시각 | 근거 |
|---|---|---|
| VM 중단 명령 직전 기록 | 02:56:54.884 | 내구 `stop-intent` 기록 |
| 첫 HTTP 실패 표본 | 02:57:04.989 | 외부 `kubectl` Service proxy 요청 로그 |
| 대상 VM `SHUTOFF` 확인 | 02:58:07.749 | Nova 개별 조회 원본 |
| 마지막 HTTP 실패 표본 | 02:58:15.193 | 요청별 원본 |
| 첫 정상 HTTP 응답 | 02:58:16.503 | 요청별 원본 |
| MHC의 기존 Machine 삭제 시작 | 02:59:45 | Machine deletionTimestamp와 `UnhealthyNode` 조건 |
| 목표 worker·신규 worker HTTP 검사 첫 충족 표본 | 03:01:31.320 | 2대 Ready, 기존 Machine/Node/Nova 제거, 새 VM ACTIVE, 새 worker 검사 Pod Ready |
| 안정화까지 충족한 최종 표본 | 03:02:14.447 | MHC 2/2, MachineDeployment 2/2, 신규 worker의 HTTP 검사 Pod Ready |

중단 명령 이후 수집한 HTTP 요청 **226회 중 29회가 실패**했고 197회가 성공했다. 첫 실패 표본에서 첫 정상 응답 표본까지 **71.515초**였다. 이는 요청 간격과 최대 5초 API 타임아웃을 포함한 *관측 구간*이며 실제 서비스 중단의 정확한 시작·종료 시각은 아니다. 초기 실패에는 API Service proxy의 응답 타임아웃과 `no endpoints available`이 모두 포함된다. Service proxy는 workload API 터널을 거치므로 일반 사용자 ingress의 지연/가용성으로 환산할 수 없다. HTTP 성공은 이후 30초 이상 연속으로 확인했다.

MHC는 Node `Ready=Unknown`이 2분 넘게 지속됐다는 이유로 원래 Machine을 삭제했다. 대체 Machine UID `98aa95c2-bd1b-4221-ad7c-5211d07a70f4`, 새 Nova VM `dc99ee16-7ab7-4a23-be18-6d453512fe14`가 생성됐다. 두 worker의 Machine·Node가 Ready, MHC 2/2, MachineDeployment 2/2/2, 새 Nova VM ACTIVE였다. 원래 Machine·Node·OpenStackMachine·Nova VM은 최종 목록에서 사라졌으며, 새 worker에 별도 검사 Pod를 실행해 클러스터 내부 HTTP 서비스를 읽었다. `SHUTOFF` 확인부터 목표 용량과 검사 Pod의 **첫 충족 표본까지 203.570초**, 안정화 확인까지 **246.697초**였다. HTTP 복구와 worker 용량 복구는 각각 독립 판정했다.

## 원본과 해석상 주의

- [실행 원본](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-experiment-20260926T025550Z-e022fb3e): `baseline.json`, `stopped-nova.json`, `http.jsonl`, `observations/*.json`, `result.json`, `run.json`.
- 실행 도중 초기 집계기가 `SHUTOFF` **확인 이후**의 HTTP 요청만 계산해 6회 실패로 표시했다. 전체 중단 명령 이후 구간을 재계산해 `result.json`과 `run.json`을 정정했으며, 이전 결과는 `result-original.json`에 보존했다. 정정 시각·이유도 `analysis_revision`에 남겼다.
- API 요청은 약 1초 간격으로 시작하도록 했지만 5초 타임아웃 때 다음 표본 간격이 늘었다. 관측 시작 시각 간 최대 공백은 약 6.114초다. 이 실험만으로 엄밀한 사용자 체감 중단 시간이나 통계적 성공률을 주장하지 않는다.
- 복구 동작은 Kubernetes의 Pod 재배치와 MHC·CAPI·CAPO의 Machine/VM 교체가 수행했다. 자체 S4 모듈은 정확한 대상 확인, 단일 장애 주입, 서비스와 용량의 별도 관측·판정 및 원본 보존을 담당했다.

## 정리 상태

S4 전용 MHC·HTTP 서비스·검사 Pod를 제거하고 원래 `auto` 모드·worker 1대로 복원했다. 환경 실행이 시작한 GCP controller와 compute 2대, 총 세 호스트만 중단했으며 2026-09-26 03:14:03 UTC 최종 조회에서 모두 `TERMINATED`였다.
