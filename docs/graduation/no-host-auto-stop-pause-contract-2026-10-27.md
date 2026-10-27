# 자동정지 해제·실험 중지/재개와 최종08시 종료 계약

사용자는10/27 기존 세 호스트의10시간 자동정지 제거를 명시적으로 요청했다.13:30에는 실험만 안전하게 멈추고 기존 호스트를 RUNNING으로 대기,17:30 재개하며 그 사이 재기동으로 시간을 쓰지 않는 것이 목적이다. 이전10시간 수명 유지·17:30 수명 부족 회전 지시는 대체됐다. 이어 완료 목표를 **2026-10-29 08:00 KST(`2026-10-28T23:00:00Z`)**로 연장한 뒤, 이를 hard deadline으로 삼지 말고 기존44/48h도 시간만을 이유로 자동 중단하지 말라고 명시적으로 승인했다. 따라서 달력/누적시간은 목표·추적 지표이며 비용·크레딧·신규146234원·정리40000원·reserve20000원1회와8 preparation/29 main·관측·안전·정해진 재시도 조건을 유지한다.

## 실제 클라우드 변경과 경계

설치된 `gcloud compute instances set-scheduling --help`에서 확인한 `--clear-max-run-duration --clear-termination-time --clear-instance-termination-action`만 기존 controller/compute01/compute02에 실행했다. VM ID는8689617440184466555/4452491138774596731/190540613588614267이며 사양과 다른 scheduling 속성은 동일하다. 세 호스트 모두 해당 세 필드 부재를 readback했다. 별도 짧은 자동정지를 만들지 않았다.

원본 전후·명령 결과는 V5 root의 `auto-stop-removal/`에 보존한다. 이 scheduling 변경에는 stop/start·새 VM·사양 변경을 섞지 않았다. 다만 최신 지시 도착 **이전** V5 무효 판정 뒤의 기존 자동 down이 이미 시작돼 세 호스트가 정지된 상태였다. 그 down은 완료·원장 종료로 확정했다. 운영 코드 준비 후 수행하는 한 번의 정상 ensure는 그 상태를 복구하는 기동이며10시간 회전이 아니다. 복구 후13:30 대기·17:30 재개 사이에는 down/ensure를 하지 않는다.

IaC의 평가용 세 호스트 `max_run_duration_seconds` 기본값은null, `max_run_duration` 블록과 STOP action은 옵션값이 있을 때만 생성한다. 일회용 image-builder의 기존36000초 보호는 별도 변수로 유지하며 이번 승인 범위 밖의 builder를 변경하지 않는다. Terraform apply는 하지 않고 실제 기존 VM scheduling만 위 명령으로 변경했다.

## 달력·가동 안전 계약

새 profile의 `operations.host_lifetime_policy`는 이 문서 SHA·정확한 세 호스트 범위·완료 목표·`cost-bounded-targets-only` 모드를 묶는다. live validator는 실제 cloud cap/terminationTime이 남아 있으면 거절한다. 명시적 정책이 없는 과거 profile은 여전히 기존 cloud/time/uptime guard를 유지한다. max_run_seconds가None/0이고 새 승인이 있을 때 effective deadline은None이다. 이를즉시만료나Infinity JSON 값으로 만들지 않는다.

`calendar_targets_only=true`, `uptime_targets_only=true`는 문서 SHA와 비용·reserve 조건을 검증해야만 유효하다. legacy schema의 hard_stop/last-case/last-injection/drain/down 시각과44/48h 숫자는 목표 참조로 남지만 시간만으로 admission·주입·정리·자동down을 막지 않는다. campaign budget_seconds의44h 누적 시간 차단도 적용하지 않는다. 08시 목표에서 역산한05시/06시/07시/07:30 시각은 계획 정보이며 자동 종료 명령이 아니다.

개별 명령의 timeout과 fixture1800/adapter5400/cleanup1800/down1800초는 작업이 영구 정체되지 않게 하는 기존 운영 오류 경계로 유지한다. H/stream/필수 증거를 축소하지 않으며 시간 목표를 맞추기 위한 중단 수단으로 쓰지 않는다. phase에 옛 달력until을 추가 적용하지 않는다. case에 필요한 준비·관측·정리 비용 예약은 그대로 비용 gate에 전달한다. 비용 원장 gate와 실제 크레딧 만료 시각은 계속 강제한다. 유효 미회복을 timeout 실패로 재분류하거나 성공할 때까지 반복하지 않는다.

고정10시간 회전과 S1 논리 SESSION-A/B 또는 시나리오별 강제 down/ensure는 제거한다. 순서·block·논리 session label은 보존하되 독립된 host 환경이라고 주장하지 않는다. case별 서비스·경쟁·QoS·volume·taint·controller·worker auto/1 소유 cleanup과 identity 검증은 그대로다. 준비 전체 go/no-go 뒤 가능한 즉시 main에 들어간다.

전체 완료 추정은 운영 참고·조기 경고용이다. 옛24시간/자정 목표 또는 보수적 전체 합계만으로 불필요한 stop·재승인 요청을 하지 않는다. 실제 case의 필수 비용 예약·크레딧/정리reserve·안전 gate는 계속 강제한다.08시 또는44/48h 목표를 넘을 것으로 보이는 의미 있는 변화는 남은 범위·예상시각·예상비용과 함께 조기에 알리되 시간만으로 중단하지 않는다.

## 13:30 안전 대기와17:30 재개

새 dispatcher의 admission은13:30~17:30에 새 case·주입·준비 mutation을 발행하지 않는다. 직전 case는 H/필수 stream/증거·소유 cleanup까지 완료하고 worker auto/1과 무잔존 상태에서 대기한다. case 경계에서 다음 case가13:30까지 끝날 것으로 보수적으로 예상되지 않으면 더 일찍 대기한다. 계산은 `max(등록 nominal, 관측 최대 case시간)×1.2+10분`이며 예상과 상한을 구분한다. 이미 시작한 관측이 지연돼도 강제 중단하거나H를 줄이지 않고 안전 완료 후 실제 대기 시각·차이를 알린다.

대기 중에는 필요한 안전 확인과 가동/비용 원장 갱신만 수행한다. 대기4시간과 경계에서 더 일찍 멈춘 실제 idle은 공유 bed-hours와 추정 비용에 포함한다.17:30 이후 동일 호스트에서 readiness·소유 상태·최종 예약·예산 gate를 확인하고 재개한다.10시간 수명 부족을 이유로 회전하지 않는다.

13시 점검은13:30 안전 대기 가능 여부·남은 준비로,15시는 실험 없이 안전 확인으로 대체한다.17:30 재개와19:30에는21시경 첫 main baseline/실제 주입 가능성을 재계산한다. 목표가 어려우면 필수 남은 단계·시간·선택지를 조기에 알린다. 중복 driver/자동화는 만들지 않는다.

## V5 무효 보존과 최소 수집 보완

V5 첫 S1 P는 fault/safety/cleanup=true이고 image 불변성도 통과했다. monotonic 경과는1200.006969초지만 UTC 경과는1199.979661초였으며, 기존 독립 판정은 `early_observation_end`로 무효다. 모든 raw·SHA·판정은 보존하고 소급 통과시키지 않는다. 벽시계 slew와 monotonic clock의 차이가 유일한 실패 원인이며 정책의 회복 성공/실패로 분류하지 않는다.

후속 source의 `horizon()`은 등록한H를 monotonic과 UTC 양쪽에서 충족할 때까지 기다린다. UTC 끝 시각은 실제 injection_applied의 원본 UTC에서 계산한다. H/분석기/.001초 허용값·요청 분모를 바꾸지 않고 미래 관측만 필요한 만큼 더 기다린다. 정상 측정 여섯 source·app/probe digest·정책 값·SLO·부하는 유지하므로 완료한 정상3+2와 실제 A DEV를 반복하지 않는다. 유효 pilot은 아직 없으므로 새 운영 source/profile에서 전체8개를 검증한다. V4 image 실패1개·V5 시간 무효1개는 그8개나main29개에 합치지 않는다.

아직 실행하지 않은 S2의 Python은 동일b658 digest, S3의 기존 postgres:16.10-alpine과 S4의busybox:1.37.0은 기존 태그의 현재 공개 registry digest로 고정한다. source/대상 캐시 차이의 사전 차단이며 아직 보지 않은 S2~S4 결과에 맞춘 조정이 아니다. workload 코드·정책·조건을 바꾸지 않고 각 새 pilot에서 실제 imageID를 확인한다. 원본 manifest는 `unrun-image-pin-registry.json`에 남기고 실제 image pull은 case 준비에서만 수행한다.

## 실측 운영 예상과 예약의 구분

성공한 native ensure는283.66/309.18/315.96/336.77초, down은345.01/346.69/349.22/351.27초였다. 실패한ensure141.75초는 성공 시간으로 넣지 않고 과거 원장 비용에 유지한다.10시간 회전 제거 후 계획 host lifecycle은 현재 정상ensure1회+최종down1회다. 여기에 `1.2×(최대 성공ensure+최대down)+600초`를5분 단위로 올린 **25분 운영 예상**을 둔다. 시나리오/논리session마다50분을 중복 예약하지 않는다. 단계 상한·3시간 case 예약은 그대로이며25분은 그 상한을 대체하지 않는다.

후속 case nominal S1/V1 45분·S2 38분·S3 35분·S4 25분과 관측최대×1.2 중 큰 값을 사용한다. 완료/경과분을 한 번만 차감하고, 대기·실제 재개시각과 가동/비용을 갱신한다. 부분 증거·일시 연결 오류는 기존 제한 재수집/cleanup-only 경로를 우선하며, mutation은 identity/소유권 readback 없이 재실행하지 않는다.
