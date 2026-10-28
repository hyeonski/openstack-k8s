# 평가 안정화 구현 및 재부팅 검증 인계

담당: Astra High `01a1829e-502e-7792-ab6c-ddbbd3f2fe91`. 이 문서는 기존 합의와 세션 인계 문서의 구현 결과를 기록한다. 최종 GO는 실제 재부팅 복원·최종 소스 검증·새 freeze를 모두 확인한 뒤 별도 증거에 기록한다. 작성 중에는 기존 pause 세 파일, 기존 active pointer, heartbeat PAUSED를 유지한다.

## 구현 범위

- 운영 읽기: `fresh_read_budget.py`가 최초 포함 3회, 명령 20초, 작업 90초, 10/25초 backoff를 공유한다. 중첩 호출은 같은 deadline을 사용한다. 구조화된 Kubernetes/OpenStack/GCP 및 명시적 SSH 읽기만 등록한다. 서비스 proxy/SQL probe와 mutation은 자동 재전송하지 않는다.
- `config/fresh-read-registry.json`: 원격 호출 AST와 파일 전체 SHA를 함께 등록한다. 새 호출뿐 아니라 변수·상수 변경도 preflight에서 막는다. legacy standalone 경로와 typed dispatcher도 명시하며, 이것이 legacy 평가 실행 권한을 추가하지 않는다.
- 원격 host/CPU/SQL integrity capture는 한 번만 생성한 고유 파일을 회수한다. 응답 유실 뒤 새 관측을 만들어 대체하지 않는다. mutation intent를 기록하고, 지원되는 소유 변경은 응답 유실 뒤 같은 UID/이름/ownership 상태를 읽어 확인한다.
- H 종료·필수 자료·identity·clock·strict 분석 가능성을 검증한 뒤 격리된 `measurement/` 사본과 해시를 fsync하여 봉인한다. 시각 설정 복원 뒤 cleanup을 진행하며 cleanup 증명은 별도로 필수다. cleanup 실패는 기존 strict verdict에서 계속 invalid다.
- 분석기의 H 누락 초기화/guard만 고치고, cleanup 전 봉인용 별도 검사 인자를 추가했다. 기본 strict 판정은 유지한다. 과거 main26 sidecar의 valid19 판정·지표가 동일하며 invalid7은 그대로 invalid다. S2-b03-P만 분석기 exception 대신 H 누락 등 구체적인 missing 사유를 얻는다. 이 사례의 execution/safety/fault_realized/provenance/metrics/missing/impact_realized가 달라졌으며 trial_valid는 계속 false다. 나머지 25건은 지표를 포함해 동일하다.

## H와 정상 읽기 경계

기존 성공한 읽기는 기존 호출의 완료 규칙을 유지해야 한다. 원래 loop가 H 직전 시작한 정상 읽기 또는 마지막 진행률 확인은 H 경계 뒤에 끝날 수 있었으며, 분석 구간은 항상 실제 주입 시각부터 고정된 H다. 이를 새 global hard cutoff로 바꾸면 정상 마지막 snapshot도 실패할 수 있다.

따라서 baseline의 원래 hard deadline은 모든 시도에 적용하고, H의 남은 예산은 **추가 재시도와 그 identity/backoff**에 적용한다. 최초 정상 호출도 명령 20초/원래 caller timeout을 넘을 수 없다. H 이후 실패를 재시도로 살리지 않으며, H·부하·요청 분모·분석 구간을 늘리지 않는다. 이 구분은 fake clock 회귀로 검증한다.

30분 live qualification은 scientific H를 설정하지 않는다. 이후 이 H 전용 분기와 calibration binding의 정확한 운영 patch가 반영되면, qualification 당시 소스를 별도 보존하고 literal reversal 검사를 통해 그 시험에서 실행된 경로가 바뀌지 않았음을 검증한다. 해당 H 분기를 live 시험했다고 주장하지 않으며 최종 소스의 오프라인 경계 시험으로 검증한다. 소스가 일반적으로 달라도 허용하는 우회는 없다.

## 시각 보호 운영

실제 설치물:

- `/Library/LaunchDaemons/dev.openstack-k8s.clock-guard.plist`
- `/Library/Application Support/openstack-k8s-clock-guard/service.py`
- root 상태·로그: `/var/db/openstack-k8s-clock-guard`
- UID 501 요청 디렉터리: `/var/run/openstack-k8s-clock-guard`

설치 전 원설정은 Network Time **On**, 서버 **time.asia.apple.com**이다. 서비스는 root 소유의 고정 프로그램이며, 요청에 임의 명령/경로를 허용하지 않는다. PID·UID·시작 시각·boot ID·고유 token을 확인하고 원설정을 fsync한 뒤 보정을 끈다. runner 종료, 만료, 서비스 crash/restart, clock step, 재부팅에서 원설정을 복원한다. clock step·lease 만료·daemon 재시작은 평가 부모에게 SIGTERM을 보내며 부모는 어댑터 process group을 중단하고 소유 정리로 전환한다.

35분/45분은 채택하지 않았다. 기존 전체 어댑터 상한 5,400초 안에서 마지막 90초를 봉인에 예약한다. 보호 요청부터 어댑터는 최대 5,310초보다 초기 arm 시간을 뺀 예산, 봉인은 최대 90초다. 보호 ceiling은 90분, 독립 daemon watchdog ceiling은 95분이다. 기존 전체 실행 예산을 늘리지 않는다.

| 구간 | 기존 과학적 시간 | 보호 예산에 포함되는 것 |
|---|---:|---|
| S1 | H 1,200초, 전체 부하 1,800초 | baseline, 전체 부하 종료, Job/로그·host/CPU 수집, 검증·봉인 |
| S2 | H 1,200초, uploader 1,800초 | baseline, 원래 tail, 원격 원자료·integrity 수집, 검증·봉인 |
| S3 | H 900초 | baseline, 원래 DB/volume·controller 증거, 검증·봉인 |
| S4 | H 1,200초 | baseline, 원래 capacity/identity 증거, 검증·봉인 |
| 공통 | 기존 어댑터 5,400초 | 위 작업 전부와 봉인을 합쳐 5,400초 이내; 초과 시 중단·invalid |

fixture 준비/worker 준비는 보호 시작 전이다. cleanup은 봉인 뒤 원설정 복원 후다. daemon이 idle/restored일 때는 NTP를 꺼두지 않는다. 정상 종료·소유 프로세스 SIGKILL·짧은 lease 만료·daemon SIGKILL 후 launchd 재시작은 실제 OS에서 검증했다. 실제 reboot cycle은 사용자가 수행하며, graceful shutdown 중 복원된 경우와 새 boot에서 복원된 경우를 구분하여 증거를 남긴다.

장애 때 임의 시계 step, 공유망 차단, VM 재생성, source 변경을 통한 gate 우회를 하지 않는다. 원설정 미복원 시 새 case를 시작하지 않는다. 설치 제거는 `sudo bash scripts/install-fresh-clock-guard.sh uninstall`이며 먼저 원설정 복원을 수행한다. 검증 후 남은 평가가 끝나면 이 설치물의 유지/제거와 원설정 상태를 최종 보고한다.

## 검증 및 재개 규칙

증거 루트: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-v7`.

- 원본 보존 대상 10,234파일의 SHA를 최초 저장했다. 기존 source/raw/verdict는 수정하지 않는다.
- 최종 전체 회귀 191개가 70.994초에 통과했다. H 경계·credit·binding 검사를 포함하며, 최종 소스 SHA와 로그를 `tests-final.json`에 기록했다.
- 표본 외 qualification은 1회, 45분 상한이다. 30분 clock 관찰과 20초 synthetic 읽기 장애를 겹치고, 고유 ConfigMap patch 응답 유실 readback 및 UID 조건부 cleanup을 검증했다. 실제 1,810.126초에 통과했고 보호 관찰은 1,800.005초, 장애 복구는 3회/44.620초다. offset bound 최대 2.5664초(<5초), local wall/monotonic 차이 최대 0.000240초다. 실제 서비스/VM fault는 없다.
- preparation10(유효8/무효2), main26(유효19/무효7), supplement0을 보존한다. 준비8 재실행 없이 기존 calibration 원자료와 preparation 계약을 검증해 재사용한다.
- calibration source 변경 허용은 baseline deadline wrapper, H 누락 guard, cleanup 전 검사 분리, 이 exact binding 분기만 역변환해 기존 SHA와 대조한다. SLO·부하·지표 계산을 바꾸면 거부한다.
- 새 profile: `.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261028-stability-v7.json`. 새 cohort: `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/bed-stability-v7`. 실제 실행 전 새 source/policy/freeze와 승인 증거가 일치해야 한다.
- 남은 순서: `s4-b02-off → s4-b03-off → s4-b03-on → s1-b02-a-supplement01 → s2-b03-p-supplement01 → s3-b02-m3600-supplement01 → s3-b03-m3600-supplement01`. 각각 최대1회다.
- 새 harness/clock invalid가 발생하면 소유 정리와 제한 readback 후 다음 case를 pause한다. 성공할 때까지 재측정하거나 원 invalid를 대체하지 않는다.

## 비용 계산

최신 사용자 표시 잔액은 136,983원이다(사용 298,540/총 435,523). 2026-10-28 20:45:40 KST 기록 이후 경과 비용과 앞으로의 비용만 차감한다. 과거 누적 원장 전체를 다시 차감하지 않는다. 원장은 감사용으로 그대로 유지한다.

기존 계획 rate 약 2,666.67원/시간, 정리 reserve 40,000원, 기타 불확실성 reserve 20,000원을 유지한다. billing cutoff는 미확인이다. admission은 추가로 미반영 12시간을 **확인되지 않은 보수적 가정**으로 잡고, 0/6/12시간 민감도와 손익분기 시간을 함께 기록한다. 유료 전환·현금 초과는 허용하지 않는다. 오래된 146,234원 필드는 역사적 profile 호환용으로 보존하지만 새 admission에서 최신 잔액 대신 사용하지 않는다.

## 실제 재부팅 이후 Astra가 할 일

1. `stability-v7/reboot-test`의 ready/heartbeat와 현재 boot ID, daemon 실행 상태·설치 SHA·NTP 원복 상태를 확인한다. qualification 및 재부팅 증거를 합쳐 `clock-restore-proof.json`을 만든다.
2. 기존 3VM/Cluster/MD/CA UID, worker 상태, 소유 fixture 부재, 실행 PID/lock을 읽기 전용으로 확인한다. 이전 tunnel keeper는 재부팅으로 사라지므로 로컬 tunnel만 재연결한다.
3. 최종 소스 회귀, 원본 SHA 및 sidecar 차이, credit·ETA를 갱신한다. 과거 증거를 소스 현재성 우회로 재기록하지 않는다.
4. 부팅 전 구현·검증 commit의 실제 HEAD/source SHA를 확인하고 그에 대응하는 v4 authorization과 S4 main3 freeze를 만든다. GO 전에는 active pointer나 pause marker를 바꾸지 않는다.
5. GO이면 사용자가 이미 승인한 새 `gpt-6.1-sol` High 로컬 세션을 만들고 정확한 commit, profile, authorization/freeze, 명령, clock 원복 책임, 원본 보존, 비용·ETA를 전달한다. 새 Sol이 단일 실행권을 인수한 뒤 원문을 보존하며 marker를 resolved 전환한다. 기존 PAUSED heartbeat는 재활성화하지 않는다.
6. 새 세션의 실제 착수를 한 번 확인한 뒤 Astra는 공유 소스/driver/인프라 수정을 멈춘다. 기존 두 세션은 보존한다.
