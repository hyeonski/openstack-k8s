# 장애 주입 전 DNS 통신 장애 복구

계측 수정 cohort의 S2 P `attempt-01`은 2026-10-28 00:02:47 KST에 공통 worker 준비에서 실패했다. 새 worker의 DNS active probe가 실패했고, 원상 복구를 위한 worker 1대 정리 후에도 남은 worker의 DNS probe가 실패했다. S2 adapter와 장애 주입은 시작하지 않았다. 해당 attempt와 cleanup 실패 증거를 보존하고 후속 주입을 차단했다. 이 실패를 시간 계측 오류나 실험 조건의 미복구와 혼동하지 않는다.

동일 DNS 질의는 control-plane에서 성공했지만 worker에서는 kube-dns 서비스 IP 및 두 CoreDNS Pod IP 모두 시간 초과됐다. Calico BGP peering, PodCIDR route, IPIP 터널은 정상 상태였다. Nova/Neutron에서 현재 worker `e44c1008-6493-4487-a680-4a102e74fa61`, IP `10.6.0.235`, 포트 `999bfbda-ae18-4b3e-8ac4-8a6ff5afb109`의 소유·배치·보안그룹을 확인했다.

control-plane이 있는 `osk8s-compute01`의 Neutron hybrid 방화벽에서 IPIP 허용 규칙은 worker 보안그룹의 ipset `NIPv4803bc172-4953-464f-bd7f-`를 참조했으나 실제 멤버 수가 0이었다. 등록된 worker 포트가 있는데도 동적 주소 집합이 비어 있었던 것이 확인된 직접 차단 원인이다. 주소 집합이 비게 된 최초 이벤트까지는 확정하지 않았다.

2026-10-28 00:13:34 KST에 기존 `neutron_openvswitch_agent` 하나를 재시작하여 등록 상태를 재동기화했다. 기존 SG 규칙·허용 범위·Calico 설정·workload·실험 source/profile은 변경하지 않았다. 이후 ipset에 `10.6.0.235`가 복원됐고, 같은 worker의 동일한 DNS 서비스 IP 및 두 직접 Pod IP 질의가 모두 성공했다. 진단 Pod는 제한시간·명시 소유 라벨로 생성했고 UID를 확인해 증거 보존 후 제거한다.

증거는 `artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`의 `dns-*`, `repair-dns-*-final.*`에 보존한다. 원래 실패 attempt는 소유 정리만 재개해 무효 결과로 봉인하며 소급 통과시키지 않는다. 이후 허용된 최대 2 attempt와 첫 attempt 보존 정책에 따라 장애 주입 전 실패에 대한 재시도를 명시적으로 기록한다. main은 여전히 각 case의 첫 attempt만 주 분석에 포함한다. 새 준비 cohort를 성공할 때까지 반복하거나 기존 4건을 다른 source의 유효성 증거로 복사하지 않는다.
