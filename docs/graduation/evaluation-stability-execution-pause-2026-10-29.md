# 안정화 재개 후 첫 case 준비 실패와 소유 정리

2026-10-29 KST. 결과는 **일시중지**다. 전체 평가·최종 보고는 완료되지 않았다. 기존 06:47 완료 예상은 철회한다.

## 실제 수행과 판정

`3375f9069022055ceca3b09e789729704be956ec`의 source249와 stability-v7 authorization/profile/freeze를 검증하고 00:20에 단일 driver를 시작했다. 기존 pause 세 파일과 active pointer 원문·SHA는 [인수 기록](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/takeover.json)에 보존했다. 준비실험은 재실행하지 않았다.

첫 `s4-b02-off`는 worker 준비 단계가 00:50:54에 1,800초 상한으로 종료됐다. 장애 주입, baseline 부하 및 H 관측은 시작하지 않았다. 최초 정리는 lock 경합으로 00:51:06에 실패했다. 이를 새 하네스 실패로 처리하고 다음 case를 중지했다. 시각 보호 lease를 arm하는 단계에 도달하지 않았다.

01:06~01:07에 저장된 original-worker와 worker-operation journal, Cluster/MD/CA UID를 대조한 뒤 소유 정리만 수행했다. worker 2/fixed를 원래 1/auto로 복원했고 mutation을 무조건 재전송하지 않았다. 이후 동결된 `resume-cleanup --case s4-b02-off`로 정리를 검증하고 attempt를 닫았다. strict 판정은 **invalid**, cleanup은 **true**다. 무효를 성공으로 변경하거나 같은 case를 재측정하지 않았다.

| 구분 | 닫힌 attempt | 유효 | 무효 | 미실행 |
|---|---:|---:|---:|---:|
| preparation | 10 | 8 | 2 | 0 |
| 원래 main first-attempt | 27 / 계획 29 | 19 | 8 | 2 |
| 별도 보충 | 0 / 승인 4 | 0 | 0 | 4 |

남은 순서는 `s4-b03-off → s4-b03-on → s1-b02-a-supplement01 → s2-b03-p-supplement01 → s3-b02-m3600-supplement01 → s3-b03-m3600-supplement01`다. 현재 모두 pause 상태다. `s4-b02-off`의 추가 attempt는 승인 범위에 없다.

## 관측한 원인과 한계

준비 단계의 `openstack-workload-inventory` 읽기는 16개 호출 묶음, 총 48개 시도가 모두 timeout이었다. 20초 명령 상한과 90초 작업 예산을 소진했고 성공한 inventory capture는 0개다. `workload_state.snapshot()`은 이 예외를 `nova` unavailable로 수집하여 readiness loop를 계속했다. 결과적으로 과학적 측정 전에 준비 단계 전체 예산을 소진했다.

`scripts/workload-inventory.sh`는 한 SSH 호출 안에서 여러 OpenStack CLI 조회를 순차 실행한다. 이 복합 호출 전체가 새 외부 20초 상한을 받는다. 따라서 **등록 단위와 timeout 적용 단위가 실제 작업의 크기에 맞는지 검증이 부족했다.** 개별 API 지연과 네트워크 최초 원인은 이번 기록만으로 확정하지 않는다. 복합 조회 구조를 이유로 timeout을 임의 확장하거나 측정 조건을 바꾸지 않았다.

최초 cleanup은 `BlockingIOError: Resource temporarily unavailable`로 실패했다. 이후 평가 자식 프로세스가 없고 관련 lock이 가용함을 확인한 뒤 소유 정리를 완료했다. 종료 시점 자식 정리와 lock 해제 경계도 회귀 검토 대상이다.

기존 qualification은 ConfigMap fixture와 synthetic read 장애·시각 복원 검증을 통과했지만, 이 복합 inventory를 사용하는 실제 worker 준비 lifecycle의 성공을 입증하지 못했다. H 전용 retry 분기는 오프라인 검증이며 live qualification에서 실행했다고 주장하지 않는다.

분석기에 표시되는 baseline/clock-origin/H 누락 사유는 **해당 측정자료가 생성되지 않았기 때문**이다. 이번 실패에서 실제 clock step을 관측했다는 뜻이 아니다.

## 자료 보존과 분석

기존 10,234개 파일의 SHA 불변을 다시 검증했다. 기존 main26의 유효19·무효7은 유지된다. S2-b03-P의 분석기 예외가 구체적인 H 누락 사유로 바뀌는 기존 sidecar 차이를 유지한다.

[별도 집계](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/interim-analysis/report.md)는 원래 strict first-attempt 판정과 보충 표를 구분한다. [전건 사후감사](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/interim-analysis/posthoc-measurement-audit.json)는 원자료·identity·hash와 동일한 규칙을 적용한다. 모든 execution error가 독립적으로 관측된 H 종료 뒤에 있고 다른 원자료·baseline·시각·시나리오 결측이 없는 경우만 측정완전성을 별도로 표시한다. 과거 측정봉인을 만들어 넣거나 strict invalid를 승격하지 않는다. S3-b02-M3600과 S4-b02-on은 이 사후 완전성 조건을 충족하지만 주분석에서는 계속 무효다. 새 s4-b02-off는 H 미실행으로 이 조건도 충족하지 않는다.

조건별 표본 수와 완전한 paired block이 부족하고 transport·clock 운영 버전이 혼합되어 있다. 유효 표본만의 성능을 전체 계획 29건의 무조건적 효과로 해석하지 않는다. 이번 중간 집계는 최종 효과 보고서가 아니다.

## 종료 상태와 재개 전 검토

[정리 readback](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/readiness-failure/closure-readback.json)은 동일 3VM RUNNING·관리 UID 동일·worker 1/auto·fixture namespace 부재·trial taint 부재·평가 프로세스 부재·lock 가용·source249 불변을 확인했다. 중간 pause 지시에 따라 VM을 정지하거나 공유원장을 종료하지 않았다.

clock guard 서비스는 설치된 상태로 유지되며 daemon 상태는 `restored`, 원설정은 On / time.asia.apple.com이다. 실패한 attempt는 clock lease를 arm하지 않았다. 이번 closure에서 직접 `systemsetup` readback을 시도했으나 `sudo -n`이 비밀번호를 요구해 현재 설정을 독립적으로 다시 읽지는 못했다. 기존 실제 재부팅 후 직접 확인한 복원 증거와 변경되지 않은 daemon 상태를 구분한다.

비용은 최신 표시 잔액 136,983원을 기준으로 보고 이후 경과·남은 범위 추정, cleanup 40,000원·기타 20,000원·미반영 12시간이라는 보수적 미확인 가정을 사용한다. 과거 원장을 새 잔액에서 다시 차감하지 않는다. [closure 비용 checkpoint](../../artifacts/fresh-evaluation-measurement-repaired-2026-10-27/stability-execution-2026-10-29/readiness-failure/closure.json)의 여유는 청구서 잔액이 아니며, pause 중에도 3VM 유지 비용이 계속 발생한다. 현금초과·유료전환은 승인되지 않았다.

재개 전에는 복합 inventory의 명령·작업 예산 단위와 종료/lock 해제 경계를 검토하고, 수정한다면 새 source·회귀·실제 준비 경로 검증·freeze와 이번 실패 후의 재개 조건을 다시 확정해야 한다. 현재 소스나 deadline을 고치거나 driver를 다시 시작하지 않았다. 이 pause는 새 하네스 무효가 생기면 정리 후 다음 case를 멈추라는 사용자 지시에 따른다.
