# 관련연구 후보 — 작품 전체 주제 기준

- 조사일: 2026-09-26
- 기준: **OpenStack 기반 Kubernetes의 다계층 장애 관측·원인 파악·자동 대응·검증**. 중간 단계에 구현한 특정 시나리오를 검색 기준으로 삼지 않는다.
- 순위는 이번 작품 주제와의 관련성에 대한 잠정 판단이며 논문의 품질 순위나 최종 선정 결과가 아니다.
- 조사 상태: 아래 논문의 출판사·학술지·학회 원문 또는 초록을 확인했다. 문헌별 세부 방법·수치·한계는 함께 정독한 뒤 관련연구 본문에 사용한다.
- 양식: 국문·영문 논문 각 3편 이상. 기술 공식 문서는 별도 인용한다.

## 국문 논문

| 우선순위 | 논문 | 연구 문제·방법 | 작품 전체 주제와의 접점 및 읽을 때 확인할 점 |
|---|---|---|---|
| 1 · K1 | [김지용·김영종·김명호, 「오픈스택 환경에서의 서비스 메시 기반 통합적 모니터링 시스템」](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002561426), 2020 | OpenStack 인스턴스에서 실행되는 Kubernetes 워커의 자원·컨테이너·서비스 메시 지표를 수집해 대시보드에 함께 표시한다. | 제공받은 [원문](</Users/hyeonseungkim/Downloads/KCI_FI002561426.pdf>) 확인. VM–Node–Pod의 식별자 관계를 자동 분석하거나 장애를 자동 복구하는 연구로 소개하지 않는다. |
| 2 · K2 | [이찬휘·이근호, 「ARVIS: 클라우드 환경을 위한 자동화된 복원력 검증 및 개선 시스템」](https://journal.kci.go.kr/kiots/archive/articlePdf?artiId=ART003259742), 2025 | 장애 주입, 백업, 오케스트레이션, 복원력 지표를 묶은 검증–복구–평가 흐름을 제안한다. | **핵심 3편에서 제외 권장.** 실험 횟수와 소수점 성공률의 분모가 연결되지 않고, 결론의 프로토타입 구현 상태가 본문의 실험 서술과 어긋난다. 평가 항목을 소개할 때만 제한적으로 검토한다. |
| 3 · K3 | [박주원·김은혜·염재근·김성호, 「시스템 결함 분석을 위한 이벤트 로그 연관성에 관한 연구」](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002119546), 2016 | OpenStack의 시스템·서비스 로그를 통합하고 메시지 군집 및 상관 분석으로 오류 원인을 찾는다. | 운영자의 원인 추적 부담과 다계층 증거 연결의 근거. 로그를 이용한 진단 연구이며 복구 조치 자동화와는 범위가 다르다. |
| 4 · K4 | [장성일·김명호, 「오픈스택 기반 클라우드 컴퓨팅 시스템의 모니터링에 관한 연구」](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002579839), 2020 | VM 중심 지표만으로 부족한 compute·스토리지·네트워크 자원 풀 관측을 위해 수집 에이전트 구조를 제안한다. | IaaS 계층의 관측 범위를 살필 수 있다. K1과 관측 주제가 겹치므로 둘 다 핵심 문헌에 넣을지는 원문 비교 후 결정. |
| 5 · K5 | [권민호·이명준, 「BR2K: 쿠버네티스를 이용한 블록체인 서비스 복제 및 복구 기법」](https://journal.kci.go.kr/jksci/archive/articlePdf?artiId=ART002639420), 2020 | Kubernetes를 이용해 상태가 있는 블록체인 응용 서비스를 복제하고 장애 후 복구하는 기법을 제안한다. | 응용 서비스 복구 절차라는 접점이 있다. 블록체인 도메인·상태 복제 요구가 작품의 일반적인 다계층 장애 대응과 얼마나 다른지 검토한다. |
| 6 · K6 | [권민호·이명준, 「블록체인 응용 서비스의 견고성을 제고하기 위한 확장된 BR2K 기법」](https://journal.kci.go.kr/jksci/archive/articlePdf?artiId=ART002814640), 2022 | 12개 VM의 Kubernetes 환경에서 리더 실행 노드를 반복 중지하고, 서비스 중단 시간·요청 처리·복제 상태 일치를 측정한다. | **핵심 후보에서 제외.** 연구의 중심이 블록체인 서비스의 상태 복제·레지스트리·리더 전환이므로 작품 전체 주제와의 접점이 좁다. |
| 신규 · K7 | [이장원·김영한, 「오픈소스 MANO에서의 자동 복원 기능 분석」](https://journal-home.s3.ap-northeast-2.amazonaws.com/site/2020kics/presentation/0606.pdf), 2020 | OpenStack Tacker와 Fenix의 힐링·스케일링·이전 절차를 분석하고, Kubernetes를 포함한 복원 워크플로에 필요한 기능을 제안한다. | OpenStack 쪽 복구 조정 설계와 직접 관련되지만 NFV/VNF 관리가 중심이다. 2쪽 학회 발표문이며 새 기능의 구현·정량 실험은 없다. |
| 신규 · K8 | [박신영·김병권·배유진·심석인, 「Kubernetes를 활용한 멀티 클라우드 모니터링 솔루션」](https://sigsoft.or.kr/wp-content/uploads/2022/02/KCSE2022-proceedings-v5.pdf), 2022 | AWS·Azure·GCP의 Kubernetes 클러스터를 통합 관측하고, 한 클라우드 장애 시 다른 클라우드에서 서비스를 자동 복구하는 대시보드를 제안·구현한다. | **국문 세 번째 문헌으로 선정.** 장애 감지→자동 조치가 작품 주제와 맞는다. 다만 전체 클라우드 간 전환이라 OpenStack 내부 VM·Node 복구와 대상이 다르고, 정량 성능 근거는 추가 확인이 필요하다. |
| 신규 · K9 | [성찬민·최광미·김남호, 「Dependency Graph와 LLM을 결합한 쿠버네티스 장애 근본 원인 자동 분석 시스템」](https://kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003357552), 2026 | Kubernetes API의 13종 자원으로 의존성 그래프를 만들고 20개 장애 시나리오로 진단을 평가한다. | Kubernetes 장애 자체를 연구하므로 주제 적합성이 높다. 복구 실행은 없고 K3의 진단 역할과 겹친다. KCI 초록만 확인했으므로 세부 실험은 원문 확인 전까지 보류한다. |

## 영문 논문

| 우선순위 | 논문 | 연구 문제·방법 | 작품 전체 주제와의 접점 및 읽을 때 확인할 점 |
|---|---|---|---|
| 1 · E1 | [Yang and Kim, “Design and Implementation of Fast Fault Detection in Cloud Infrastructure for Containerized IoT Services”](https://pmc.ncbi.nlm.nih.gov/articles/PMC7472316/), *Sensors* 20(16), 4592, 2020 | OpenStack의 VM 장애 정보를 Kubernetes에 전달하는 Fast Fault Detection Manager를 설계·구현하고 탐지 시간을 평가한다. | 두 관리 계층을 실제로 연결한다는 점에서 가장 직접적이다. 탐지 개선과 다양한 장애별 대응 자동화의 범위를 구분해 읽는다. |
| 2 · E2 | [Vayghan et al., “A Kubernetes controller for managing the availability of elastic microservice based stateful applications”](https://www.sciencedirect.com/science/article/pii/S0164121221000212), *Journal of Systems and Software* 175, 110924, 2021 | Kubernetes의 기본 수리 동작에 상태 복제와 서비스 경로 전환을 보완하는 제어기를 제안한다. | 기본 self-healing 바깥의 대응 모듈 설계 사례. 상태 저장 응용에 특화된 제어 조건을 일반 장애 정책과 구분한다. |
| 3 · E3 | [Xiang et al., “Debugging OpenStack Problems Using a State Graph Approach”](https://people.iiis.tsinghua.edu.cn/~weixu/Krvdro9c/apsys-xiang.pdf), *APSys*, 2016 | OpenStack–Ceph의 런타임 상태와 이벤트 관계를 그래프로 묶어 VM 문제 추적과 이상 탐지에 활용한다. | 서로 다른 인프라 자원의 관계를 따라가는 진단 방법. Kubernetes 객체는 대상에 포함하지 않으며 진단 뒤 자동 조치가 어디까지 있는지 확인한다. |
| 4 · E4 | [Cotroneo et al., “How Bad Can a Bug Get? An Empirical Analysis of Software Failures in the OpenStack Cloud Computing Platform”](https://arxiv.org/abs/1907.04055), *ESEC/FSE*, 2019 | Nova·Cinder·Neutron에 결함을 주입해 오류 통지, 자원 상태 불일치, 구성 요소 간 전파를 분석한다. | OpenStack API 성공만으로 자원 정상 상태를 단정하기 어려운 배경. 논문은 자동 복구 모듈보다 장애 영향의 실증 분석이다. |
| 5 · E5 | [Nikolaidis et al., “Frisbee: automated testing of Cloud-native applications in Kubernetes”](https://arxiv.org/abs/2109.10727), 2021 공개본 | 선언형으로 배포·워크로드·장애·기대 동작을 정의하고 자동 검증하는 도구를 제안한다. | 대표 장애 유형별 대응 절차를 반복 검증하는 방법론. 정식 게재 여부와 논문 수 인정 범위를 최종 선정 전에 확인한다. |
| 6 · E6 | [Barletta et al., “Mutiny! How does Kubernetes fail, and what can we do about it?”](https://experts.illinois.edu/en/publications/mutiny-how-does-kubernetes-fail-and-what-can-we-do-about-it/), *DSN*, 2024 | 실제 Kubernetes 장애 사례를 분류하고 클러스터 상태 저장소 결함을 주입해 전파 양상을 조사한다. | Kubernetes 운영 계층의 장애 분류와 장애 주입 근거. 제어 평면 내부 결함이 중심이므로 작품의 VM·가상 네트워크 장애와 범위를 구분한다. |
| 7 · E7 | [Flora et al., “A Study on the Aging and Fault Tolerance of Microservices in Kubernetes”](https://doi.org/10.1109/ACCESS.2022.3231191), *IEEE Access* 10, 132786–132799, 2022 | TeaStore·SockShop에서 부하·응용 결함을 주입하고 Kubernetes probe의 탐지 범위를 실험한다. | Kubernetes 기본 자가복구의 적용 범위와 한계를 실증적으로 설명할 근거. 소프트웨어 노화·응용 결함 실험이므로 VM·Node 장애의 직접적인 실험 결과로 일반화하지 않는다. |

## 중간보고서 3+3 조합 — 2026-09-26 선정

- **소거: E3, K5, K2, K6.** E3와 K3은 OpenStack 장애 진단이라는 목적이 겹친다. K3의 로그 상관 분석을 남기면 국문 3편 요건을 충족하면서 K1의 지표 시각화와 다른 증거 유형을 설명할 수 있다. E3의 상태 그래프는 강한 후보지만 이번 6편 안에서는 제외한다.
- K5와 E2는 상태 저장 서비스의 복제·전환이 겹친다. K5는 블록체인 요청·상태 일관성에 특화되어 있고 서비스 전체 재배포 절차에는 관리자가 개입한다. 작품의 일반적인 장애 대응 모듈 설명에는 자동 서비스 전환을 구현한 E2가 더 적합하다.
- K2는 제안하는 평가 틀 자체는 주제에 맞지만, 본문 수치의 집계 기준과 구현 상태를 안전하게 확인할 수 없어 핵심 문헌으로 유지하지 않는다. K6는 블록체인 전용 설계가 중심이라 주제 적합성이 낮아 제외한다.
- **국문 선정:** K1 관측·시각화, K3 OpenStack 로그 기반 진단, K8 Kubernetes 서비스의 장애 감지 후 클라우드 간 자동 복구. K8의 상세 구현과 성능 수치는 원문 확인 후 본문에 인용한다.
- **영문:** E1 OpenStack VM 장애 신호의 Kubernetes 전달, E2 Kubernetes 서비스 복구 제어, E7 Kubernetes 기본 probe·자가복구 범위의 실험적 평가.
- E7은 기존 E4(OpenStack 내부 소프트웨어 결함의 전파), E6(Kubernetes 상태 저장소 결함)보다 이번 작품의 기본 자가복구 한계를 설명하는 데 직접적이다. 단, E7의 실험을 VM·Node·네트워크 전체에 대한 결과로 확대하지 않는다.
- K7은 OpenStack 복원 절차에 더 가깝지만 NFV 중심의 설계 분석이고 실험이 없다. K9는 Kubernetes 장애 시나리오 실험이 있지만 복구 조치가 없고 K3과 진단 역할이 겹친다. 두 편은 예비 후보로 남긴다.

### 여섯 편의 인용 역할과 확신도

확신도는 논문의 원문이 지정한 역할을 **중간보고서에서 안전하게 인용할 수 있는 정도에 대한 주관적 판단**이며, 연구 품질이나 주제 관련성의 정량 점수가 아니다.

| 논문 | 중간보고서에서 맡길 역할 | 확신도 | 인용 경계 |
|---|---|---:|---|
| K1 | OpenStack 인스턴스에서 실행되는 Kubernetes 워커·컨테이너·서비스 메시 지표의 통합 시각화 | 97% | 자원 식별자 자동 연관·원인 진단·복구로 확대하지 않음 |
| K3 | OpenStack 시스템·서비스 이벤트 로그를 모아 연관성을 분석하는 진단 | 92% | Kubernetes 객체 진단 또는 복구 자동화로 확대하지 않음 |
| K8 | Kubernetes 서비스 장애 감지 후 다른 클라우드에서 자동 복구하는 모듈 사례 | 원문 세부 확인 전 | 전체 클라우드 간 전환을 OpenStack 내부 VM 복구와 동일시하지 않음. 정량 평가 수치는 검증 전 인용하지 않음 |
| E1 | OpenStack VM 장애 신호를 Kubernetes에 전달하는 계층 간 탐지 연동 | 98% | 다양한 장애별 복구 모듈 구현으로 확대하지 않음 |
| E2 | Kubernetes 제어기의 상태 저장 서비스 자동 전환·가용성 회복 | 96% | 범용 VM·네트워크 장애 복구로 확대하지 않음 |
| E7 | 구성된 Kubernetes probe가 응용 결함·소프트웨어 노화를 놓칠 수 있음을 실험으로 평가 | 90% | Node·VM 장애에 대한 실험 결과나 Kubernetes 자가복구 전체의 실패로 일반화하지 않음 |

## 정독·선정 기준

1. 논문의 **탐지 대상 계층**과 **복구 제어 대상 계층**을 분리해 적는다.
2. 사용하는 데이터가 지표, 로그, 이벤트, 자원 관계 중 무엇인지 기록한다.
3. 실제 자동 조치를 구현했는지, 진단·모니터링 또는 실험 도구만 제안했는지 구분한다.
4. 장애 주입 조건과 성공 판정이 어떤 서비스·인프라 상태를 확인하는지 비교한다.
5. 같은 문제를 다룬 후속 연구와 범위 중복 여부, 정식 게재 정보, 원문 접근성을 확인한다.

현재 중간보고서 본문을 위한 **선정 조합**은 위의 **K1·K3·K8 + E1·E2·E7**이다. K8의 원문 상세와 검증 근거는 본문 서술 전에 확인한다. K7과 K9는 예비 후보로 남긴다. 본문에 넣을 세부 실험 조건·수치는 각 원문과 다시 대조한다.
