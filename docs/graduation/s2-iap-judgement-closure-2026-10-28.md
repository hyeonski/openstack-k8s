# S2 IAP 읽기 실패와 무효 봉인 복원

`s2-b03-p/attempt-01`은 새 source c7804d9에서 실행했고, 2026-10-28 14:34 KST경 SSH/IAP `4047: Failed to lookup instance`로 업로드 진행률 읽기가 중단됐다. probe stop-file 요청도 같은 오류로 실패했으므로 변경 명령을 반복하지 않았다. 기존 probe는 자연 종료했고 15:02:36 KST부터 canonical 실행자가 정리했다. 15:09:14 KST에 소유 정리 10항목이 모두 참으로 확인됐다. VM 3대의 원 ID·종류는 그대로다. Mac 잠자기가 원인이라는 증거는 없다.

중단 원자료에는 horizon_end가 없으며 기존 분석기는 이 경로에서 start 변수를 참조하다 UnboundLocalError를 냈다. 실행자는 정리 후 종료됐고, case의 VERIFIED 표시는 판정·hash 봉인 완료를 뜻하지 않았다. 운영 감사에서 이를 무효 미봉인으로 분리한다.

분석기 fresh_analysis.py와 앱·부하·fault·정책·H/SLO·안정창·표본수·calibration의 원 SHA를 유지한다. 실행 관리의 순수 wrapper는 기존 분석기를 그대로 호출하고 정상 결과를 그대로 반환한다. 분석기 예외만 명시적 trial_valid=false, fault/impact/recovered/safety=null, execution=judgement_failed로 보존한다. cleanup은 실제 기존 소유 정리 검사로만 확인한다. 성공 승격·추정 metrics·관측 보완·raw 변경은 없다. 보고 재계산도 원자료에 쓰지 않는다.

판정 실패 건은 재정리나 fault 재주입 없이 원자료 preclosure hash와 오류 기록, 실제 cleanup을 확인한 뒤 무효 결과로 닫는다. 기존 원자료 파일은 그대로이고 판정 실패 설명·무효 판정·봉인만 추가한다. 이전 봉인 25 attempt는 불변이다. main 첫 시도는 16건 중 유효14/무효2이며, preparation은 10 attempt 유효8/무효2다. 미실행 main13만 원순서로 새 cohort에서 이어가고 승인된 S1 A 보충1은 original main29 뒤에 그대로 분리한다. S2 추가 시도는 하지 않는다.

production Python3.11 회귀 131건 통과. 정상 판정 동일성, 분석 예외의 unknown 결과, cleanup 누락/실패의 비승격, KeyboardInterrupt 전파, 봉인 raw 비수정 검사를 포함한다. 새 freeze는 전체 source234와 이전 source에서 추가된 정확한 3파일 diff를 기록하고, 최초 230 source 대비 전체 diff와 원 preparation 재사용 감사도 함께 고정한다. 새 profile은 artifact_root만 다르다. 완료된 시나리오는 재등록하지 않는다.

실패/중단 중 forecast는 null이다. 같은 공유 비용 원장·신규작업146234원·정리 reserve40000원·불확실성20000원 단1회를 유지하고, 미실행13건+보충1을 포함한 재개 예측을 다시 산출한다. 모든 raw, 이번 분석기 예외, source 경계 및 원무효를 최종 보고에 공개한다.
