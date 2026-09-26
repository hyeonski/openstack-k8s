# S4 실험 준비 자동화 검증 (2026-09-26)

이 기록은 공통 환경 준비와 S4 **사전 조건**의 실환경 검증이다. worker VM 장애 주입과 복구 시간 측정은 아직 수행하지 않았다.

재실행 진입점은 다음과 같다. `graduation-env-ensure`는 이미 정상인 호스트를 다시 시작하지 않고, `graduation-s4-prepare`는 장애를 주입하지 않는다.

```bash
export ENV_OVERRIDE_FILE="$PWD/config/environments/local.env"
make graduation-env-ensure
make graduation-s4-prepare
make graduation-s4-verify
make graduation-s4-cleanup
make graduation-env-down
```

## 공통 환경 준비

- 실환경 프로필: `ENV_OVERRIDE_FILE=config/environments/local.env`, `cloud-gcp-amd64-greenfield`.
- 환경 실행 ID: `env-8ce8680f68c7`. 시작 전 GCP controller 1대·compute 2대는 모두 `TERMINATED`였고, 준비 실행이 세 호스트를 기동했다. 기존 IaC나 클러스터는 재생성하지 않았다.
- 첫 복구 시 workload control-plane Nova VM이 다시 `SHUTOFF`로 남아 workload API 확인이 시간 초과됐다. 환경 기록의 호스트 소유권을 재조정하고 해당 CAPI 게스트만 재기동한 뒤 같은 실행 ID로 준비가 통과했다. 이를 반영해 게스트 기동 스크립트에 `ACTIVE` 안정 확인과 최대 1회 재시도를 추가했다.
- 두 번째 cold start(`env-8a53c39c6e22`)에서도 게스트 안정 검사 1차 실행이 실패했다. 게스트 복구 명령을 직접 재실행하고 환경을 재조정한 뒤 준비가 통과했다. 이어 공통 실행기에 제한된 게스트 복구 재시도와 실패 진단 기록을 추가했다.
- 세 번째 cold start(`env-d27a62139a0f`)는 **수동 개입 없이** 준비 완료됐다. control-plane·worker 게스트 모두 첫 시작 시도 후 `ACTIVE` 안정 확인을 통과했고, management/workload API와 기존 worker 1대가 Ready였다. 공통 실행기의 재시도 분기는 단위 테스트를 통과했지만, 이 세 번째 실환경 실행에서는 필요하지 않아 실제 재시도 상황의 수용 시험은 남아 있다.
- 준비 완료 시 management control plane 1대, workload control plane 1대, worker 1대가 Ready였다. 다시 `graduation-env-ensure`를 실행한 경우 GCP 호스트 시작 시각·ID가 그대로였고, 새 호스트 시작 없이 준비 상태를 확인했다.

## S4 사전 조건

- 기존 `worker-control` 기록의 `auto`·worker 1대에서 시작했다. 기존 제어 경로를 통해 `fixed`·worker 2대로 전환하고 MachineDeployment의 desired/ready/available 2대를 확인했다.
- management cluster에 worker 전용 `MachineHealthCheck`를 배포했다. `cluster.x-k8s.io/deployment-name=osk8s-workload-md-0` 선택자로 MachineSet 소유 worker 2대만 선택하고 control plane 1대는 제외했다. MHC 상태는 `expectedMachines=2`, `currentHealthy=2`였다.
- workload cluster에 PVC 없는 stateless HTTP Deployment 1개와 Service를 배포했다. Pod 1개가 Ready였고, 실제 배치 Node와 Machine UID, `openstack:///` providerID의 Nova VM ID를 연결했다.
- 장애 대상 worker 밖의 클라이언트에서 workload API의 Service 프록시를 통해 `/healthz`를 요청했다. 준비 직후 5회와 독립 재검증 5회, 총 **10/10회 `ok`**였다. 관측 지연의 중앙값은 **273.22ms**, 최대는 **293.98ms**다. 이 값은 API 터널·서비스 프록시를 포함하므로 일반 사용자 ingress 지연으로 해석하지 않는다.
- 원본 snapshot의 `errors`는 비어 있었고, Machine 3대·Node 3대·Nova VM 3대가 기록됐다. 원본과 MHC 객체, worker Machine, 두 차례 HTTP 결과는 [실행 증거](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-preparation-20260926T013427Z-a71fe05b)에 있다.
- 두 번째 독립 준비 실행에서도 MHC `expectedMachines=2`·`currentHealthy=2`, HTTP **10/10회 `ok`**, snapshot 조회 오류 없음으로 통과했다. HTTP 측정 지연 중앙값은 **265.42ms**였다. [두 번째 실행 증거](../../artifacts/cloud-gcp-amd64-greenfield/graduation-s4-preparation-20260926T020803Z-3d94dc4b)에 원본을 보존했다.

## 정리와 남은 검증

두 S4 준비 실행 모두 전용 MHC·HTTP 자원을 제거하고 worker 1대·`auto` 모드로 복원했다. 각 환경 실행이 기동한 GCP 호스트 세 대만 종료했다. 세 번째 cold-start 검증 후에도 소유 GCP 호스트 세 대가 모두 `TERMINATED`로 돌아왔다. 로컬 정적 검사·단위 테스트는 `make lint`에서 117개가 통과했다.

이 기록은 S4 복구 성공 증거가 아니다. 다음 실험에서는 동일 준비를 다시 실행한 후 정확한 Nova worker VM 한 대를 중단하고, HTTP 서비스 안정화와 대체 worker 용량 회복을 독립적으로 측정해야 한다. 현재 HTTP 측정 경로는 Kubernetes API Service 프록시이므로, 최종 결과를 일반 서비스 ingress 기준으로 제시하려면 별도 고정 진입 경로를 검증해야 한다.
