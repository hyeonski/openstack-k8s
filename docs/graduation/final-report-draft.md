# 요약

OpenStack VM 위에서 Kubernetes를 운영하는 환경에서는 서비스 장애의 원인과 조치 수단이 서로 다른 관리 계층에 나뉘어 있어, 한 계층의 정보만으로는 적절한 대응을 결정하기 어렵다. 본 작품은 두 계층의 자원 관계를 연결하여 대표 장애 네 가지에 대응하는 모듈을 설계·구현하고 비교 실험으로 검증하였다. Google Cloud 호스트 3대 위에 중첩 가상화로 OpenStack 2025.2와 Kubernetes 1.35.7을 코드로 구축하고 Cluster API와 Cluster Autoscaler를 연동하였다. 대응 모듈은 자원 관계 확인, 조치 조건 판단, 대상 조치, 결과 확인의 네 단계로 동작하며, 외부 요청 원자료로 결과를 독립 판정하는 평가 도구를 함께 구현하였다. 평가 규모는 11개 조건, 총 33회다. 호스트 CPU 경합에서 재배치 후 SLO(Service Level Objective) 위반율은 0.08~0.14%였고, 무조치는 2.44~2.63%, 동일 노드 재시작은 2.24~3.54%였다. 공유 송신 경로 혼잡에서는 작업 분리와 Neutron QoS(Quality of Service)를 적용한 4회 모두 조치 후 위반율이 0%였으며, 작업 분리 단독은 2.63~3.02%였고 업로드 처리량은 약 66% 감소하였다. 노드 통신 단절에서는 fencing 확인 후 3회 모두 데이터베이스가 회복되고 커밋된 1,000건이 보존되었다. worker 노드 VM 정지에서는 서비스가 약 73~81초 중단된 뒤 남은 노드에서 회복되었고, MachineHealthCheck가 정지 요청 후 283~298초에 노드 용량을 3회 모두 복원하였다. 본 작품은 계층 간 자원 연결과 안전한 조치 순서를 구현하고, 서비스·데이터·용량의 회복을 구분하여 관측한 사례 연구다.

# 1. 서론

## 1.1 제안 배경 및 필요성

사설 클라우드에서는 OpenStack이 제공하는 VM 위에 Kubernetes 클러스터를 구성하여 컨테이너 서비스를 운영할 수 있다. OpenStack은 VM의 생성과 삭제, 네트워크 연결, 영구 저장소의 제공을 담당한다. Kubernetes는 그 VM을 Node로 사용하여 애플리케이션의 배치와 실행 상태를 관리한다. 이러한 구성은 인프라 자원 관리와 애플리케이션 배포 관리를 나누어 수행하게 한다. 서비스 개발자는 컨테이너와 Pod를 중심으로 실행 환경을 표현하고, 인프라 운영자는 호스트와 VM을 중심으로 자원을 배분한다. 본 작품은 이와 같이 역할이 나뉜 환경에서 장애 대응에 필요한 정보를 연결하는 문제를 다룬다. 정상 운용을 위한 역할 분리는 장애 대응에서도 각 계층이 제공하는 기능을 활용할 수 있는 기반이 된다. 동시에 서비스의 실행 위치와 하위 자원의 상태를 함께 확인해야 할 필요를 만든다.

두 관리 계층은 같은 서비스를 서로 다른 자원 단위로 관측한다. Kubernetes가 보는 대상은 Pod와 Node이며, 서비스가 어느 Node에 배치되어 있는지를 확인할 수 있다. OpenStack은 VM이 놓인 compute 호스트와 해당 VM의 Neutron port, Cinder volume을 관리한다. 하나의 Pod에 요청 지연이 발생해도 원인은 같은 호스트를 쓰는 다른 VM이나 공유 네트워크 경로에 있을 수 있다. 이때 서비스 상태를 읽는 위치와 원인을 확인하는 위치가 달라진다. 조치 수단도 원인에 따라 달라진다. 배치를 바꾸는 조치는 Kubernetes에서 수행하고, port의 대역폭 제한이나 VM 정지는 OpenStack에서 수행한다. 따라서 본 작품은 서비스에서 시작한 자원 조회가 실제 제어 대상까지 이어지도록 구성한다. 자원 사이의 관계를 명확히 기록하면, 관측한 상태가 어느 서비스와 어느 VM에 해당하는지 같은 실행 안에서 대조할 수 있다.

시나리오 1은 호스트 CPU 경합이다. 같은 compute 호스트에 있는 다른 VM이 CPU를 많이 사용하면 서비스 Pod가 정상 실행 중이어도 API 응답이 느려질 수 있다. 이 경우 Pod의 실행 상태와 서비스의 응답 품질은 서로 다른 결과를 나타낸다. Kubernetes에서 확인한 Node 정보만으로는 그 Node의 VM과 경쟁 VM이 같은 호스트에 있는지를 직접 알기 어렵다. 동일 노드에서 Pod를 다시 시작하면 서비스 프로세스는 새로 만들어지지만 하위 호스트의 경합 관계는 유지된다. 본 작품은 서비스 지연과 호스트 경합을 함께 확인한 뒤 다른 compute 호스트의 worker 노드로 Pod를 옮기는 절차를 대상으로 삼는다. 목적지의 여유도 함께 확인해야 이동 이후의 서비스가 안정적으로 실행될 수 있다. 이 시나리오는 프로세스의 재시작과 실행 위치의 변경이 서로 다른 조치라는 점을 비교하기에 적합하다.

시나리오 2는 공유 송신 경로 혼잡이다. API 서비스와 대용량 업로드 작업이 같은 송신 경로를 사용하면 업로드 트래픽의 증가가 API 응답 지연으로 이어질 수 있다. 두 작업을 다른 worker 노드에 배치해도 공통 출구를 계속 사용하면 네트워크 경합이 남을 수 있다. Kubernetes의 배치 변경은 실행 위치를 바꾸는 수단이고, Neutron QoS는 VM의 port에 대역폭 제한을 적용하는 수단이다. 두 작업이 같은 port를 사용하는 상태에서 제한을 걸면 API 트래픽까지 같은 제한을 받는다. 본 작품은 업로드 작업을 별도 worker 노드의 port로 연결한 뒤 그 port를 제어하는 구성을 사용한다. 이 구성에서는 API의 응답 품질과 업로드의 진행을 함께 확인해야 한다. API 응답이 빨라졌다는 사실과 두 작업이 함께 지속되고 있다는 사실을 구분하기 위해 업로드 처리량을 결과에 포함한다.

시나리오 3은 노드 통신 단절과 데이터베이스 복구다. Kubernetes에서 Node가 NotReady로 표시되어도 해당 VM과 그 위의 데이터베이스 프로세스는 계속 실행 중일 수 있다. 통신 상태는 원격에서 응답을 확인할 수 있는지를 나타내며, 프로세스의 실행 종료는 별도의 상태다. 이전 프로세스가 멈췄는지 확인하기 전에 같은 volume을 다른 노드에서 사용하면 두 실행 주체가 같은 데이터에 쓰는 위험이 생긴다. Kubernetes의 out-of-service taint를 사용하는 복구도 노드가 실제로 꺼졌는지를 먼저 확인하는 순서를 전제로 한다. 본 작품은 Nova를 통한 fencing 요청과 실제 종료 확인을 구분한다. 종료가 확인된 뒤에만 Kubernetes의 Pod 정리와 volume 재연결 절차를 진행한다. 이 시나리오의 완료에는 새로운 데이터베이스의 접속 성공과 장애 전에 커밋된 데이터의 보존이 함께 포함된다.

시나리오 4는 worker 노드 VM 정지다. worker 노드 VM이 멈추면 Kubernetes는 남은 노드에서 Pod를 다시 실행하여 서비스를 회복시킨다. 서비스는 Kubernetes가 회복시키지만, 노드 용량은 인프라 계층의 VM 교체 없이는 돌아오지 않는다. 서비스가 다시 응답하더라도 클러스터에는 worker 노드가 한 대 줄어든 상태가 남는다. 이는 다음 장애나 새로운 작업을 받아낼 실행 여유의 감소를 뜻한다. 목표 용량을 되돌리려면 대체 VM을 만들고 Kubernetes 클러스터에 합류시켜야 한다. 본 작품은 Cluster API, Cluster API Provider OpenStack, MachineHealthCheck를 연결하여 이 과정을 관찰한다. 서비스가 남은 노드에서 회복되는 경로와 새로운 worker 노드가 준비되는 경로를 따로 기록한다. 이를 통해 같은 장애에 대해 서비스의 회복과 클러스터 용량의 복원이 서로 다른 완료 조건을 갖는다는 점을 확인한다.

이들 시나리오에 대응하려면 서비스 상태와 인프라 상태를 같은 자원 관계 위에서 읽어야 한다. 본 작품은 조치 대상의 식별자를 확인하고 안전 조건이 충족된 뒤 정해진 순서로 조치하도록 설계한다. 조치 이후에는 서비스 요청, 데이터, 노드 용량 가운데 해당 시나리오에 필요한 결과를 확인한다. 이러한 구조는 관측과 조치를 하나의 절차로 연결하면서도 각 단계의 성공 근거를 따로 남긴다. 예를 들어 VM 정지 요청의 접수는 fencing 완료 확인과 분리하여 기록하고, Pod의 준비 상태는 외부 요청의 회복과 함께 검토한다. 그 결과 어떤 단계에서 문제가 남았는지를 실행 기록으로 추적할 수 있다. 본 작품은 재시작, 재스케줄링, toleration, MachineHealthCheck와 같은 기존 기능을 비교 조건에 포함한다. 기존 기능만으로 서비스나 용량 문제가 남는지는 다음 절의 목표에 따라 실험으로 확인한다.

## 1.2 연구논문/작품의 목표

본 작품의 목표는 세 가지다. 첫째, OpenStack과 Kubernetes를 함께 사용하는 테스트베드를 코드로 구축한다. 클라우드 호스트의 선언에서 서비스 실행 환경까지 필요한 단계를 연결하고, 각 단계의 상태를 확인할 수 있게 한다. 둘째, 네 가지 장애에 대한 대응 모듈을 공통된 네 단계 구조로 구현한다. 자원 관계 확인, 조치 조건 판단, 대상 조치, 결과 확인을 같은 틀로 배치하되, 각 장애가 요구하는 조건과 제어 수단을 구체화한다. 셋째, 비교 조건을 둔 실험으로 조치의 효과를 확인한다. 대응 모듈이 남긴 성공 표시와 별도로 외부 요청 원자료를 평가하여 결과를 판단한다. 환경과 설정을 기록해야 같은 조건에서 조치를 비교할 수 있고, 독립적인 판정이 있어야 구현의 완료와 서비스의 회복을 각각 확인할 수 있다.

평가는 필요성, 계층 간 정보의 기여, 조치 기전, 복구 효과, 안전성의 다섯 연구 질문에 답하도록 설계하였다. 필요성은 기존 기능만으로 서비스나 용량 문제가 남는지를 묻는다. 계층 간 정보의 기여는 두 계층의 정보를 연결하는 과정이 판단과 대상 지정에서 어떤 역할을 하는지를 묻는다. 조치 기전은 구현된 절차 가운데 어떤 조치가 관측된 차이와 연결되는지를 검토한다. 복구 효과는 서비스의 응답뿐 아니라 데이터와 실행 용량까지 포함한다. 안전성은 조치 조건이 부족할 때의 보류와 실행 이후의 원상 복원을 다룬다. 이 질문들은 하나의 성공 여부로 합치기보다 서로 다른 근거로 평가할 필요가 있다. 서비스가 회복된 결과는 효과에 관한 근거이고, 실행 중인 VM에 대해 복구를 보류한 결과는 안전 순서에 관한 근거다. 본 작품은 각 질문에 대응하는 관측을 결과표와 분석에서 구분하여 제시한다.

본 작품은 사전에 정의한 네 가지 장애를 대상으로 하며, 임의의 장애를 자동으로 분류하는 기능은 범위에 포함하지 않는다. 표 1-1은 각 장애의 발생 조건, 서비스 영향, 대응 조치와 작품 내 역할을 정리한 것이다. 호스트 CPU 경합과 공유 송신 경로 혼잡은 서비스의 응답 품질 저하를 중심으로 구성한다. 노드 통신 단절은 단일 데이터베이스의 실행 종료와 같은 volume의 재사용 순서를 중심으로 구성한다. worker 노드 VM 정지는 기존 제어기가 수행하는 노드 교체를 통합하는 사례로 구성한다. 각 시나리오는 영향을 받는 자원과 조치의 완료 조건이 분명하다. 이 구분에 따라 직접 구현한 판단·순서 제어와 기반 플랫폼이 제공하는 기능의 역할을 정리한다.

[표 1-1] 대상 장애 시나리오

| 시나리오 | 장애 | 서비스 영향 | 대응 조치 | 작품 내 역할 |
|---|---|---|---|---|
| 1. 호스트 CPU 경합 | 같은 compute 호스트의 다른 VM이 CPU를 과다 사용 | API 응답 지연 | 다른 compute 호스트의 worker 노드로 API Pod 재배치 | 직접 구현 |
| 2. 공유 송신 경로 혼잡 | API와 업로드가 같은 송신 경로를 공유 | API 응답 지연 | 업로드를 다른 worker 노드로 분리하고 그 port에 Neutron QoS 적용 | 직접 구현 |
| 3. 노드 통신 단절과 데이터베이스 복구 | worker 노드의 제어 통신과 DB 접속 경로 단절 | DB 접근 실패 | 기존 VM의 fencing 확인 → out-of-service taint → 같은 볼륨으로 DB 재기동 | 직접 구현 |
| 4. worker 노드 VM 정지 | worker 노드 VM 한 대 정지 | 일시적 요청 실패, 노드 용량 감소 | MachineHealthCheck 기반 Machine 교체와 용량 회복 확인 | 기존 기능 통합 |

## 1.3 전체 개관과 결과 미리보기

테스트베드는 Google Cloud의 controller 호스트 1대와 compute 호스트 2대 위에 OpenStack을 배포한 구조다. 그 위의 VM으로 Kubernetes control plane 노드와 worker 노드를 구성한다. controller 호스트는 OpenStack 제어 서비스와 클러스터를 관리하는 management 클러스터를 제공한다. compute 호스트는 workload 클러스터의 VM과 장애 재현에 필요한 경쟁 VM을 실행한다. 그림 1-1과 같이 대응 모듈과 평가 도구는 운영 클라이언트에서 두 관리 계층의 상태를 읽고 조치를 요청한다. 접근에는 IAP(Identity-Aware Proxy)를 사용한다. 하나의 서비스에서 출발하여 Pod, Node, VM과 그 하위 자원을 따라가도록 관계를 구성한다. 이 구조는 요청 품질의 변화와 인프라 조치의 대상을 같은 실행 기록으로 연결한다. 구체적인 사양과 식별자 연결 방식은 3장에서 설명한다.

> [그림 1-1 자리] 구성 요소: 아래층에 Google Cloud 호스트 3대, 가운데층에 OpenStack 서비스와 control plane 노드 VM 1대·worker 노드 VM 2대, 위층에 Kubernetes 서비스를 배치한다. 오른쪽의 대응 모듈·평가 도구에서 Kubernetes와 OpenStack 각각으로 상태 읽기와 조치 화살표를 연결한다.

[그림 1-1] 전체 구성 개요

본 작품은 2026년 7월 말 로컬 테스트베드 구축으로 시작하였다. 저장소의 첫 커밋은 7월 28일이다. 8월 24일의 설계 결정에 따라 8월 말부터 Google Cloud를 단일 실행 환경으로 사용하였다. 9월에는 worker 노드의 자동 증감과 네 가지 장애 대응 절차를 구현하였다. 10월 초에 1차 평가를 마친 뒤, 10월 26일에는 비교 조건과 사건 시각의 정의를 검토하여 평가를 새로 설계하였다. 이에 따라 10월 27~29일에 비교 평가를 수행하였다. 본 보고서의 결과 분석은 마지막 평가에서 정리된 조건과 수치를 기준으로 한다.

실험 결과는 표 1-2와 같이 서비스 품질, 데이터 보존, 용량 복원으로 나누어 정리하였다. 시나리오 1에서 다른 compute 호스트로 재배치한 조건의 조치 후 SLO 위반율은 0.08~0.14%였다. 무조치와 동일 노드 재시작 조건에는 더 높은 위반율이 남았다. 시나리오 2의 제안 방식은 4회 모두 조치 이후의 위반율이 0%였다. 시나리오 3에서는 fencing 확인을 앞세운 복구 뒤 1,000건의 커밋 데이터가 보존되었다. 시나리오 4에서는 두 조건 모두 서비스가 약 73~81초 중단된 뒤 회복되었고, MachineHealthCheck 사용 조건에서만 노드 용량까지 복원되었다. 시나리오 2에서는 작업 분리 단독으로 API 보호 효과가 나타나지 않았으며, Neutron QoS를 포함한 조치에는 업로드 처리량 감소라는 대가가 있었다.

[표 1-2] 시나리오별 핵심 결과

| 시나리오 | 제안 방식 | 비교 조건 | 핵심 차이 |
|---|---|---|---|
| 1 | 조치 후 SLO 위반율 0.08~0.14% | 무조치 2.44~2.63%, 동일 노드 재시작 2.24~3.54% | 재배치만 기준선 수준으로 회복 |
| 2 | 조치 후 위반율 0% (4/4) | 작업 분리 단독 2.63~3.02%, 무조치 1.72~2.34% | Neutron QoS가 필요. 업로드 처리량 약 66% 감소 |
| 3 | 3/3 회복, 1,000건 보존 | 무조치 0/3 (관측 구간 동안 요청 전부 실패) | fencing 확인 후 같은 볼륨으로 재기동 |
| 4 | 용량 복원 3/3 (정지 요청 후 283~298초) | MachineHealthCheck 미사용: 용량 복원 0/3 | 서비스는 두 조건 모두 약 73~81초 중단 후 회복 |

## 1.4 보고서 구성

본 보고서의 구성은 다음과 같다. 2장은 통합 관측, 계층 간 장애 정보 전달, 자원 경합과 네트워크 제어, 상태 저장 서비스 복구, 서비스 수준의 결과 검증이라는 다섯 관점에서 관련연구를 검토한다. 연구별 관측 대상과 조치 주체를 비교하여 본 작품의 위치를 정리한다. 3장은 기반 기술의 동작 원리와 테스트베드 구성을 제시한다. 이어 구축·운영 설계의 원칙과 공통 대응 구조를 설명하고, 각 시나리오의 판단 기준과 조치 순서를 구체화한다. 4장은 구현 결과, 측정 조건, 비교 실험의 결과를 제시한다. 결과표에 나타난 관측을 연구 질문과 연결하고, 판정 지표의 의미와 타당성 위협을 검토한다. 5장은 목표의 달성과 기여를 정리하고 후속 연구를 제시한다. 소감에는 작품을 진행하며 겪은 경험과 배운 점을 적는다. 부록에는 핵심 원천코드와 전체 회차별 결과표를 수록하여 본문의 설명을 구현 및 측정 결과와 대조할 수 있게 한다.

# 2. 관련연구

본 장은 OpenStack 위에서 Kubernetes 서비스를 운영할 때 여러 계층의 정보를 연결해 장애에 대응하는 과정을 다섯 관점에서 검토한다. 검토 대상은 통합 관측, 계층 간 장애 정보 전달, 자원 경합과 네트워크 제어, 상태 저장 서비스의 복구, 서비스 수준의 결과 검증이다. 각 연구에서 관측하는 대상과 실제 변경하는 자원을 구분하고, 장애 탐지, 자원 수리, 사용자 서비스의 회복이 어떤 결과로 평가되는지 살펴본다. 이러한 비교는 본 작품의 자원 관계 확인과 조치 순서가 선행연구의 어느 부분과 연결되는지를 정리하는 기준이 된다.

## 2.1 통합 관측과 장애 증거 연결

김지용 등은 OpenStack 환경에서 서비스 메시 기반의 통합 모니터링 시스템을 제안하였다[1]. 이 시스템은 서비스 메시가 제공하는 마이크로서비스 관측 정보에 기반 인프라의 메트릭을 함께 수집하고 시각화하였다[1]. 이를 통해 운영자가 개별 서비스뿐 아니라 시스템 전반의 상태를 확인할 수 있게 하였다[1]. 이 연구에서 중요한 관점은 서비스 계층의 정보와 하위 실행 환경의 정보를 함께 제공한다는 점이다. 서비스 요청의 이상과 인프라 상태를 같은 맥락에서 살펴보면 문제 발생 당시의 실행 환경을 더 넓게 파악할 수 있다. 해당 연구의 조치 단위는 자동 복구 명령보다 관측과 시각화에 놓여 있으며[1], 이 점에서 본 작품이 자원 관계를 따라 장애 근거를 모으는 과정과 관련된다.

박주원 등은 OpenStack의 시스템 및 응용 서비스 이벤트 로그를 메시지 기준으로 군집화하고 그룹 사이의 연관성을 분석하였다[2]. 시간적으로 어긋난 패턴의 비교에는 DTW(Dynamic Time Warping)를 사용하였다[2]. MicroRCA와 Sage도 관측 정보를 이용하여 성능 문제의 원인이 되는 서비스를 추정하였다[3][4]. 이들 연구는 흩어진 관측을 연결하여 문제의 위치를 파악한다는 공통점을 갖는다[2][3][4]. 관측 항목의 수집과 원인 추정은 장애 대응에서 조치를 선택하기 위한 근거를 제공한다. 본 작품은 providerID와 VM·port·volume 식별자를 이용하여 자원 관계를 명시적으로 연결하고, 장애 시점에 읽은 정보가 실제로 변경할 자원과 일치하는지를 확인하는 데 초점을 둔다.

## 2.2 계층 간 장애 정보 전달

Yang과 Kim은 컨테이너 서비스를 위한 클라우드 인프라에서 Fast Fault Detection Manager를 설계하였다[5]. OpenStack의 Ceilometer와 Aodh가 감지한 VM 장애를 Kubernetes로 전달하여 Node의 상태가 변경되도록 구성하였다[5]. 평가는 장애 발생 이후 Kubernetes의 관리 계층이 장애 정보를 받기까지의 탐지 시간을 중심으로 수행하였다[5]. VM 계층의 관측이 컨테이너 계층의 복구 흐름으로 이어진다는 점에서 본 작품과 가장 가까운 선행연구다. 장애 정보가 관리 계층 사이를 이동하도록 연결하면 상위 계층의 상태 인식에 하위 계층의 증거를 반영할 수 있다[5].

OpenStack Masakari는 VM과 compute 호스트의 장애에 대응하는 고가용성 기능을 제공한다[6]. 공식 문서는 VM 프로세스 장애 시 Nova의 정지·시작 기능으로 VM을 다시 시작하고, compute 호스트 장애 시 Nova evacuation을 사용한다고 설명한다[6]. 조치 단위는 VM이며 인프라 수준에서 실행 가능한 상태를 회복하는 흐름이다[6]. VM 수준의 복구는 그 위에서 실행되는 서비스가 다시 동작할 기반을 마련한다. Yang과 Kim의 연구와 Masakari는 각각 장애 정보의 전달과 VM 수준의 복구를 중심으로 한다[5][6]. 본 작품은 이 흐름 이후의 서비스 요청, 데이터 보존, 클러스터 용량을 외부 관측과 자원 상태로 확인하는 데까지 검토 범위를 넓힌다.

## 2.3 자원 경합과 서비스 목표를 고려한 제어

Delimitrou와 Kozyrakis의 Paragon은 서버의 이질성과 함께 배치된 작업 사이의 간섭을 고려하는 스케줄러다[7]. 이전 작업에 대한 정보를 활용하여 새로운 작업의 특성을 분류하고, 공유 자원에서의 간섭을 줄이는 방향으로 배치를 결정한다[7]. 이 접근은 작업이 어느 서버에서 실행되는지가 성능에 영향을 준다는 문제를 다루며[7], 서로 다른 실행 단위가 하위 자원을 공유하는 상황을 살피는 관점을 제공한다. 본 작품의 호스트 CPU 경합 시나리오도 VM 내부의 서비스와 같은 호스트의 다른 VM 사이에 존재하는 자원 공유 관계를 대상으로 한다.

Qiu 등의 FIRM은 마이크로서비스의 SLO 위반에 대응하는 자원 관리 프레임워크다[8]. 온라인 관측 정보와 기계학습으로 문제가 있는 마이크로서비스 및 경합 자원을 식별하고[8], 동적인 자원 재할당으로 서비스 목표 위반을 완화한다[8]. FIRM은 서비스의 응답 품질을 하위 자원 상태와 제어 조치에 연결한다는 점에서 관련된다[8]. Paragon과 FIRM은 배치 또는 자원 할당의 결정 방식을 제안한다[7][8]. 본 작품은 이미 호스트 경합이 발생한 상황에서 OpenStack의 compute 호스트 정보를 확인하고 Kubernetes의 배치를 변경하는 절차를 시나리오 1로 구현하였다. 구현한 절차의 효과는 재배치와 동일 노드 재시작의 관측 결과를 통해 검토한다.

## 2.4 네트워크 성능 제어와 작업 배치의 결합

변지섭 등은 엣지 컴퓨팅 환경에서 Kubernetes 기반 네트워크 성능 제어 방식의 실측 특성을 분석하였다[9]. 이 연구는 설정한 성능 수준에 도달하기까지 시간이 걸리거나 목표 성능을 충분히 달성하지 못하는 사례를 보고하였다[9]. 이러한 결과는 네트워크 제어의 설정값과 실제 트래픽의 동작을 구분하여 확인해야 함을 보여 준다[9]. 제어 규칙이 존재한다는 사실과 서비스가 목표 성능을 얻었다는 사실은 서로 다른 관측 대상이다. 해당 연구는 네트워크 제어를 평가할 때 설정의 확인에 더하여 서비스가 경험한 성능을 관찰하는 근거를 제공한다[9].

설정과 실측을 함께 검토하는 관점은 공유 송신 경로의 여러 작업을 다룰 때에도 적용된다. 하나의 제어 규칙이 어느 트래픽에 적용되는지에 따라 API와 업로드가 받는 영향이 달라지기 때문이다. 변지섭 등의 연구에서 나타난 목표 성능과 관측 성능의 차이는 제어 적용 이후의 결과 확인이 필요함을 뒷받침한다[9]. 본 작품의 시나리오 2는 Neutron QoS가 Open vSwitch 인터페이스에 설치되었는지 확인하고, 이와 함께 API 지연과 업로드 처리량을 관측한다. 정책 설치, API 응답 품질, 업로드 진행을 나누어 읽음으로써 제어 설정과 서비스 결과를 연결한다.

## 2.5 상태 저장 서비스의 가용성과 복구 순서

Vayghan 등은 상태 저장 마이크로서비스의 가용성을 관리하기 위한 HA(High Availability) State Controller를 제안하였다[10]. 이 구조는 애플리케이션의 상태 복제와 정상 인스턴스로의 전환을 결합한다[10]. 이 연구는 반응 시간, 수리 시간, 서비스 회복 시간, 전체 중단 시간을 구분하였다[10]. 관리 대상의 수리와 사용자에게 서비스를 다시 제공하는 사건을 따로 측정하는 점이 중요하다[10]. 이러한 구분은 상태 저장 서비스에서 새 Pod의 기동과 데이터 접근의 회복을 각각 확인하는 관점으로 이어진다.

Fence Agents Remediation은 fence agent를 사용하여 비정상 노드를 fencing하고 복구하는 Kubernetes operator다[11]. 공식 문서의 복구 과정에는 비정상 노드의 재부팅과 해당 노드 작업의 축출이 포함된다[11]. 이전 실행 주체의 동작을 끊는 절차는 상태 저장 작업을 다른 노드에서 시작하기 위한 안전 조건과 연결된다. Vayghan 등의 상태 복제와 정상 인스턴스 전환은 서비스 가용성을 유지하는 방식이고[10], fencing은 이전 실행 주체의 상태를 제어하는 방식이다[11]. 본 작품의 시나리오 3은 단일 PostgreSQL과 같은 Cinder volume을 사용한다. fencing을 확인한 뒤 그 volume을 다른 노드에서 다시 사용하도록 순서를 구성하고, 커밋 데이터의 보존과 새 요청의 수행을 확인한다.

## 2.6 probe와 사용자 관점의 회복 검증

Flora 등은 TeaStore와 SockShop에 부하와 결함을 주입하여 Kubernetes probe의 장애 감지 효과를 평가하였다[12]. 실험에서는 probe가 감지하지 못한 응용 실패가 관찰되었다[12]. 건강 검사 엔드포인트의 구현과 매개변수 설정이 감지 동작에 미치는 영향도 분석하였다[12]. 이 연구는 관리 계층에 표시되는 컨테이너 상태와 실제 응용 동작을 함께 확인해야 한다는 관점을 제공한다[12]. probe의 응답은 해당 검사 경로에 관한 관측이며, 사용자 요청의 성공과 지연은 서비스 사용 경로에 관한 관측이다. 두 종류의 관측을 함께 살피면 상태 표시가 정상인 동안에도 남아 있는 서비스 문제를 구분할 수 있다.

Basiri 등의 카오스 엔지니어링은 장애를 주입하여 분산 시스템의 실제 동작을 실험적으로 확인하는 접근이다[13]. 복잡한 시스템의 장애 대응을 가정에만 의존하지 않고 실행 결과로 검토한다는 데 의미가 있다[13]. 이 관점에서 장애 주입은 서비스가 어떤 영향을 받으며 대응 이후 어떤 상태에 도달하는지를 관찰하기 위한 수단이 된다[13]. Flora 등의 probe 평가도 결함을 주입하고 응용 실패를 함께 살폈다는 점에서 같은 실증적 관점과 연결된다[12]. 본 작품은 외부 측정기가 보낸 요청의 성공 여부와 지연으로 회복을 판정하여, Pod Ready와 사용자 관점의 응답 품질을 함께 읽는 평가 구조를 구성하였다.

## 2.7 선행연구와 본 작품의 관계

표 2-1은 선행연구를 관측 계층, 조치 주체와 단위, 상태 저장 서비스 고려, 서비스 수준 결과 검증의 네 기준으로 정리한 것이다. 통합 관측과 로그 분석은 장애 근거를 연결한다[1][2]. 계층 간 정보 전달은 VM의 장애를 Kubernetes의 상태 인식에 반영한다[5]. 배치 및 자원 제어 연구는 서비스 목표와 하위 자원 할당을 연결한다[7][8]. 상태 저장 서비스의 가용성 연구는 데이터와 실행 주체의 관계를 다루며[10], probe 평가와 카오스 엔지니어링은 실제 서비스 동작의 확인을 강조한다[12][13]. 표의 서비스 수준 결과 검증은 각 문헌에서 다룬 평가 범위를 기준으로 읽는다.

[표 2-1] 선행연구와 본 작품의 비교

| 연구 | 관측 계층 | 조치 주체·단위 | 상태 저장 서비스 고려 | 서비스 수준 결과 검증 | 관련 시나리오 |
|---|---|---|---|---|---|
| 김지용 등 [1] | 서비스 메시, 인프라 메트릭 | 없음 (관측·시각화) | 없음 | 관측만 | 공통 |
| 박주원 등 [2] | OpenStack 시스템·응용 로그 | 없음 (원인 분석) | 없음 | 없음 | 공통 |
| Yang과 Kim [5] | VM 상태 → Kubernetes | Kubernetes Node 상태 변경 | 없음 | 없음 (탐지 시간) | 3, 4 |
| Masakari [6] | VM, 호스트 | VM 재시작·이동 | VM 수준 | 없음 (VM 상태 기준) | 3, 4 |
| Paragon [7] | 서버, 작업 간 간섭 | 스케줄러 배치 | 없음 | 있음 (QoS) | 1 |
| FIRM [8] | 마이크로서비스 추적, 자원 | 자원 재할당 | 없음 | 있음 (SLO) | 1, 2 |
| 변지섭 등 [9] | 컨테이너 네트워크 | Kubernetes 네트워크 제어 | 없음 | 일부 (처리량 실측) | 2 |
| Vayghan 등 [10] | 애플리케이션 상태 | Kubernetes 컨트롤러 (복제·전환) | 있음 | 있음 | 3 |
| Flora 등 [12] | probe, 응용 동작 | 없음 (평가 연구) | 없음 | 있음 | 공통 |
| **본 작품** | Pod·Node·VM·compute 호스트·port·volume | Kubernetes 배치, Neutron QoS, Nova 정지, Cluster API | 있음 | 있음 (외부 요청 원자료) | 1~4 |

본 작품은 이들 관점을 세 가지 구현 원칙으로 연결한다. 첫째, 두 계층의 자원을 providerID와 각 자원의 식별자로 연결하여 조치 대상을 확인한다. 둘째, fencing 확인, 자원 소유 확인, 동시 변경 감지와 같은 안전 조건을 조치 순서에 포함한다. 셋째, 서비스·데이터·용량의 결과를 외부 측정 원자료로 독립 판정한다. 자원 연결은 관측 대상과 제어 대상의 일치를 확인하고, 안전 조건은 다음 단계로 진행할 수 있는지를 정하며, 독립 판정은 실행기가 완료되었다는 기록과 서비스가 회복되었다는 관측을 대조한다. 다음 장에서는 이 세 원칙이 테스트베드 운영과 시나리오별 알고리즘에 어떻게 반영되었는지를 설명한다.

# 3. 제안 작품 소개

## 3.1 이론적 배경

Nova는 VM의 생성과 실행 상태를 관리하며, 공유 CPU 정책에서는 여러 VM의 vCPU가 같은 호스트 CPU를 나누어 사용한다[14]. Nova의 정지 요청은 비동기로 처리되므로 요청의 접수와 VM의 실제 정지는 따로 확인해야 한다[15]. Neutron은 VM의 네트워크 연결을 port 단위로 관리하며, Neutron QoS의 bandwidth-limit 규칙은 지정한 port의 트래픽을 제한한다[16]. Cinder는 VM에 연결하는 영구 block volume을 제공한다.

Kubernetes는 Node의 Ready 조건에 따라 not-ready 또는 unreachable taint를 붙이고, Pod는 toleration 시간(기본 300초)이 지나면 축출된다[17]. 노드가 정상 종료 절차 없이 멈춘 경우에는 노드가 실제로 꺼졌음을 확인한 뒤 out-of-service taint를 붙여야 Pod 정리와 volume 분리가 진행된다[18]. 조건에 따라 6분 뒤 volume을 강제로 분리하는 동작도 있으나[18], 본 작품은 시나리오 3에서 이를 비활성화하여 fencing을 앞세운 순서를 유지하였다.

Cluster API는 클러스터의 노드를 Machine 객체로 선언하여 관리한다. MachineHealthCheck는 Node 조건과 그 지속 시간을 검사하여 비정상 Machine의 교체를 시작하며, skip-remediation 또는 paused annotation으로 교체를 막을 수 있다[19]. Cluster API Provider OpenStack은 Machine을 Nova VM으로 생성한다[20]. Cluster Autoscaler는 배치되지 못한 Pod의 자원 요청을 보고 worker 노드 수를 조정한다.

MAPE-K는 Monitor, Analyze, Plan, Execute의 순환과 공유 Knowledge로 자율 관리를 설명하는 모델이며[21], 본 작품의 공통 대응 구조는 이 순환에 대응한다(3.3절). PSI(Pressure Stall Information)는 작업이 CPU·메모리·I/O를 기다리며 멈춘 시간의 비율로[22], CPU 사용률만으로는 구분하기 어려운 경합을 판단하는 근거로 사용한다. PostgreSQL은 데이터 파일을 바꾸기 전에 변경 내용을 WAL(Write-Ahead Logging)에 기록한다[23]. 따라서 fsync, synchronous_commit, full_page_writes가 켜진 상태에서 커밋이 끝난 데이터는 같은 volume으로 다시 기동할 때 보존된다.

## 3.2 시스템 구성

테스트베드는 Google Cloud의 사용자 정의 VPC(Virtual Private Cloud) 안에 있는 호스트 3대로 구성된다(표 3-1). controller 호스트에는 OpenStack 제어 서비스와 kind 기반 management 클러스터를 두고, compute 호스트 2대에서는 KVM 중첩 가상화로 workload 클러스터의 VM을 실행한다. 운영 클라이언트는 IAP(Identity-Aware Proxy)로만 호스트에 접근하며, workload 클러스터의 API는 공개하지 않고 터널로 접근한다. compute 호스트 1은 재배치 목적지의 여유를 확보하려고 n2-standard-8로 구성하였다. 4 vCPU 목적지에서는 재배치 뒤에도 p95 지연이 회복 기준을 간헐적으로 넘었으며, 본 작품은 회복 임계값을 낮추는 대신 목적지 사양을 늘렸다.

[표 3-1] 테스트베드 구성

| 계층 | 구성 | 버전·사양 |
|---|---|---|
| Google Cloud 호스트 | controller 호스트 1대, compute 호스트 2대. 중첩 가상화(KVM), IAP 접근 | e2-standard-4 / n2-standard-8 / n2-standard-4 |
| OpenStack | Kolla-Ansible 배포. Nova, Neutron(QoS 추가), Cinder(LVM 추가), Keystone, Placement | 2025.2, Ubuntu |
| management 클러스터 | controller 호스트의 단일 노드 kind | kind 0.31.0, Kubernetes 1.35.0 |
| 클러스터 관리 | Cluster API(CABPK, KCP 포함), Cluster API Provider OpenStack, ORC, Cluster Autoscaler | 1.13.4 / 0.14.6 / 2.4.0 / 1.35.0 |
| workload 클러스터 | control plane 노드 1대(compute 호스트 1), worker 노드 1~3대 | Kubernetes 1.35.7, Calico 3.32.1. 노드당 2 vCPU, 2 GiB, 20 GB |
| 저장소 | Cinder CSI 드라이버, controller의 파일 기반 LVM | — |

그림 3-1은 호스트별 배치와 계층 간 자원 관계를 함께 나타낸다. Kubernetes Node와 Nova VM은 Node의 providerID(openstack:///VM 식별자)로 연결하고, Machine의 providerID도 함께 대조한다. VM과 Neutron port는 port의 device_id로, VM과 Cinder volume은 attachment의 server_id로 연결한다. 이름의 유사성이 아니라 식별자의 일치로 대상을 정하므로, 자원이 교체되거나 같은 이름의 객체가 새로 만들어진 경우를 구분할 수 있다.

> [그림 3-1 자리] 구성 요소: 기존 그림 3-1(호스트 3대와 각 호스트의 VM 배치)과 기존 그림 3-2(Service·Deployment·StatefulSet → Pod → Node → Machine → Nova VM → compute 호스트, Nova VM → Neutron port·Cinder volume, 연결선의 nodeName·providerID·device_id·attachment server_id)를 한 그림으로 합친다. 왼쪽에 호스트 배치, 오른쪽에 자원 관계를 둔다. 높이는 약 9cm 이내로 한다.

[그림 3-1] 테스트베드 구성과 계층 간 자원 관계

## 3.3 개념설계: 공통 대응 구조와 구축·운영 원칙

모든 대응 모듈은 자원 관계 확인, 조치 조건 판단, 대상 조치, 결과 확인의 네 단계로 동작한다(그림 3-2). 이는 MAPE-K의 Monitor, Analyze·Plan, Execute와 다음 순환의 Monitor·Knowledge 갱신에 대응한다. 판단 단계는 자원 사용률 하나로 장애를 선언하지 않고 서비스 영향과 자원 증거가 함께 지속될 때만 조치하며, 근거가 부족하거나 서로 맞지 않으면 보류 사유를 기록한다. 조치 단계는 변경 의도를 기록하고 조건부로 변경한 뒤 실제 적용을 다시 읽어 확인한다. 결과 확인은 한 번의 정상 응답이나 Pod Ready가 아니라 외부 요청이 연속 구간 동안 목표를 만족하는지로 판정하며, 시나리오에 따라 데이터와 노드 용량도 확인한다.

> [그림 3-2 자리] 구성 요소: 기존 그림 3-3(공통 4단계 대응 흐름, MAPE-K 병기, 순환 화살표)을 그대로 사용한다. 높이는 약 8cm 이내로 줄인다.

[그림 3-2] 공통 4단계 대응 흐름

구축과 운영 코드에는 표 3-2의 원칙을 공통으로 적용하였다. 이 원칙들은 대응 조치가 잘못된 대상이나 다른 실행이 만든 자원에 영향을 주지 않게 하고, 실패한 실행을 증거와 함께 남기기 위한 것이다.

[표 3-2] 구축·운영 설계 원칙

| 원칙 | 구현 방법 |
|---|---|
| 단계별 구축 | 클라우드 자원 선언(OpenTofu) → 호스트 준비(Ansible) → OpenStack 배포(Kolla-Ansible) → 노드 이미지 → management 클러스터와 Cluster API → workload 클러스터 → Cluster Autoscaler 순으로 진행하고 단계마다 검증한다. 검증된 이미지는 체크섬을 확인해 재사용한다 |
| 기록 우선 상태 관리 | 외부 자원을 바꾸기 전에 의도를 기록한다. 상태 파일은 임시 파일에 쓰고 fsync한 뒤 교체한다. 미완료 기록이 있으면 새 변경을 거부한다 |
| 식별자 기반 소유권 | 실행마다 고유 식별자를 만들고 생성한 자원에 label과 UID를 남긴다. 정리는 자기 소유 자원만 대상으로 한다. 호스트 ID나 클러스터 UID가 바뀌면 진행을 거부한다 |
| 배타 실행과 제어권 전환 | 파일 잠금으로 중복 실행을 막는다. 실험 중에는 Cluster Autoscaler를 멈추고 worker 노드를 2대로 고정한 뒤, 끝나면 원래 상태로 복원한다 |
| 변경 전 재확인과 변경 후 확인 | UID와 resourceVersion을 조건으로 건 JSON patch로 동시 변경을 감지한다. 위험한 조치 직전에 상태를 다시 읽고, 변경 후 실제 적용을 확인한다. 응답이 사라진 변경은 다시 보내지 않고 상태로 판단한다 |
| 실패 시 중단과 증거 보존 | 조건이 불확실하면 강행하지 않는다. 요청 원자료, 상태 스냅샷, 실행 코드의 해시와 사본을 실행별로 보존한다 |
| 공통 기반과 시나리오의 분리 | 환경·노드·OpenStack 접근은 공통 모듈이 맡고, 시나리오 실행기와 평가 도구는 그 위에 따로 둔다 |
| 비용과 접근 통제 | 호스트는 최대 실행 시간 뒤 자동 정지하고, 종료는 그 실행이 켠 호스트만 대상으로 한다. 핵심 자원에는 prevent_destroy를 건다 |

## 3.4 상세설계: 시나리오별 알고리즘

표 3-3은 네 시나리오의 판단 조건, 조치, 회복 판정과 활용한 기존 기능을 정리한 것이다. 수치 기준은 사전 실험에서 정하고 실험 중에는 바꾸지 않았다.

[표 3-3] 시나리오별 판단·조치·회복 기준

| 시나리오 | 판단 조건 | 조치(직접 구현) | 회복 판정 | 활용한 기존 기능 |
|---|---|---|---|---|
| 1. 호스트 CPU 경합 | 60초 창을 최대 6회 관측하여 다음이 2회 연속 성립: 실패 증가 또는 p95가 기준선의 1.5배 초과, 그리고 호스트 CPU 사용률 0.7 이상과 CPU PSI가 max(0.02, 기준선×2) 이상. Pod throttling, 메모리·I/O PSI 0.02 이상, 요청 기록 누락은 보류 | 다른 compute 호스트의 Ready worker 노드 중 배치 제약, 자원 요청, 목적지 여유(CPU 사용률 0.7 미만, PSI 0.02 미만)를 만족하고 CPU 사용률이 가장 낮은 노드를 선택. nodeSelector를 UID·resourceVersion 조건 patch로 변경하고 새 Pod를 먼저 기동. 900초 동안 재이동 금지 | 30초 대기 후 60초 창 3회 연속으로 실패 0, p95 기준선 1.2배 이하. 8회 안에 충족하지 못하면 검토 필요로 종료 | Nova 조회, nodeSelector, Deployment rolling update |
| 2. 공유 송신 경로 혼잡 | 60초 창 2회 모두: API p95 1.5배 초과 또는 실패, 송신 16 Mbps 이상과 qdisc overlimits 증가, 업로드 진행, 호스트 CPU 0.7 미만 | 목적지 worker 노드 port에 egress bandwidth-limit을 먼저 적용하고 Neutron API와 Open vSwitch의 실제 적용을 확인한 뒤 업로드를 이동. rate를 6·10·14·18 Mbps 단계로 조정 | API p95 기준선 1.3배 이하이며 업로드 진행 중이면 한 단계 상향. 악화 시 한 단계 낮춘 뒤 조정 중단 | Neutron QoS, Kubernetes 배치 |
| 3. 노드 통신 단절과 데이터베이스 복구 | Node NotReady 뒤 데이터베이스 접속 15회 연속 실패. 기존 데이터베이스 컨테이너의 실행 여부 확인 | Nova 정지 요청 후 SHUTOFF, task_state 없음, power_state 4, libvirt shut off를 확인. 직전에 다시 확인한 뒤 out-of-service taint 적용. fencing 미확인 시 중단 | 같은 volume을 쓰는 새 Pod Ready, 1,000건 digest 일치, 새 COMMIT 후 SELECT 성공, 60초 연속 접속, volume의 단독 연결 | Nova 정지, out-of-service taint, StatefulSet, Cinder CSI, PostgreSQL WAL |
| 4. worker 노드 VM 정지 | 대상 VM 1대에 Nova 정지 요청. 중단 후 재개 시 정지 요청을 다시 보내지 않음 | 서비스와 노드 용량을 분리하여 판정하고 실험 후 원상 복원 | 서비스: 외부 HTTP 요청의 회복. 용량: 목표 worker 수 Ready와 새 노드의 시험 Pod 실행 | MachineHealthCheck(Ready Unknown·False 120초), Cluster API, Cluster API Provider OpenStack |

시나리오 1의 서비스는 요청마다 PBKDF2를 100,000회 계산하는 CPU 중심 HTTP 서버로, compute 호스트 2의 worker 노드에서 실행하고 같은 호스트의 4 vCPU 경쟁 VM으로 경합을 만든다. 서비스 영향과 호스트 경합이 함께 지속될 때만 조치하도록 두 조건의 동시 성립을 요구하며, 목적지는 다른 compute 호스트로 한정한다. 같은 노드에서 다시 시작해도 같은 호스트의 경합은 남기 때문이다. 그림 3-3은 진단 반복, 목적지 선택, 안정화 확인의 순서를 나타낸다.

> [그림 3-3 자리] 구성 요소: 기존 그림 3-4(시나리오 1 순서도)를 그대로 사용한다. 높이는 약 8cm 이내로 줄인다.

[그림 3-3] 시나리오 1 순서도

시나리오 2는 요청마다 256 KiB를 응답하는 API와 1 MiB 조각을 보내는 업로드가 controller 호스트의 20 Mbit 송신 제한을 함께 지나는 구성이다. Neutron QoS는 port 단위로 적용되므로 두 작업이 같은 port를 쓰면 API까지 제한된다. 그래서 업로드를 별도 worker 노드로 옮겨 port를 나누고, 이동 전에 목적지 port에 제한을 먼저 걸어 이동 직후의 혼잡을 막는다(그림 3-4). 업로드 조각은 수신 측 기록과 SHA-256으로 검증하여 이동 뒤에도 중복이나 손상 없이 이어지는지 확인한다.

> [그림 3-4 자리] 구성 요소: 기존 그림 3-5(시나리오 2 조치 전후 배치도)를 그대로 사용한다. 높이는 약 7cm 이내로 줄인다.

[그림 3-4] 시나리오 2 조치 전후 배치도

시나리오 3은 단일 PostgreSQL StatefulSet이 1 GiB Cinder volume을 쓰는 구성에서, 대상 worker 노드의 Kubernetes API(6443)와 데이터베이스(5432) 경로를 iptables로 차단한다. 이때 Node는 NotReady가 되지만 기존 데이터베이스 프로세스는 계속 실행될 수 있으므로, 이전 VM이 실제로 멈췄음을 Nova와 libvirt 양쪽에서 확인한 뒤에만 out-of-service taint를 붙인다(그림 3-5). 실험 동안 toleration은 3600초로 두고 강제 volume 분리와 MachineHealthCheck의 교체를 막아, 다른 제어기가 fencing보다 먼저 복구를 진행하지 않게 하였다. Pod 강제 삭제, volume 강제 분리, finalizer 제거는 사용하지 않는다.

> [그림 3-5 자리] 구성 요소: 기존 그림 3-6(시나리오 3 순서도)을 그대로 사용한다. 높이는 약 8cm 이내로 줄인다.

[그림 3-5] 시나리오 3 순서도

시나리오 4의 서비스는 영구 volume이 없는 HTTP Deployment(replica 1, toleration 30초)이며, Kubernetes API의 서비스 프록시 경로로 초당 1회 요청한다. 실행기는 정확히 한 VM에 정지를 요청하고 서비스 회복과 노드 용량 회복을 따로 판정한다. 노드 교체 자체는 MachineHealthCheck, Cluster API, Cluster API Provider OpenStack이 수행하며, MachineHealthCheck 미사용 조건은 paused annotation으로 만든다. 정지 요청에서 SHUTOFF 확인까지는 약 73~81초가 걸렸고, 관측 구간과 용량 복원 시간은 SHUTOFF 확인 시각을 기준으로 잰다. 외부 요청은 정지 요청 전부터 계속 기록하므로 관측 구간 이전의 실패도 원자료에 남는다.

## 3.5 평가 도구 설계

평가 도구는 장애 주입기, 대응 정책, 외부 측정기, 독립 판정기를 분리한다(그림 3-6). 판정기는 외부 측정기의 요청 원자료와 사건 기록, 상태 스냅샷만 읽으며, 정책이 남긴 성공 표시는 사용하지 않는다. 실행 전에는 소스 코드와 설정의 해시를 고정하고 각 실험 뒤에 다시 확인하여 실험 도중 코드가 바뀌지 않았음을 보장한다. 판정은 측정 조건 충족, 안전성(대상·순서·식별자), 관측 구간 안의 서비스 회복을 따로 기록한다.

> [그림 3-6 자리] 구성 요소: 기존 그림 3-8(평가 도구 구조)을 그대로 사용한다. 높이는 약 8cm 이내로 줄인다.

[그림 3-6] 평가 도구 구조

# 4. 구현 및 결과분석

## 4.1 구현 결과

구현 코드는 Python 약 2.5만 줄과 셸·Makefile 약 6천 줄이며, 구축·운영(scripts), 시나리오 실행기(experiments), 평가 도구(evaluation)로 나뉜다. 테스트 함수 486개로 판정 논리와 실패 경로를 검증했고, 최신 회귀 테스트 221개가 통과하였다. 구축은 클라우드 선언부터 Cluster Autoscaler까지 하위 계층부터 순서대로 검증했으며, worker 노드의 1→2→3→2→1 자동 증감과 삭제된 노드의 Machine·VM·port 정리도 확인하였다. 장애 비교 실험은 worker 노드 수를 2대로 고정한 조건에서 수행하였다.

## 4.2 실험 방법

외부 측정기는 예정된 시각마다 요청을 보내고 예정 시각, 성공 여부, 지연을 모두 기록하며, 서비스 요청은 재시도하지 않는다. 표 4-1은 시나리오별 측정 조건과 비교 조건이다. 각 시나리오는 같은 장애·부하·설정에서 제안 조치만 뺀 무조치를 기본 비교로 두었다. 시나리오 1에는 재시작의 효과를 구분하는 동일 노드 재시작과, 호스트 경합만 있고 서비스 영향은 없을 때 조치하지 않는지 확인하는 경합만 있는 대조 조건을 더했다. 시나리오 2의 작업 분리 단독 조건은 Neutron QoS의 필요성을 확인하려고 다른 결과를 본 뒤 추가하였다. 실험은 11개 조건, 총 33회다.

[표 4-1] 측정 조건과 비교 조건

| 시나리오 | 관측 구간 | 요청률 | SLO | 장애 강도 | 비교 조건(횟수) |
|---|---:|---:|---:|---|---|
| 1 | 1200초 | 초당 5회 | 200 ms | 4 vCPU 경쟁 VM, CPU 작업 4개 | 제안 방식(3), 무조치(3), 동일 노드 재시작(3), 경합만 있는 대조 조건(2) |
| 2 | 1200초 | 초당 2회 | 500 ms | 20 Mbit 병목, 1 MiB × 4,096 조각 업로드 | 제안 방식(4), 작업 분리 단독(3), 무조치(3) |
| 3 | 900초 | 초당 1회 | 2000 ms | 6443·5432 통신 차단 | 제안 방식(3), 무조치(3) |
| 4 | 1200초 | 초당 1회 | 2000 ms | worker 노드 VM 1대 정지 | MachineHealthCheck 사용(3), 미사용(3) |

20초 판정 구간마다 예정 요청이 모두 기록되고, SLO 위반 비율이 5% 이하이며, 성공 요청의 p95 지연이 SLO 이하이면 정상 구간이다. 엄격 회복 판정은 관측 구간 끝까지 정상 구간이 120초 이상 이어지는 경우이며, 회복하지 못한 실험의 시간은 —로 표시한다. 시나리오 1·2는 조치 시점부터 관측 구간 끝까지의 SLO 위반율(조치 후 위반율)을 주지표로 쓰고, 조치 기록이 없는 무조치에는 진단 시각을 집계 시작으로 사용한다. 이 지표를 택한 이유는 4.5절에서 설명한다.

## 4.3 시나리오별 결과

### 4.3.1 시나리오 1

[표 4-2] 시나리오 1 결과

| 조건 | 회차 | 엄격 회복 | 최종 정상 구간 시작(초) | 조치 후 SLO 위반율 |
|---|---|---|---:|---:|
| 제안 방식 | 1 | 예 | 160 | 0.14% |
| | 2 | 예 | 140 | 0.12% |
| | 3 | 예 | 0 | 0.08% |
| 무조치 | 1 | 예 | 320 | 2.44% |
| | 2 | 아니오 | — | 2.63% |
| | 3 | 예 | 660 | 2.59% |
| 동일 노드 재시작 | 1 | 예 | 1040 | 2.80% |
| | 2 | 예 | 940 | 2.24% |
| | 3 | 예 | 940 | 3.54% |
| 경합만 있는 대조 조건 | 1, 2 | 조치 보류 | — | — |

제안 방식의 조치 후 SLO 위반율은 0.08~0.14%로 주입 전 기준선(0~0.67%) 안에 들었고, 무조치(2.44~2.63%)와 동일 노드 재시작(2.24~3.54%)은 높게 남아 두 집합의 값이 겹치지 않았다(표 4-2, 그림 4-1). 동일 노드 재시작이 무조치와 차이가 없었던 것은 경합의 원인이 같은 호스트의 다른 VM에 있어, 같은 노드에서 프로세스를 다시 띄워도 경합이 남는다는 해석과 맞는다. 경합만 있는 대조 조건(SLO 100 ms)에서는 두 회차 모두 서비스 영향이 기준에 미치지 않아(관측 구간 위반율 0.22%, 0.32%) 모듈이 조치를 보류하였다.

> [그림 4-1 자리] 구성 요소: 기존 그림 4-1(조건별 조치 후 SLO 위반율 점 그래프)을 그대로 사용한다. 높이는 약 7cm 이내로 줄인다.

[그림 4-1] 시나리오 1 조건별 조치 후 SLO 위반율

### 4.3.2 시나리오 2

[표 4-3] 시나리오 2 결과

| 조건 | 회차 | 엄격 회복 | 조치 후 위반율 | 업로드 처리량(MB/s) |
|---|---|---|---:|---:|
| 제안 방식 | 1 | 예 (영향 없음) | 0% | 0.63 |
| | 2 | 예 (영향 없음) | 0% | 0.62 |
| | 3 | 예 | 0% | 0.62 |
| | 4 | 예 (영향 없음) | 0% | 0.61 |
| 작업 분리 단독 | 1 | 예 (880초) | 2.63% | 1.83 |
| | 2 | 예 (1000초) | 2.83% | 1.83 |
| | 3 | 아니오 | 3.02% | 1.83 |
| 무조치 | 1 | 예 | 1.72% | 1.82 |
| | 2 | 예 | 2.34% | 1.82 |
| | 3 | 예 | 1.86% | 1.81 |

제안 방식은 4회 모두 조치 후 위반율이 0%였고, 작업 분리 단독(2.63~3.02%)은 무조치(1.72~2.34%)와 같은 수준이었다(표 4-3, 그림 4-2). 작업 분리 단독의 업로드 처리량(1.83 MB/s)도 무조치(1.81~1.82 MB/s)와 같아, 분리 뒤에도 업로드가 같은 공유 출구를 계속 쓴 것으로 해석된다. 병목 위치를 직접 측정하지는 않았다. Neutron QoS는 API를 보호한 대가로 업로드 처리량을 약 66%(1.82 → 0.62 MB/s) 줄였다. 제안 방식 4회 중 3회는 정책이 기준선 대비 지연으로 영향을 판단해 조치했지만 SLO 기준으로 비정상인 판정 구간은 생기지 않았으므로, 이 경우의 회복 시간 0초는 복구 속도를 뜻하지 않는다.

> [그림 4-2 자리] 구성 요소: 기존 그림 4-2(조건별 조치 후 위반율과 업로드 처리량)를 그대로 사용한다. 높이는 약 7cm 이내로 줄인다.

[그림 4-2] 시나리오 2 위반율과 업로드 처리량

### 4.3.3 시나리오 3

[표 4-4] 시나리오 3 결과

| 조건 | 회차 | 엄격 회복 | 최종 정상 구간 시작(초) | 요청 실패율 | 1,000건 보존 |
|---|---|---|---:|---:|---|
| 제안 방식 | 1 | 예 | 120 | 12.9% | 예 |
| | 2 | 예 | 460 | 12.2% | 예 |
| | 3 | 예 | 120 | 11.3% | 예 |
| 무조치 | 1~3 | 아니오 | — | 100% | — |

제안 방식은 3회 모두 관측 구간 안에 회복하였고, 커밋된 1,000건이 모두 보존되었으며, 모든 회차에서 fencing 확인이 out-of-service taint보다 먼저 이루어졌다(표 4-4). 무조치에서는 요청이 모두 실패했는데, toleration 3600초가 관측 구간 900초보다 길어 Pod가 옮겨지지 않았으므로 설정상 예상된 결과다. 장애 주입 뒤 Node는 NotReady였지만 VM과 데이터베이스 컨테이너는 계속 실행 중이었다. 이는 통신 실패만으로 이전 writer의 종료를 판단할 수 없으며, fencing 확인이 먼저 필요하다는 직접적인 근거다.

### 4.3.4 시나리오 4

[표 4-5] 시나리오 4 결과

| 조건 | 회차 | 정지 요청 → SHUTOFF 확인(초) | 실패 요청 수 | 서비스 중단 구간(초) | 서비스 회복 | 용량 복원 | 용량 복원 시간(초, SHUTOFF 기준 / 정지 요청 기준) |
|---|---|---:|---:|---:|---|---|---:|
| MachineHealthCheck 사용 | 1 | 80.6 | 76 | 75.0 | 예 | 예 | 216.9 / 297.5 |
| | 2 | 75.2 | 74 | 73.0 | 예 | 예 | 207.4 / 282.6 |
| | 3 | 74.7 | 76 | 75.0 | 예 | 예 | 214.9 / 289.6 |
| MachineHealthCheck 미사용 | 1 | 77.7 | 82 | 81.0 | 예 | 아니오 | — |
| | 2 | 73.0 | 79 | 78.0 | 예 | 아니오 | — |
| | 3 | 74.9 | 76 | 75.0 | 예 | 아니오 | — |

서비스 중단 구간은 첫 실패 요청부터 마지막 실패 요청까지의 시간이다. 실패 요청 수는 정지 요청 이후 전체를 센 값이며, 그중 SHUTOFF 확인 이후의 관측 구간에 든 것은 회차별 5~15건이다.

요청 실패는 두 조건 모두 정지 요청 약 10초 뒤 시작되어 73~81초 이어졌고, 대부분 VM이 SHUTOFF로 확인되기 전에 발생하였다(표 4-5, 그림 4-3). Nova 정지가 게스트의 정상 종료로 처리되는 동안 서비스가 먼저 멈춘 것으로 해석되며, 이 원인은 직접 확인하지 않았다. 서비스는 두 조건 모두 남은 worker 노드에서 회복했지만, 노드 용량은 MachineHealthCheck 사용 조건에서만 정지 요청 후 283~298초에 복원되었다. 서비스는 Kubernetes가 회복시키지만 노드 용량은 인프라 계층의 교체 없이는 돌아오지 않는다는 1.1절의 문제가 실측으로 확인된 것이다. 용량 복원은 기존 기능이 수행하였으며, 본 작품의 기여는 이를 통합하여 서비스와 용량을 분리해 판정하고 중단 후에도 안전하게 재개·정리하는 부분이다.

> [그림 4-3 자리] 구성 요소: 기존 그림 4-3(정지 요청 기준 사건 시간선)을 그대로 사용한다. 높이는 약 9cm 이내로 줄인다.

[그림 4-3] 시나리오 4 사건 시간선

## 4.4 연구 질문별 분석

[표 4-6] 연구 질문별 판정

| 연구 질문 | 판정 | 근거 |
|---|---|---|
| 필요성 | 지지 | 기존 기능만 쓴 조건(시나리오 1·2·3의 무조치, 시나리오 4의 MachineHealthCheck 미사용)에서 서비스나 용량 문제가 남았다 |
| 계층 간 정보의 기여 | 불확실 | 시나리오 2·3은 계층 간 대응 정보 없이는 조치를 실행할 수 없다는 구성적 근거만 있다. 시나리오 1은 현재 구성에서 식별할 수 없다 |
| 조치 기전 | 부분 지지 | 시나리오 1: 재배치가 효과를 냈다. 시나리오 2: Neutron QoS가 필요함을 확인했다. 시나리오 3: 개별 조치의 기여를 나누지 않았다 |
| 복구 효과 | 지지 | 네 시나리오 모두 제안 방식이 회복했다. 시나리오 2는 업로드 처리량 감소라는 대가가 있었다 |
| 안전성 | 부분 지지 | 경합만 있는 대조 조건에서 2회 모두 보류했다. 정리 검증을 모두 통과했다. 오래된 환경 식별자를 거부했다 |

필요성과 복구 효과는 지지되었다(표 4-6). 기존 기능만 쓴 조건에서는 서비스 품질이나 노드 용량 문제가 남았고, 제안 방식은 네 시나리오 모두에서 서비스를, 시나리오 3에서 데이터를, 시나리오 4에서 노드 용량을 회복하였다. 조건 간 차이를 보면 시나리오 1·2의 조치 후 위반율은 비교 조건과 완전히 분리되었고(정확 검정의 양측 확률값 각각 0.10, 0.057), 시나리오 3·4는 3/3 대 0/3이었다(0.10). 표본이 작아 이 확률값은 설명용으로만 제시한다.

계층 간 정보의 기여는 불확실로 판정하였다. 시나리오 2에서는 업로드 Pod가 연결된 VM과 Neutron port를 알아야 QoS 대상을 정할 수 있었고, 시나리오 3에서는 Node 상태만으로 알 수 없는 VM과 프로세스의 실행 여부를 확인해야 fencing 순서를 정할 수 있었다. 이는 계층 간 정보가 구현된 조치에 필요하다는 구성적 근거다. 그러나 시나리오 1은 worker 노드 2대가 서로 다른 호스트에 있어 "다른 노드로 옮긴다"는 단일 계층 규칙도 같은 목적지를 고르므로, 정보의 효과를 따로 식별할 수 없다. 조치 기전은 부분 지지다. 시나리오 1의 재배치 효과와 시나리오 2의 Neutron QoS 필요성은 확인했지만, 작업 분리가 꼭 필요한지와 시나리오 3의 개별 조치 기여는 나누어 시험하지 않았다. 안전성도 부분 지지로, 경합만 있는 대조 조건의 보류, 실행 중인 VM에 대한 fencing 확인 거부, 소유 자원 정리 검증, 오래된 환경 식별자로 시작한 실행의 장애 주입 전 거부를 확인하였다.

## 4.5 판정 지표에 대한 고찰

위반율이 일정하게 남은 조건에서도 엄격 회복 판정이 나타났다(무조치 2/3, 작업 분리 단독 2/3). 위반율을 약 2.6%(시나리오 1 무조치의 중앙값)로 두면, 요청 100개인 20초 구간 하나가 5% 기준을 넘을 확률은 이항분포로 약 4.7%이고 마지막 6개 구간이 모두 정상일 확률은 약 75%다. 즉 효과가 없는 조건도 우연히 회복으로 판정될 수 있으며, 실제 회복 시점도 880~1040초로 관측 구간 끝에 몰렸다. 그래서 시나리오 1·2는 조치 후 SLO 위반율을 주지표로 삼고 엄격 회복 판정을 함께 공개하였다. 이 지표는 실험 후에 정한 것이다.

## 4.6 타당성 위협과 한계

본 평가는 조건당 2~4회의 사례 연구이며, worker 노드 2대와 호스트 3대의 고정된 테스트베드에서 수행하였다. compute 호스트의 사양이 비대칭이고 요청 발생기가 목적지 호스트에 있으나, 시나리오 1의 재배치 후 지연은 기준선보다 좋아지지 않았다. 조치 후 위반율과 작업 분리 단독 조건은 사후에 정한 요소이며, 실험 기간 중 운영 코드(읽기 재시도, 시계 보호, security group 동기화 확인)를 보완했지만 측정 조건은 33회 전체에서 같게 유지하였다. 시나리오 3은 커밋된 기준 레코드의 보존만 확인했고, 무조치의 미회복은 900초 관측 범위의 결과다. 시나리오 4의 관측 구간은 SHUTOFF 확인 시각에서 시작하므로, 실제 중단은 정지 요청 기준으로 함께 제시하였다.

# 5. 결론 및 소감

## 5.1 결론

본 작품은 OpenStack과 Kubernetes의 자원 관계를 식별자로 연결하여 대표 장애 네 가지에 대응하는 모듈을 구현하고, 11개 조건, 총 33회의 비교 실험으로 검증하였다. 통합 테스트베드를 코드로 구축하고, 네 단계의 공통 구조로 대응 모듈을 구현했으며, 외부 요청 원자료로 결과를 독립 판정하였다. 실험에서 호스트 경합 시 다른 호스트로의 재배치는 위반율을 기준선 수준으로 되돌렸고, Neutron QoS는 업로드 처리량을 대가로 API를 보호했으며, fencing을 앞세운 복구는 커밋 데이터를 보존하였다. worker 노드 VM 정지에서는 서비스 회복과 노드 용량 회복이 서로 다른 조건으로 이루어짐을 확인하였다. 후속 연구로는 작업 분리 없이 Neutron QoS만 적용하는 조건, 단일 계층 정보만 쓰는 판단 규칙과의 비교, fencing과 out-of-service taint의 개별 효과 분리, 같은 호스트에 대체 노드가 있는 3대 이상의 worker 구성에서의 검증이 필요하다.

## 5.2 소감

처음 이 주제를 골랐을 때 나는 OpenStack 위에 Kubernetes를 올리고 장애가 나면 자동으로 고치는 프로그램을 만드는 일을 구현의 문제로만 생각했다. 7월 말에는 로컬 환경에 테스트베드를 꾸리는 것부터 시작했지만, 실행 환경과 CPU 구조가 다른 여러 구성을 함께 유지하는 부담이 커서 8월 말 Google Cloud 한 곳으로 옮겼다. 중첩 가상화 위에 OpenStack과 Cluster API를 올리고 worker 노드가 자동으로 늘고 줄어드는 것을 처음 확인했을 때, 이제 시작할 수 있겠다는 안도감이 들었다.

가장 오래 붙잡고 있었던 것은 내가 만든 기능이 아니라 그 아래의 환경이었다. security group의 주소 목록이 비어 DNS가 실패하기도 했고, 접속 터널이 끊겨 실험이 중간에 멈추기도 했다. 측정 도중 노트북 시계가 자동으로 보정되어 요청 시각이 어긋난 일도 있었는데, 결국 실험 중에는 시계 보정을 막는 장치를 직접 만들었다. 원인을 하나 찾을 때마다 장애 대응을 연구한다면서 정작 내 실험 환경의 장애에 가장 많이 대응하고 있다는 생각이 들었다.

가장 크게 생각이 바뀐 것은 10월 말이었다. 10월 24일 재시험에서 34건이 모두 통과해 거의 끝났다고 생각했는데, 이틀 뒤 결과를 다시 읽다가 시나리오 3에서 노드 이상 시각으로 쓴 값이 실제로는 진단이 끝난 시각이었다는 것을 발견했다. 시나리오 2의 비교도 서로 독립된 실행이 아니었다. 통과했다는 사실이 곧 무엇을 증명했다는 뜻은 아니라는 것을 그때 알았다. 마감까지 사흘밖에 남지 않았지만 비교 조건과 판정 기준을 다시 정하고 네 시나리오를 처음부터 다시 실험했다. 보고서를 쓰면서도 시나리오 4의 회복 시간이 측정 구간의 시작점 때문에 짧게 보였다는 것을 찾아 고쳤다. 숫자는 그것을 잰 방법과 함께 읽어야 한다는 것을 여러 번 배웠다.

진행하면서 스스로 지키려고 한 원칙도 있다. 재배치 목적지의 성능이 회복 기준을 넘었을 때 기준을 낮추지 않고 목적지 사양을 늘렸으며, 그 사실과 한계를 기록했다. 복구되지 않은 결과도 다시 돌려 좋은 결과로 바꾸지 않았다. 1차 평가에서 자동 대응과 스크립트 런북의 복구 시간이 거의 같게 나왔을 때는 처음에 실망했지만, 그 덕분에 이 작품의 가치가 속도보다 이전 VM이 멈췄는지 확인한 뒤에야 볼륨을 넘기는 안전한 순서에 있다는 것을 분명히 알게 되었다. 무료 체험 크레딧 안에서 호스트 가동 시간을 기록하며 실험 일정을 짠 경험도 비용을 생각하며 일하는 연습이 되었다.

아쉬움도 남는다. 같은 호스트에 대체 노드를 두는 구성이나 작업 분리 없이 QoS만 거는 조건은 시간과 비용 때문에 시험하지 못했다. 다시 한다면 실험 환경의 안정성과 측정 방법부터 먼저 검증한 뒤 기능을 만들겠다. 이번 작품을 통해 동작하는 시스템을 만드는 것과 그것이 제대로 동작한다고 말할 수 있는 근거를 만드는 것은 다른 일이며, 후자가 훨씬 어렵고 중요하다는 것을 배웠다.

# 참고문헌

[1] 김지용, 김영종, 김명호, “오픈스택 환경에서의 서비스 메시 기반 통합적 모니터링 시스템,” 한국IT정책경영학회 논문지, 제12권 제1호, pp. 1601–1610, 2020.

[2] 박주원 외, “시스템 결함 분석을 위한 이벤트 로그 연관성에 관한 연구,” 한국산업경영시스템학회지, 제39권 제2호, pp. 129–137, 2016.

[3] L. Wu et al., “MicroRCA: Root Cause Localization of Performance Issues in Microservices,” Proc. IEEE/IFIP NOMS, pp. 1–9, April 2020.

[4] Y. Gan et al., “Sage: Practical and Scalable ML-Driven Performance Debugging in Microservices,” Proc. ASPLOS, pp. 135–151, April 2021.

[5] H. Yang and Y. Kim, “Design and Implementation of Fast Fault Detection in Cloud Infrastructure for Containerized IoT Services,” Sensors, vol. 20, no. 16, 4592, August 2020.

[6] OpenStack Masakari, “Masakari service overview,” https://docs.openstack.org/masakari/latest/install/overview.html

[7] C. Delimitrou and C. Kozyrakis, “Paragon: QoS-aware Scheduling for Heterogeneous Datacenters,” Proc. ASPLOS, pp. 77–88, March 2013.

[8] H. Qiu et al., “FIRM: An Intelligent Fine-grained Resource Management Framework for SLO-Oriented Microservices,” Proc. USENIX OSDI, pp. 805–825, November 2020.

[9] 변지섭 외, “엣지 컴퓨팅 환경에서 쿠버네티스 기반 네트워크 성능 제어 방식 분석,” 한국차세대컴퓨팅학회 논문지, 제20권 제1호, pp. 114–124, 2024.

[10] L. A. Vayghan et al., “A Kubernetes Controller for Managing the Availability of Elastic Microservice Based Stateful Applications,” Journal of Systems and Software, vol. 175, 110924, May 2021.

[11] Medik8s, “Fence Agents Remediation,” https://www.medik8s.io/remediation/fence-agents-remediation/fence-agents-remediation/

[12] J. Flora et al., “A Study on the Aging and Fault Tolerance of Microservices in Kubernetes,” IEEE Access, vol. 10, pp. 132786–132799, 2022.

[13] A. Basiri et al., “Chaos Engineering,” IEEE Software, vol. 33, no. 3, pp. 35–41, May 2016.

[14] OpenStack Nova, “CPU topologies,” https://docs.openstack.org/nova/2025.2/admin/cpu-topologies.html

[15] OpenStack Compute API, “Stop Server,” https://docs.openstack.org/api-ref/compute/#stop-server-os-stop-action

[16] OpenStack Neutron, “Quality of Service (QoS),” https://docs.openstack.org/neutron/latest/admin/config-qos.html

[17] Kubernetes, “Taints and Tolerations,” https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/

[18] Kubernetes, “Node Shutdowns,” https://v1-35.docs.kubernetes.io/docs/concepts/cluster-administration/node-shutdown/

[19] Cluster API, “Configure a MachineHealthCheck,” https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking.html

[20] Cluster API Provider OpenStack, “Introduction,” https://cluster-api-openstack.sigs.k8s.io/introduction

[21] J. O. Kephart and D. M. Chess, “The Vision of Autonomic Computing,” Computer, vol. 36, no. 1, pp. 41–50, January 2003.

[22] Linux Kernel Documentation, “PSI - Pressure Stall Information,” https://docs.kernel.org/accounting/psi.html

[23] PostgreSQL Documentation, “Write-Ahead Logging (WAL),” https://www.postgresql.org/docs/current/wal-intro.html

# 부록

## A. 원천코드

[확인 필요: 원천코드의 최종 제출 범위는 지도교수에게 확인할 것.]

아래 발췌는 저장소의 원문을 함수 단위로 수록한 것이다. 줄 번호는 작성 시점의 원본 파일을 기준으로 한다.

### 시나리오 1

`experiments/graduation_s1_auto.py:127-148` — `diagnose`

```python
def diagnose(baseline, sample, metrics, cpu_before, cpu_after, baseline_pressure, rate):
    reasons = []
    if sample['requests'] < rate * POLICY['window_seconds'] * .9 or sample['duplicate_indexes'] or\
            sample['max_sample_gap_seconds'] is None or sample['max_sample_gap_seconds'] > max(2.5, 3 / rate):
        reasons.append('request_evidence_incomplete')
    if not baseline['latency_ms']['p95']:
        reasons.append('latency_unavailable')
    elif sample['failures'] <= baseline['failures']:
        if not sample['latency_ms']['p95']:
            reasons.append('latency_unavailable')
        elif sample['latency_ms']['p95'] <= baseline['latency_ms']['p95'] * POLICY['impact_ratio']:
            reasons.append('service_impact_not_confirmed')
    if metrics['cpu_utilization'] < POLICY['cpu_min'] or\
            metrics['cpu_pressure_some'] < max(POLICY['psi_min'], baseline_pressure * POLICY['psi_baseline_ratio']):
        reasons.append('host_contention_not_confirmed')
    delta, errors = pod_cpu_delta(cpu_before, cpu_after)
    if errors or delta.get('nr_throttled', 0) or delta.get('throttled_usec', 0):
        reasons.append('pod_cpu_evidence_invalid_or_throttled')
    if metrics['memory_pressure_some'] >= .02 or metrics['io_pressure_some'] >= .02 or\
            metrics['memory_available'] < POLICY['min_host_memory_bytes']:
        reasons.append('other_host_pressure')
    return {'trigger': not reasons, 'reasons': reasons, 'pod_cpu_delta': delta, 'cpu_errors': errors}
```

`experiments/graduation_s1_auto.py:72-113` — `candidate_reasons`

```python
def candidate_reasons(node, pods, spec, source_host, placement, metrics):
    reasons = []
    labels = node['metadata'].get('labels', {})
    if not condition(node, 'Ready') or node['spec'].get('unschedulable'):
        reasons.append('node_not_schedulable')
    if 'node-role.kubernetes.io/control-plane' in labels or placement['compute_host'] == source_host:
        reasons.append('not_another_compute_worker')
    for key, value in spec.get('nodeSelector', {}).items():
        if key != 'kubernetes.io/hostname' and labels.get(key) != value:
            reasons.append('node_selector')
    affinity = spec.get('affinity', {})
    if affinity.get('podAffinity') or affinity.get('podAntiAffinity') or spec.get('topologySpreadConstraints'):
        reasons.append('unsupported_cross_pod_constraint')
    terms = affinity.get('nodeAffinity', {}).get('requiredDuringSchedulingIgnoredDuringExecution', {}).get('nodeSelectorTerms')
    if terms is not None and not any(
            bool(term.get('matchExpressions') or term.get('matchFields')) and
            all(matches(e, labels) for e in term.get('matchExpressions', [])) and
            all(matches(e, {'metadata.name': node['metadata']['name']}) for e in term.get('matchFields', []))
            for term in terms):
        reasons.append('node_affinity')
    for taint in node['spec'].get('taints', []):
        if taint['effect'] not in ('NoSchedule', 'NoExecute'):
            continue
        if not any((not t.get('effect') or t['effect'] == taint['effect']) and
                   (t.get('key') == taint['key'] or (not t.get('key') and t.get('operator') == 'Exists')) and
                   (t.get('operator') == 'Exists' or t.get('value', '') == taint.get('value', ''))
                   for t in spec.get('tolerations', [])):
            reasons.append('untolerated_taint')
    for resource in ('cpu', 'memory'):
        available = quantity(node['status']['allocatable'][resource])
        used = sum(requests(p['spec'], resource) for p in pods
                   if p['spec'].get('nodeName') == node['metadata']['name'] and
                   p.get('status', {}).get('phase') not in ('Succeeded', 'Failed'))
        if available - used < requests(spec, resource):
            reasons.append('insufficient_' + resource)
    if metrics['cpu_utilization'] >= POLICY['cpu_min'] or metrics['cpu_pressure_some'] >= POLICY['psi_min']:
        reasons.append('destination_cpu_busy')
    if metrics['memory_available'] < POLICY['min_host_memory_bytes']:
        reasons.append('destination_memory_low')
    if any(metrics.get(name + '_pressure_some', 1) >= .02 for name in ('memory', 'io')):
        reasons.append('destination_other_pressure')
    return reasons
```

`experiments/graduation_s1_auto.py:225-279` — `move_service`

```python
    def move_service(self, record):
        source = self.s1.verify()
        if any(source[k] != record['service_before'][k] for k in
               ('pod_uid', 'nova_id', 'image_id', 'container_id', 'restart_count')):
            raise RuntimeError('S1 source changed before automatic action')
        source_place = self.s1.placement(source['nova_id'])
        self.check_source_placement(record, source_place)
        deployment = self.s1.obj('deployment', 'http')
        original = record['deployment_before']
        if deployment['metadata']['uid'] != original['metadata']['uid'] or deployment['spec'] != original['spec']:
            raise RuntimeError('S1 Deployment was changed by another controller')
        if deployment['spec']['replicas'] != 1 or deployment['spec']['strategy'] != {
                'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0}}:
            raise RuntimeError('S1 requires surge-before-removal rollout')
        nodes = self.client.get('w', 'nodes')['items']
        pods = self.client.get('w', 'pods', '-A')['items']
        machines = self.client.get('m', 'machines', '-n', self.client.ns,
                                   '-l', 'cluster.x-k8s.io/cluster-name=' + self.client.cluster)['items']
        candidates = []
        for node in nodes:
            if 'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels', {}):
                continue
            matches_machine = [m for m in machines if not m['metadata'].get('deletionTimestamp') and
                               m.get('status', {}).get('nodeRef', {}).get('name') == node['metadata']['name']]
            if len(matches_machine) != 1:
                continue
            provider = matches_machine[0].get('spec', {}).get('providerID', '')
            if not provider.startswith('openstack:///') or node['spec'].get('providerID') != provider:
                continue
            place = self.s1.placement(provider.removeprefix('openstack:///'))
            metrics = record['decision_metrics'].get(place['compute_host'])
            if not metrics or time.time() - epoch(metrics['time']) > POLICY['max_sample_age_seconds']:
                continue
            reasons = candidate_reasons(node, pods, deployment['spec']['template']['spec'],
                                        source_place['compute_host'], place, metrics)
            self.event(record, {'kind': 'candidate', 'node': node['metadata']['name'],
                                'placement': place, 'reasons': reasons})
            if not reasons:
                candidates.append((metrics['cpu_utilization'], node['metadata']['name'], node, place))
        if not candidates:
            self.write(record, 'deferred', defer_reason='no_eligible_destination')
            raise RuntimeError('S1 automatic recovery deferred: no eligible destination')
        _, _, node, place = min(candidates, key=lambda x: (x[0], x[1]))
        record.update(target_node=node['metadata']['name'], target_selector=node['metadata']['labels']['kubernetes.io/hostname'],
                      target_nova_id=place['nova_id'], target_compute_host=place['compute_host'])
        annotations = dict(deployment['metadata'].get('annotations', {}))
        annotations[COOLDOWN_KEY] = utc_now()
        selector = dict(deployment['spec']['template']['spec'].get('nodeSelector', {}))
        selector['kubernetes.io/hostname'] = record['target_selector']
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': deployment['metadata']['uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': deployment['metadata']['resourceVersion']},
                 {'op': 'add', 'path': '/metadata/annotations', 'value': annotations},
                 {'op': 'add', 'path': '/spec/template/spec/nodeSelector', 'value': selector}]
        self.write(record, 'relocation-intent', relocation_intent_at=utc_now(), action_count=1)
        self.s1.k('-n', NAMESPACE, 'patch', 'deployment', 'http', '--type=json', '-p', json.dumps(patch))
```

`experiments/graduation_s1_auto.py:151-157` — `stable_window`

```python
def stable_window(window, baseline_p95, rate):
    return (window['requests'] >= rate * POLICY['recovery_window_seconds'] * .9 and
            not window['failures'] and not window['duplicate_indexes'] and
            window['latency_ms']['p95'] is not None and
            window['latency_ms']['p95'] <= baseline_p95 * POLICY['recovery_ratio'] and
            window['max_sample_gap_seconds'] is not None and
            window['max_sample_gap_seconds'] <= max(2.5, 3 / rate))
```

### 시나리오 2

`experiments/graduation_s2.py:16-27` — `analyze`

```python
def analyze(sample):
    rows = sample['rows']
    indexes = [r['index'] for r in rows]
    success = [r for r in rows if r['ok']]
    before, after = sample['qdisc_before'][0], sample['qdisc_after'][0]
    return {'requests': len(rows), 'failures': len(rows) - len(success),
            'complete': len(rows) == 120 and set(indexes) == set(range(120)) and len(set(indexes)) == 120,
            'p95_ms': percentile([r['latency_ms'] for r in success], .95),
            'upload_bytes': sample['progress_after']['bytes'] - sample['progress_before']['bytes'],
            'egress_bps': (after['bytes'] - before['bytes']) * 8 / sample['elapsed'],
            'overlimits': after['overlimits'] - before['overlimits'],
            'drops': after['drops'] - before['drops']}
```

`experiments/graduation_s2.py:30-32` — `impacted`

```python
def impacted(base, metric):
    return metric['complete'] and (metric['failures'] > 0 or
           (metric['p95_ms'] is not None and metric['p95_ms'] > base * 1.5))
```

`experiments/graduation_s2.py:35-36` — `stable`

```python
def stable(base, metric):
    return metric['complete'] and metric['failures'] == 0 and metric['p95_ms'] is not None and metric['p95_ms'] <= base * 1.3 and metric['upload_bytes'] > 0
```

`experiments/graduation_s2.py:39-41` — `next_rate`

```python
def next_rate(current, healthy):
    index = RATES.index(current)
    return RATES[min(len(RATES) - 1, index + 1)] if healthy else RATES[max(0, index - 1)]
```

`experiments/graduation_s2.py:70-98` — `set_rate`

```python
    def set_rate(self, rate):
        r = self.record
        node = self.obj('node', r['workers'][1]['node'], False)
        if node['metadata']['uid'] != r['workers'][1]['node_uid'] or not condition(node, 'Ready') or node['spec'].get('unschedulable'):
            raise RuntimeError('destination worker identity/readiness changed')
        port = self.admin_json('port', 'show', r['workers'][1]['port']['id'])
        if port['device_id'] != r['workers'][1]['nova_id'] or port.get('qos_policy_id') not in (None, '', r['policy_id']):
            raise RuntimeError('destination port ownership/policy changed')
        self.write('qos-change-intent', desired_rate_kbps=rate)
        self.admin('network', 'qos', 'rule', 'set', '--max-kbps', str(rate), '--max-burst-kbits', str(BURST_KBITS),
                   r['policy_id'], r['rule_id'])
        self.admin('port', 'set', '--qos-policy', r['policy_id'], port['id'])
        observed = self.admin_json('network', 'qos', 'rule', 'show', r['policy_id'], r['rule_id'])
        updated = self.admin_json('port', 'show', port['id'])
        if int(observed['max_kbps']) != rate or observed['direction'] != 'egress' or updated['qos_policy_id'] != r['policy_id']:
            raise RuntimeError('QoS API readback mismatch')
        # Inspect the enforcing OVS interface, not just the Neutron database.
        def installed():
            out = self.operational_remote('s2-ovs-enforcement','sudo docker exec openvswitch_vswitchd ovs-vsctl --format=json '
                              '--columns=name,ingress_policing_rate,ingress_policing_burst find Interface '
                              + shlex.quote('external_ids:iface-id=' + port['id']), host=r['workers'][1]['host'])
            rows = json.loads(out)['data']
            if len(rows) != 1 or (int(rows[0][1]) != rate or int(rows[0][2]) != BURST_KBITS):
                return False
            return rows
        enforcement = wait_for(installed, seconds=120, interval=5)
        self.record.setdefault('policy_changes', []).append({'time': utc_now(), 'kbps': rate, 'burst_kbits': BURST_KBITS,
                                                           'port_id': port['id'], 'ovs': enforcement})
        self.write('qos-installed', current_rate_kbps=rate)
```

### 시나리오 3

`experiments/graduation_s3.py:20-24` — `require_fenced`

```python
def require_fenced(server, expected_id, hypervisor_state):
    if server.get('id') != expected_id or server.get('status') != 'SHUTOFF' or\
            server.get('OS-EXT-STS:task_state') is not None or\
            server.get('OS-EXT-STS:power_state') != 4 or hypervisor_state.strip() != 'shut off':
        raise RuntimeError('fencing is unconfirmed; no Pod deletion or volume detach is permitted')
```

`experiments/graduation_s3.py:142-157` — `fence`

```python
    def fence(self):
        source = self.record['source']
        self.write('fence-intent', fence_requested_at=utc_now())
        self.admin('server', 'stop', source['nova_id'])
        def stopped():
            server = self.admin_json('server', 'show', source['nova_id'])
            if server.get('OS-EXT-SRV-ATTR:host') != source['host']:
                raise RuntimeError('source VM moved to another hypervisor during fencing')
            if server.get('status') != 'SHUTOFF' or server.get('OS-EXT-STS:task_state') is not None:
                return False
            hypervisor = self.operational_remote('s3-hypervisor-state','sudo docker exec nova_libvirt virsh domstate ' + shlex.quote(source['instance_name']), host=source['host'])
            require_fenced(server, source['nova_id'], hypervisor)
            self.save('fence.json', {'time': utc_now(), 'server': server, 'hypervisor_state': hypervisor.strip()})
            return True
        wait_for(stopped, seconds=180)
        self.write('fenced', fenced_at=utc_now())
```

`experiments/graduation_s3.py:159-177` — `mark_out_of_service`

```python
    def mark_out_of_service(self):
        source = self.record['source']
        # Re-read fencing immediately before the first destructive recovery action.
        server = self.admin_json('server', 'show', source['nova_id'])
        if server.get('OS-EXT-SRV-ATTR:host') != source['host']:
            raise RuntimeError('source VM hypervisor mapping changed')
        hypervisor = self.operational_remote('s3-hypervisor-state','sudo docker exec nova_libvirt virsh domstate ' + shlex.quote(source['instance_name']), host=source['host'])
        require_fenced(server, source['nova_id'], hypervisor)
        node = self.obj('node', source['node'], False)
        if node['metadata']['uid'] != source['node_uid']:
            raise RuntimeError('source Node identity changed')
        taints = node['spec'].get('taints', [])
        if any(t['key'] == OUT for t in taints):
            raise RuntimeError('out-of-service taint is owned by another actor')
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': source['node_uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
                 {'op': 'add', 'path': '/spec/taints', 'value': taints + [{'key': OUT, 'value': self.record['run_id'], 'effect': 'NoExecute'}]}]
        self.write('out-of-service-intent', out_of_service_at=utc_now())
        self.k('patch', 'node', source['node'], '--type=json', '-p', json.dumps(patch))
```

`experiments/graduation_s3.py:179-191` — `activate_recovery`

```python
    def activate_recovery(self):
        self.mark_out_of_service()
        timeline = []
        def recovered():
            pod = self.dbpod()
            attachments = self.client.get('w', 'volumeattachments')['items']
            relevant = [v for v in attachments if v['spec']['source'].get('persistentVolumeName') == self.record['pv_name']]
            timeline.append({'time': utc_now(), 'pod': pod, 'attachments': relevant})
            self.save('recovery-timeline.json', timeline)
            return pod and pod['metadata']['uid'] != self.record['pod_before']['metadata']['uid'] and\
                pod['spec'].get('nodeName') == self.record['target']['node'] and condition(pod, 'Ready')
        wait_for(recovered, seconds=600, interval=5)
        self.write('database-recovered', pod_after=self.dbpod(), recovered_at=utc_now())
```

### 시나리오 4: MachineHealthCheck 선언

`kubernetes/graduation-s4/machine-health-check.yaml.tpl:1-24`

```yaml
apiVersion: cluster.x-k8s.io/v1beta2
kind: MachineHealthCheck
metadata:
  name: graduation-s4-worker
  namespace: ${WORKLOAD_NAMESPACE}
  labels:
    openstack-k8s.dev/experiment: graduation-s4
spec:
  clusterName: ${WORKLOAD_CLUSTER_NAME}
  selector:
    matchLabels:
      cluster.x-k8s.io/deployment-name: ${WORKLOAD_CLUSTER_NAME}-md-0
  checks:
    nodeStartupTimeoutSeconds: 900
    unhealthyNodeConditions:
    - type: Ready
      status: Unknown
      timeoutSeconds: 120
    - type: Ready
      status: "False"
      timeoutSeconds: 120
  remediation:
    triggerIf:
      unhealthyLessThanOrEqualTo: 1
```

### 독립 판정기

`evaluation/fresh_analysis.py:67-151` — `request_metrics`

```python
def request_metrics(requests, cfg, start, end, expected=None):
    errors = []
    indexed = {}
    for row in requests:
        key = row.get('request_id')
        if key is None or key in indexed:
            errors.append('missing_or_duplicate_request_id')
        indexed[key] = row
    indexed_arrivals = sorted((r for r in requests if type(r.get('index')) is int), key=lambda r:r['index'])
    indexes=[r['index'] for r in indexed_arrivals]
    if len(indexes)!=len(set(indexes)):
        errors.append('duplicate_arrival_index')
    for a,b in zip(indexed_arrivals,indexed_arrivals[1:]):
        if a.get('clock_id')==b.get('clock_id') and a.get('started_monotonic') is not None and b.get('started_monotonic') is not None and a.get('started_utc') and b.get('started_utc') and abs((epoch(b['started_utc'])-epoch(a['started_utc']))-(b['started_monotonic']-a['started_monotonic']))>.1:
            errors.append('clock_step_between_requests')
        if a.get('clock_id')==b.get('clock_id') and abs(epoch(b['scheduled_utc'])-epoch(a['scheduled_utc'])-(b['index']-a['index'])/cfg['rate'])>.01:
            errors.append('arrival_schedule_mismatch')
    expected = expected if expected is not None else int(round((end - start) * cfg['rate']))
    arrivals = [r for r in requests if start <= epoch(r['scheduled_utc']) < end]
    missing = max(0, expected - len(arrivals))
    if missing or len(arrivals) != expected:
        errors.append('request_arrivals_incomplete')
    latencies, execution_latencies, queue = [], [], []
    failures = missing
    incomplete = rejected = 0
    timed = []
    for row in arrivals:
        scheduled = epoch(row['scheduled_utc'])
        begin = epoch(row['started_utc']) if row.get('started_utc') else None
        finish = epoch(row['completed_utc']) if row.get('completed_utc') else None
        if begin is not None and begin < scheduled - .001 or finish is not None and (begin is None or finish < begin):
            errors.append('request_time_reversed')
        if row.get('started_monotonic') is not None and row.get('completed_monotonic') is not None:
            if row.get('completed_clock_id', row.get('clock_id')) != row.get('clock_id') or row['completed_monotonic'] < row['started_monotonic']:
                errors.append('request_monotonic_invalid')
            elif begin is not None and finish is not None and abs((finish-begin)-(row['completed_monotonic']-row['started_monotonic']))>.1:
                errors.append('wall_monotonic_duration_disagreement')
        rejection = row.get('generator_rejection', False)
        rejected += bool(rejection)
        incomplete += finish is None and not rejection
        total_ms = (finish - scheduled) * 1000 if finish is not None else None
        ordered=begin is not None and finish is not None and scheduled-.001<=begin<=finish
        good = bool(ordered and row.get('ok') and row.get('correct') and begin is not None and finish is not None
                    and not rejection and total_ms <= cfg['deadline_seconds'] * 1000)
        failures += not good
        if begin is not None:
            queue.append((begin - scheduled) * 1000)
        if good:
            latencies.append(total_ms)
            execution_latencies.append((finish - begin) * 1000)
        timed.append((scheduled, good, total_ms))
    bins = []
    bin_seconds = cfg['bin_seconds']
    for i in range(math.ceil((end - start) / bin_seconds)):
        a, b = start + i * bin_seconds, min(end, start + (i + 1) * bin_seconds)
        samples = [r for r in timed if a <= r[0] < b]
        complete = len(samples) >= max(cfg['min_samples'], int(round((b - a) * cfg['rate'])))
        bad=sum(not ok or latency>cfg['slo_ms'] for _,ok,latency in samples)
        successful_p95=quantile([latency for _,ok,latency in samples if ok])
        healthy = complete and bad/len(samples)<=cfg['bin_max_bad_fraction'] and successful_p95 is not None and successful_p95<=cfg['slo_ms']
        bins.append(dict(start=a, end=b, samples=len(samples), complete=complete, healthy=healthy,
                         service_slo_violations=bad,successful_p95_ms=successful_p95,
                         allowed_bad_count=math.floor(cfg['bin_max_bad_fraction']*int(round((b-a)*cfg['rate'])))))
    # Recovery is the final contiguous healthy tail; an earlier healthy interval followed by relapse is not final recovery.
    tail = []
    for b in bins:
        if b['healthy']:
            tail.append(b)
        else:
            tail = []
    stable_start = tail[0]['start'] if tail and tail[-1]['end'] - tail[0]['start'] >= cfg['stable_seconds'] else None
    confirmed = next((b['end'] for b in tail if stable_start is not None and b['end'] - stable_start >= cfg['stable_seconds']), None)
    return dict(expected_arrivals=expected, observed_arrivals=len(arrivals), failures=failures,
                failure_rate=failures / expected if expected else None, missing=missing, incomplete=incomplete,
                service_slo_violation_fraction=(missing+sum(not ok or latency>cfg['slo_ms'] for _,ok,latency in timed))/expected if expected else None,
                generator_rejections=rejected, scheduled_latency_p95_ms=quantile(latencies),
                execution_latency_p95_ms=quantile(execution_latencies), queue_p95_ms=quantile(queue),
                violation_seconds_lower_bound=sum(b['end'] - b['start'] for b in bins if b['complete'] and not b['healthy']),
                unobserved_seconds=sum(b['end'] - b['start'] for b in bins if not b['complete']),
                impact_start=min((at for at,ok,latency in timed if not ok or latency>cfg['slo_ms']),default=None),
                recovery_start=stable_start, stable_confirmed=confirmed,
                recovery_seconds=stable_start - start if stable_start is not None else None,
                recovered=stable_start is not None, bins=bins, errors=sorted(set(errors)),
                units={'latency':'ms', 'recovery':'seconds', 'violation':'seconds'},
                interval=[start, end], limitation='success latency conditional on successful, correct requests before deadline')
```

## B. 33회 전체 결과표

표 4-2~4-5의 각 회차를 하나의 표로 정리하였다. 시나리오 1·2의 위반율은 관측 구간 전체와 조치 후를 구분한다. 조건부 p95와 업로드 처리량은 관측 구간 전체의 값이다. 최종 정상 구간 시작이 —인 행은 관측 구간 안에 회복하지 못했거나 해당 지표가 없는 경우다. 시나리오 4의 관측 구간과 최종 정상 구간 시작은 VM SHUTOFF 확인 기준이며, 용량 복원 시간은 SHUTOFF 기준과 정지 요청 기준을 함께 적었다. 시나리오 4의 실패 요청 수는 정지 요청 이후 전체이고 괄호 안은 관측 구간에 든 수다.

[표 B-1] 33회 전체 결과

| 시나리오 | 조건 | 회차 | 서비스 엄격 회복 | 최종 정상 구간 시작(초) | 전체 SLO 위반율 | 조치 후 SLO 위반율 | 요청 실패율 | 조건부 p95(ms) | 업로드 처리량(MB/s) | 1,000건 보존 | 용량 복원 | 용량 복원 시간(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 제안 방식 | 1 | 예 | 160 | 0.65% | 0.14% | — | 154.1 | — | — | — | — |
| 1 | 제안 방식 | 2 | 예 | 140 | 0.68% | 0.12% | — | 157.4 | — | — | — | — |
| 1 | 제안 방식 | 3 | 예 | 0 | 0.57% | 0.08% | — | 155.3 | — | — | — | — |
| 1 | 무조치 | 1 | 예 | 320 | 2.60% | 2.44% | — | 184.8 | — | — | — | — |
| 1 | 무조치 | 2 | 아니오 | — | 2.73% | 2.63% | — | 186.6 | — | — | — | — |
| 1 | 무조치 | 3 | 예 | 660 | 2.78% | 2.59% | — | 187.6 | — | — | — | — |
| 1 | 동일 노드 재시작 | 1 | 예 | 1040 | 2.87% | 2.80% | — | 188.7 | — | — | — | — |
| 1 | 동일 노드 재시작 | 2 | 예 | 940 | 2.38% | 2.24% | — | 188.8 | — | — | — | — |
| 1 | 동일 노드 재시작 | 3 | 예 | 940 | 3.48% | 3.54% | — | 192.9 | — | — | — | — |
| 1 | 경합만 있는 대조 조건 | 1 | 조치 보류 | — | 0.22% | — | — | 54.3 | — | — | — | — |
| 1 | 경합만 있는 대조 조건 | 2 | 조치 보류 | — | 0.32% | — | — | 53.0 | — | — | — | — |
| 2 | 제안 방식 | 1 | 예 (영향 없음) | 0 | 0.21% | 0% | — | — | 0.63 | — | — | — |
| 2 | 제안 방식 | 2 | 예 (영향 없음) | 0 | 0.29% | 0% | — | — | 0.62 | — | — | — |
| 2 | 제안 방식 | 3 | 예 | 220 | 0.50% | 0% | — | — | 0.62 | — | — | — |
| 2 | 제안 방식 | 4 | 예 (영향 없음) | 0 | 0.33% | 0% | — | — | 0.61 | — | — | — |
| 2 | 작업 분리 단독 | 1 | 예 (880초) | 880 | 2.54% | 2.63% | — | — | 1.83 | — | — | — |
| 2 | 작업 분리 단독 | 2 | 예 (1000초) | 1000 | 2.79% | 2.83% | — | — | 1.83 | — | — | — |
| 2 | 작업 분리 단독 | 3 | 아니오 | — | 2.83% | 3.02% | — | — | 1.83 | — | — | — |
| 2 | 무조치 | 1 | 예 | 100 | 1.92% | 1.72% | — | — | 1.82 | — | — | — |
| 2 | 무조치 | 2 | 예 | 960 | 2.25% | 2.34% | — | — | 1.82 | — | — | — |
| 2 | 무조치 | 3 | 예 | 240 | 1.67% | 1.86% | — | — | 1.81 | — | — | — |
| 3 | 제안 방식 | 1 | 예 | 120 | — | — | 12.9% | 617.7 | — | 예 | — | — |
| 3 | 제안 방식 | 2 | 예 | 460 | — | — | 12.2% | 604.7 | — | 예 | — | — |
| 3 | 제안 방식 | 3 | 예 | 120 | — | — | 11.3% | 596.4 | — | 예 | — | — |
| 3 | 무조치 | 1 | 아니오 | — | — | — | 100% | — | — | — | — | — |
| 3 | 무조치 | 2 | 아니오 | — | — | — | 100% | — | — | — | — | — |
| 3 | 무조치 | 3 | 아니오 | — | — | — | 100% | — | — | — | — | — |
| 4 | MachineHealthCheck 사용 | 1 | 예 | 20 | — | — | 76건 (관측 구간 5건) | — | — | — | 예 | 216.9 / 297.5 |
| 4 | MachineHealthCheck 사용 | 2 | 예 | 20 | — | — | 74건 (관측 구간 8건) | — | — | — | 예 | 207.4 / 282.6 |
| 4 | MachineHealthCheck 사용 | 3 | 예 | 20 | — | — | 76건 (관측 구간 10건) | — | — | — | 예 | 214.9 / 289.6 |
| 4 | MachineHealthCheck 미사용 | 1 | 예 | 20 | — | — | 82건 (관측 구간 13건) | — | — | — | 아니오 | — |
| 4 | MachineHealthCheck 미사용 | 2 | 예 | 20 | — | — | 79건 (관측 구간 15건) | — | — | — | 아니오 | — |
| 4 | MachineHealthCheck 미사용 | 3 | 예 | 20 | — | — | 76건 (관측 구간 11건) | — | — | — | 아니오 | — |
