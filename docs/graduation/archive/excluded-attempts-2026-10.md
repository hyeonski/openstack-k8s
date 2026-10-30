# 33회에 포함하지 않은 실험 기록 (2026-10-27 ~ 10-29)

최종보고서의 "11개 조건, 총 33회"에 들어가지 않은 실행 15회의 색인이다. 모두 실험 진행 자체가 제대로 완료되지 않아 결과로 쓰지 않은 실행이다. 원인은 관측 경로·시계·준비·정리 단계의 문제이며, 서비스가 복구되지 않아서 제외한 실행은 없다.

## 보관 위치

원자료 폴더(`artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`)를 정리하더라도, 아래 압축본만 남겨 두면 15회 전체를 복원할 수 있다. `artifacts/`는 Git에 포함되지 않으므로, 압축본은 저장소 밖(개인 드라이브 등)에도 한 부 복사해 두는 것을 권한다.

| 파일 | 내용 |
|---|---|
| `artifacts/archive/excluded-attempts-2026-10/excluded-attempts.tar.gz` | 15회의 attempt 디렉터리 전체, 판정 집계 JSON 4개, 측정 전 거부된 실행의 campaign 기록. 1,844개 파일, 12.4 MB |
| `artifacts/archive/excluded-attempts-2026-10/manifest.json` | 압축본 안 파일마다 경로·크기·SHA-256 |
| `artifacts/archive/excluded-attempts-2026-10/SHA256SUMS` | 압축본과 manifest의 SHA-256 |

압축본 SHA-256: `c8018a40fa29ce96fe8d4ac0c7a19187c2ee96614073b9b85358e5503e3ccd1a`

압축본을 만들 때 manifest의 1,844개 파일 해시를 압축본 안에서 다시 읽어 모두 일치함을 확인했다. 복원은 원자료 폴더를 기준으로 푼다.

```bash
shasum -a 256 -c artifacts/archive/excluded-attempts-2026-10/SHA256SUMS
```

```bash
tar -xzf artifacts/archive/excluded-attempts-2026-10/excluded-attempts.tar.gz -C artifacts/fresh-evaluation-measurement-repaired-2026-10-27
```

## 15회 목록

- 시각은 attempt의 첫 사건 기록 기준(KST)이다.
- 진행 단계의 "주입"은 장애가 실제로 적용됐다는 뜻이고, "조치"는 정책이 조치를 적용했다는 뜻이다.
- 원인 요약은 운영 기록([평가 운영·수리 기록 통합본](evaluation-operations-log-2026-10-27-29.md))과 판정 결측 코드를 근거로 정리했다.

| # | 실행 | 시작(KST) | 진행 단계 | 원인 요약 | 판정 결측 코드 | 같은 조건으로 다시 한 실행(33회 중) |
|---:|---|---|---|---|---|---|
| 1 | s1-b02-a (시나리오 1, 동일 노드 재시작) | 10-28 07:13 | 주입·조치 후 중단 | 관측 중 운영 클라이언트의 API 터널 연결이 끊겨 요청 기록이 불완전해짐 | execution_interrupted, request_arrivals_incomplete 외 | s1-b02-a-supplement02 |
| 2 | s2-b03-p (시나리오 2, 제안 방식) | 10-28 14:31 | 주입 후 측정, 판정 실패 | 측정 뒤 판정기가 예외로 종료됨(관측 구간 누락을 처리하지 못한 코드 결함) | judgement_error | s2-b03-p-supplement01 |
| 3 | s3-b02-m3600 (시나리오 3, 무조치) | 10-28 17:51 | 주입·관측 완료 후 중단 | 관측 구간 종료 뒤 정리 단계에서 API 터널이 끊겨 실행이 중단됨 | execution_interrupted | s3-b02-m3600-supplement03 |
| 4 | s3-b03-m3600 (시나리오 3, 무조치) | 10-28 18:32 | 주입 전 중단 | 준비 단계의 원격 읽기 실패로 기준선 측정 전에 중단됨 | baseline 관련 결측, execution_interrupted 외 | s3-b03-m3600-supplement01 |
| 5 | s3-b03-p3600 (시나리오 3, 제안 방식) | 10-28 18:59 | 주입·조치·관측 완료 | 측정 중 운영 노트북의 시계가 자동 보정되어 요청 시각이 어긋남 | clock_step_between_requests | s3-b03-p3600-supplement01 |
| 6 | s4-b01-off (시나리오 4, MachineHealthCheck 미사용) | 10-28 19:46 | 주입 전 중단 | 장애 주입 전 운영 노트북의 시계 보정으로 기준선 시각이 어긋남 | baseline_clock_disagreement 외 | s4-b01-off-supplement01 |
| 7 | s4-b02-on (시나리오 4, MachineHealthCheck 사용) | 10-28 20:45 | 주입·관측 완료 후 중단 | 관측 뒤 정리 단계에서 Cluster Autoscaler 상태 확인이 TLS 시간 초과로 실패함 | execution_interrupted | s4-b02-on-supplement01 |
| 8 | s4-b02-off (시나리오 4, MachineHealthCheck 미사용) | 10-29 00:50 | 주입 전 중단 | 준비 단계에서 잠금 파일 충돌(BlockingIOError)로 중단됨 | baseline 관련 결측, execution_interrupted 외 | s4-b02-off-supplement01 |
| 9 | s1-b02-a-supplement01 (시나리오 1, 동일 노드 재시작) | 10-29 03:29 | 주입 후 중단 | 관측 중 자원 목록(inventory) 읽기가 실패해 실행이 중단됨 | execution_interrupted, horizon_missing 외 | s1-b02-a-supplement02 |
| 10 | s3-b02-m3600-supplement01 (시나리오 3, 무조치) | 10-29 05:20 | 주입 요청 직후 중단 | 장애 주입 직후 기존 DB 프로세스 확인 읽기가 실패해 중단됨 | execution_interrupted, horizon_missing 외 | s3-b02-m3600-supplement03 |
| 11 | s3-b02-m3600-supplement02 (시나리오 3, 무조치) | 10-29 12:00 | 주입 전 중단 | 준비 단계의 DNS 확인 실패로 기준선 측정 전에 중단됨 | baseline 관련 결측, execution_interrupted 외 | s3-b02-m3600-supplement03 |
| 12 | s2-x01-s (시나리오 2, 작업 분리 단독) | 10-29 16:16 | 측정 전 거부 | 실행 프로필의 환경 식별자가 재기동한 환경과 달라 장애 주입 전에 거부됨 | — | s2-x01-s (v13) |
| 13 | s2-x02-s (시나리오 2, 작업 분리 단독) | 10-29 16:32 | 측정 전 거부 | 같은 원인 | — | s2-x02-s (v13) |
| 14 | s2-x03-s (시나리오 2, 작업 분리 단독) | 10-29 16:48 | 측정 전 거부 | 같은 원인 | — | s2-x03-s (v13) |
| 15 | s2-x04-p (시나리오 2, 제안 방식) | 10-29 17:02 | 측정 전 거부 | 같은 원인 | — | s2-x04-p (v13) |

## 함께 알아둘 것

- **진행 단계별 분포:**
  - 장애 주입 전에 멈춘 실행: 8회(#4, #6, #8, #11~#15)
  - 주입 직후 멈춘 실행: 1회(#10)
  - 주입 이후 관측·정리·판정 단계에서 멈춘 실행: 6회(#1~#3, #5, #7, #9)
- **측정 완전성이 확인된 실행:** #3과 #7은 관측 구간의 측정 자료가 사후 감사에서 완전했지만, 실행이 정리 단계에서 중단되어 결과로 쓰지 않았다.
- **준비 실험:** 준비 실험 10회(`bed-a/*-pilot-v1`)는 분석 대상이 아니므로 이 목록에 넣지 않았다. 원자료 폴더를 정리할 때 함께 지울지는 따로 정한다.
- **원자료 경로:** 각 실행의 원래 경로는 `manifest.json`의 `attempt_dirs`에 있다.
