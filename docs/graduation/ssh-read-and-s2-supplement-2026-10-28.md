# SSH/IAP 명시 읽기 재시도와 S2 P 보충 1회

사용자는 진행 중인 실험을 중단하지 않고 SSH/IAP 읽기 오류 복구를 보완하고 무효 S2 P를 별도로 1회 더 측정하도록 명시 승인했다. 기존 S1 A 보충 1회도 유지한다. 본시험 original main29의 순서와 첫 시도 주분석은 유지하며, 이후 S1 A와 S2 P를 각각 독립 supplemental block에서 정확히 한 번 측정한다. 두 보충은 원무효를 대체하거나 이전 동시 paired block으로 합치지 않는다.

지시 수신 때 s3-b01-p3600은 이미 정리·판정·봉인됐고 s3-b02-p3600이 시작됐다. 기존 source694bd67/PID64387을 바꾸거나 중단하지 않고, 현재 case의 자연 종료·소유 정리·독립 판정·봉인 다음 기존 driver의 next-case gate에서 handoff하도록 REPAIR-REQUIRED.json을 설정했다. 수정은 별도 staging에서 준비했다. 실제 적용은 PID 종료와 단일 operator flock 해제 뒤에만 한다.

재시도 경계는 S2의 고정 curl /progress, qdisc show, 호스트 통계, receiver clock, 지정 port/QoS rule show 및 extension list, 현재 run_id의 지정 원자료 파일/준비 파일 확인 호출이다. S3의 최종 source hypervisor domstate도 기존 source instance_name·host에 묶인 명시 읽기만 허용한다. 임의 remote shell이나 원자료 경로를 허용하지 않는다. 기존 remote(), fault, workload/probe 실행, QoS 변경, patch/restart/delete를 통째로 재실행하지 않는다. 진행 중인 원격 probe는 읽기 복구 중 계속 동작한다. probe stop-file 응답 유실은 touch를 다시 보내지 않고 동일 파일의 존재부터 읽어 확인한다. 적용 여부가 확인되지 않으면 원오류를 보존한다.

각 명시 읽기는 원 timeout 안 최대3회, backoff1/2초다. identity 조회·실제 읽기·backoff가 같은 누적 deadline을 공유한다. raw 다운로드의 외부 collection loop는 1회만 두고 내부 SSH 읽기 최대3회를 사용하여 3x3 재시도를 막는다. 기존 kubectl 재시도와 겹치는 identity kubectl은 재시도 없는 직접 읽기이며 동일 remaining 시간에 제한한다. 기존 단계 전체 deadline도 유지한다.

IAP4047 Failed to lookup instance는 단독으로 일시 오류라고 판단하지 않는다. 재시도 전과 성공 후 GCP describe로 기존 프로젝트·zone·VM name·ID·RUNNING을 확인하고, 현재 environment run과 실험 namespace UID/소유 label을 직접 읽어 확인한다. 권한·설정·인증서·NotFound 등 영구 오류나 identity 불일치는 즉시 반환한다. 반복 실패·deadline 초과는 TimeoutError로 남기며 오류·시각·실제 duration·관측 공백을 기록한다. 성공한 재조회는 그 시점의 실제 값이며 빈 구간을 정상값으로 보간하지 않는다.

분석기·calibration/DEV 계측 source6개·앱·부하·fault·정책·SLO/H·안정창·표본수는 원 SHA/계약 그대로다. AST 검사는 명시 읽기 adapter와 bounded collection 선택만 제거하면 원 시나리오/정책 본문이 동일함을 검증한다. source exemption, 옛 manifest/hash 변경, 완료 측정 복사, 준비8 기계적 재실행은 없다. 준비8의 원판정/원자료/source·계약 동일성과 AST·회귀로 재사용 근거를 남긴다. 모든 새 source와 정확한 diff·영향 검토·검증 증거를 새 freeze에 결합한다.

s1-b02-a 및 s2-b03-p 원무효와 cleanup 판정/원자료는 불변이다. S2 원무효의 분석기 UnboundLocalError도 별도 행정 무효 봉인 그대로 유지한다. 보충 id는 s1-b02-a-supplement01, s2-b03-p-supplement01이며 purpose=supplemental, 독립 block, 각 max_attempts=1이다. 본시험29 봉인 전 보충 admission을 거부하고 S1 보충 봉인 전 S2 보충을 거부한다. 두 보충이 실제 끝나기 전 driver/heartbeat 완료·down·삭제를 금지한다.

신규작업146234원·정리reserve40000원·불확실성20000원은 같은 공유원장에 단1회 유지하며 실시간 Billing으로 표현하지 않는다. 현재 case와 staging을 병행하고 전환10분·약444원, 추가 S2 P는 유효 완료 실측 최대에20%를 더한 약46분·약2051원을 보수적으로 잡았다. 기존 S1 보충·미완 main·정리를 포함한 잠정 전체 ETA는 10월29일02:42KST·약141851원이며, 실제 경계 종료 뒤 완료 작업을 제외하여 다시 갱신한다. 중단 중 확정 forecast는 null이다. 시간 목표는 advisory이고 실제 비용 부족은 조기 알린다.

최종 보고는 모든 raw/invalid/분석기 예외·source 경계와 두 보충의 비동시성 한계를 공개한다. paired 원자료 차이·중앙값·범위, latency/upload tradeoff, S2 API 영향과 정상유지/복구의 구분, S3 timer/H, S4 기존 MHC 역할을 포함한다. final main29+보충2 실제 측정·분석/보고·소유정리·기존3VM TERMINATED·공유원장 종료를 모두 확인한 뒤 단일 heartbeat를 삭제한다.

실제 handoff는 17:36:02 KST에 끝났다. s3-b02-p3600은 원 source에서 trial_valid/fault/impact/recovered/safety/cleanup 모두 참, missing=[]로 봉인됐고 PID64387과 단일 flock이 해제됐다. 경계 원자료는 preparation10(유효8/무효2)+main20(유효18/무효2)=총30봉인이며 보충0이다. 8개 추가 source 파일을 적용하기 전에 모든 봉인과 frozen manifest/hash를 별도 감사로 보존했다. 새 cohort에는 미실행 main9만 남고, 본시험 뒤 S1 A 및 S2 P 보충 각1회가 뒤따른다.
