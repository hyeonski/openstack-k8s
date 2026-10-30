"""최종보고서 v4 그림 10개. 실행: python generate_figures_v4.py (matplotlib 필요).
수치: final-report-draft.md 표 4-2, 4-3, 4-5 및 4.3.4절.
원본 SVG는 편집 가능한 text, PNG는 동일한 물리 크기와 300 dpi.
"""
from pathlib import Path
import os
import sys
os.environ.setdefault('MPLCONFIGDIR', '/tmp/final-report-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Rectangle, FancyArrowPatch
import numpy as np

OUT = Path(__file__).resolve().parents[1]
FONT = Path(os.environ.get('REPORT_FONT', '/Applications/Microsoft Word.app/Contents/Resources/DFonts/malgun.ttf'))
BOLD = FONT.with_name('malgunbd.ttf')
if not FONT.exists():
    raise FileNotFoundError('맑은 고딕 파일 경로를 REPORT_FONT 환경 변수로 지정하십시오.')
fm.fontManager.addfont(str(FONT))
if BOLD.exists(): fm.fontManager.addfont(str(BOLD))
plt.rcParams.update({'font.family':fm.FontProperties(fname=FONT).get_name(), 'font.size':9.5,
 'svg.fonttype':'none', 'axes.unicode_minus':False, 'axes.linewidth':.7,
 'savefig.facecolor':'white','hatch.linewidth':.5})
INK='#252525'; GRAY='#eeeeee'; ACCENT='#315f7c'; EDGE='#666666'
TEXTS=[]

def canvas(height, coord_height=None):
    f=plt.figure(figsize=(15/2.54,height/2.54));a=f.add_axes([0,0,1,1]);a.set(xlim=(0,15),ylim=(coord_height or height,0));a.axis('off');return f,a

def text(a,x,y,s,size=9.5,bold=False,ha='center',color=INK):
    t=a.text(x,y,s,fontsize=size,ha=ha,va='center',color=color,fontweight='bold' if bold else 'normal',linespacing=1.28)
    TEXTS.append(t);return t

def box(a,x,y,w,h,s,fill='white',accent=False,size=9.5):
    a.add_patch(Rectangle((x,y),w,h,facecolor=fill,edgecolor=ACCENT if accent else EDGE,linewidth=1 if accent else .7))
    if s:text(a,x+w/2,y+h/2,s,size)
    return (x,y,w,h)

def line(a,pts,dash=False,color=EDGE):
    a.plot(*zip(*pts),color=color,lw=.8,ls='--' if dash else '-')

def arrow(a,start,end,via=None,dash=False,color=INK):
    pts=[start]+(via or [])+[end]
    if len(pts)>2:line(a,pts[:-1],dash,color)
    a.add_patch(FancyArrowPatch(pts[-2],end,arrowstyle='-|>',mutation_scale=8,lw=.8,color=color,linestyle='--' if dash else '-',shrinkA=0,shrinkB=1))

def save(f,n):
    if len(sys.argv)>1 and n not in sys.argv[1:]:
        plt.close(f);return
    f.canvas.draw();renderer=f.canvas.get_renderer();fw,fh=f.canvas.get_width_height()
    for t in f.findobj(matplotlib.text.Text):
        if not t.get_visible() or not t.get_text(): continue
        bb=t.get_window_extent(renderer)
        if bb.x0 < -1 or bb.y0 < -1 or bb.x1 > fw+1 or bb.y1 > fh+1:
            raise ValueError(f'{n}: 글자 경계 초과 {t.get_text()} {bb}')
        if t.get_fontsize()<9: raise ValueError(f'{n}: 9pt 미만')
    f.savefig(OUT/f'fig-v4-{n}.svg',format='svg',metadata={'Date':None})
    f.savefig(OUT/f'fig-v4-{n}.png',dpi=300)
    print(n,'15 x',round(f.get_figheight()*2.54,2),'cm',FONT.name)
    plt.close(f)

# 1-1 is unchanged; keep the original pixels, vector content, and physical size.
import shutil
for ext in ['svg','png']:shutil.copyfile(OUT/f'fig-1-1.{ext}',OUT/f'fig-v4-1-1.{ext}')
print('1-1 15 x 9.5 cm malgun.ttf (unchanged)')

# 3-1: host deployment on the left, resource relationships on the right.
f,a=canvas(9)
for y,title,left,right in [(.35,'controller','OpenStack\n제어 서비스','kind management\n클러스터'),(3.15,'compute 호스트 1','control plane VM','재배치 목적지\nworker VM'),(5.95,'compute 호스트 2','서비스의 원래\nworker VM','시나리오 1\n경쟁 VM')]:
    box(a,.15,y,6.75,2.5,'',GRAY)
    text(a,3.525,y+.4,title,bold=True,size=9)
    box(a,.4,y+.85,3,1.35,left,size=9)
    box(a,3.65,y+.85,3,1.35,right,size=9)
box(a,7.55,.3,4.6,1.0,'Service · Deployment\n· StatefulSet',GRAY,size=9)
for y,label in [(1.9,'Pod'),(3.15,'Node'),(4.4,'Machine'),(5.65,'Nova VM'),(7.9,'compute 호스트')]:box(a,7.9,y,3.85,.7,label,accent=label=='Nova VM',size=9)
for y,end in [(1.3,1.9),(2.6,3.15),(3.85,4.4),(5.1,5.65),(6.35,7.9)]:arrow(a,(9.825,y),(9.825,end))
for y,label in [(2.88,'nodeName'),(4.13,'providerID'),(5.38,'providerID')]:text(a,10.05,y,label,ha='left',size=9)
box(a,12.75,4.9,2.1,1.0,'Neutron\nport',GRAY,size=9)
box(a,12.75,6.9,2.1,1.0,'Cinder\nvolume',GRAY,size=9)
arrow(a,(11.75,5.85),(12.75,5.4),[(12.25,5.85),(12.25,5.4)])
text(a,13.5,4.55,'device_id',size=9)
arrow(a,(11.75,6.15),(12.75,7.4),[(12.25,6.15),(12.25,7.4)])
text(a,13.5,8.45,'attachment\nserver_id',size=9)
save(f,'3-1')

f,a=canvas(8, coord_height=10)
# 3.1절의 Monitor / Analyze·Plan / Execute 대응과 다음 관측 순환.
for x,eng,label in [(.35,'Monitor','자원 관계\n확인'),(4.1,'Analyze·Plan','조치 조건\n판단'),(7.85,'Execute','대상 조치'),(11.6,'다음 순환의 Monitor\nKnowledge 갱신','결과 확인')]:
    text(a,x+1.5,1.35,eng,size=9);box(a,x,2.15,3,1.4,label,GRAY)
for x in [3.35,7.1,10.85]:arrow(a,(x,2.85),(x+.75,2.85))
# 외곽으로 돌아오는 순환 화살표는 상단 대응 글자와 겹치지 않는다.
arrow(a,(14.6,2.85),(.35,2.85),[(14.85,2.85),(14.85,.3),(.15,.3),(.15,2.85)])
box(a,3.9,4.35,3.4,1,'보류 기록 후 종료');arrow(a,(5.6,3.55),(5.6,4.35))
box(a,7.65,4.35,3.4,2.5,'의도 기록\n↓\n조건부 변경\n↓\n적용 확인',size=9)
line(a,[(9.35,3.55),(9.35,4.35)],dash=True)
box(a,11.4,4.35,3.4,2.5,'서비스\n데이터\n용량',size=9.5);line(a,[(13.1,3.55),(13.1,4.35)],dash=True)
box(a,.65,8.8,13.7,.85,'공유 Knowledge',GRAY,accent=True)
for x,y in [(1.85,3.55),(5.6,5.35),(9.35,6.85)]:line(a,[(x,y),(x,8.8)],dash=True)
arrow(a,(13.1,6.85),(13.1,8.8),dash=True)
save(f,'3-2')

f,a=canvas(8, coord_height=10.6)
box(a,3.9,.45,6,1.4,'진단 반복 루프\n60초 창, 최대 6회',GRAY)
box(a,3.9,3.35,6,1.05,'목적지 후보 필터',GRAY)
box(a,3.9,5.15,6,1.05,'Deployment patch',GRAY)
box(a,3.9,6.95,6,1.4,'안정화 루프\n60초 창, 최대 8회',GRAY)
arrow(a,(6.9,1.85),(6.9,3.35));text(a,7.15,2.65,'조건 충족',ha='left',size=9)
box(a,.25,2.5,2.8,1,'보류');arrow(a,(3.9,1.15),(1.65,2.5),[(1.65,1.15)])
text(a,2.75,1.95,'조건 부족',size=9)
arrow(a,(9.9,1.4),(9.9,.8),[(11.5,1.4),(11.5,.8)])
for y,end in [(4.4,5.15),(6.2,6.95)]:arrow(a,(6.9,y),(6.9,end))
arrow(a,(9.9,7.95),(9.9,7.35),[(11.5,7.95),(11.5,7.35)])
box(a,2,9.55,4.8,.7,'안정화 조건 충족',accent=True);box(a,8.1,9.55,4.8,.7,'검토 필요 종료')
arrow(a,(4.5,8.35),(4.5,9.55));arrow(a,(9.3,8.35),(9.3,9.55))
text(a,2.8,8.95,'3회 연속 정상',size=9)
text(a,11.4,8.95,'8회 안에 미충족',size=9)
save(f,'3-3')

f,a=canvas(7, coord_height=8.8)
line(a,[(7.5,.4),(7.5,8.4)],dash=True)
text(a,3.65,.65,'조치 전',bold=True);text(a,11.3,.65,'조치 후',bold=True)
box(a,.4,1.3,6.5,3.0,'',GRAY);text(a,3.65,1.85,'첫 worker 노드',bold=True)
box(a,.8,2.55,2.5,1,'API');box(a,4,2.55,2.5,1,'업로드')
box(a,8,1.3,3,3,'',GRAY);text(a,9.5,1.9,'첫 worker\n노드');box(a,8.35,2.7,2.3,1,'API')
box(a,11.45,1.3,3.15,4.7,'',GRAY);text(a,13.025,1.9,'두 번째\nworker 노드');box(a,11.8,2.7,2.45,1,'업로드')
box(a,11.75,4.35,2.55,1.05,'port\nQoS',accent=True);arrow(a,(13.025,3.7),(13.025,4.35))
box(a,1.6,7.15,4.1,1,'공유 출구',accent=True);box(a,9.2,7.15,4.1,1,'공유 출구',accent=True)
arrow(a,(2.05,3.55),(2.7,7.15),[(2.05,6.3),(2.7,6.3)]);arrow(a,(5.25,3.55),(4.6,7.15),[(5.25,6.3),(4.6,6.3)])
arrow(a,(9.5,3.7),(10.1,7.15),[(9.5,6.3),(10.1,6.3)]);arrow(a,(13.025,5.4),(12.4,7.15),[(13.025,6.3),(12.4,6.3)])
save(f,'3-4')

f,a=canvas(8, coord_height=11.5)
# 확인 두 단계를 같은 높이에 놓고, 중단 분기는 아래쪽에서 각각 진입한다.
ys=[.4,2.2,4,5.8,7.6]
for y,s in zip(ys,['장애 주입','NotReady','서비스 영향 확인','정지 요청','꺼짐 4조건 확인']):box(a,.4,y,5.2,1.1,s,GRAY)
for y,s in zip(ys[1:],['데이터 검증','새 Pod Ready','out-of-service taint','직전 재확인']):box(a,9.4,y,5.2,1.1,s,GRAY)
for y in ys[:-1]:arrow(a,(3,y+1.1),(3,y+1.8))
for y in ys[1:-1]:arrow(a,(12,y+1.8),(12,y+1.1))
arrow(a,(5.6,8.15),(9.4,8.15))
box(a,5.8,10.1,3.4,.95,'중단')
arrow(a,(3,8.7),(6.4,10.1));arrow(a,(12,8.7),(8.6,10.1))
text(a,3.4,9.65,'실패',size=9);text(a,11.6,9.65,'실패',size=9)
save(f,'3-5')

f,a=canvas(8, coord_height=9.7)
# 전체 평가 구성을 감싸는 바깥 틀은 유지한다.
box(a,.2,.65,14.6,8.65,'')
box(a,.65,1.25,4,1.0,'장애 주입기',accent=True)
box(a,9.8,1.25,4.5,1.0,'대응 정책',accent=True)
box(a,5.2,3.0,4.5,1.2,'대상 시스템\n(Kubernetes·OpenStack)',GRAY,size=9.5)
arrow(a,(2.65,2.25),(6.15,3.0));arrow(a,(12.05,2.25),(8.75,3.0))
box(a,.65,3.1,3.1,1,'외부 측정기',accent=True)
arrow(a,(3.75,3.6),(5.2,3.6));text(a,4.475,3.25,'요청',size=9)
box(a,.65,5.45,9.05,1.0,'원자료\n요청 원자료 · 사건 기록 · 상태 스냅샷',GRAY,size=9.5)
arrow(a,(2.2,4.1),(2.2,5.45));text(a,3.65,4.8,'요청 원자료',size=9)
arrow(a,(7.45,4.2),(7.45,5.45));text(a,10.1,4.8,'사건 기록·상태 스냅샷',size=9)
box(a,4.9,7.65,4.4,1,'독립 판정기',accent=True)
box(a,10.4,7.65,3.5,1,'결과표',GRAY)
arrow(a,(7.1,6.45),(7.1,7.65));arrow(a,(9.3,8.15),(10.4,8.15))
# 점선은 입력 화살표가 아니다. 정책의 자체 성공 표시가 배제됨을 명시한다.
line(a,[(14.3,1.75),(14.5,1.75),(14.5,7.1),(9.3,7.1),(9.3,7.65)],dash=True)
text(a,12.1,5.95,'정책의 성공 표시는\n판정에 사용하지 않음',size=9)
save(f,'3-6')

# 표 4-2 조치 후 SLO 위반율, 회차 순서 그대로. 기준선은 본문 0~0.67%.
CPU_POST = {'제안 방식':[0.14,0.12,0.08], '무조치':[2.44,2.63,2.59], '동일 노드 재시작':[2.80,2.24,3.54]}
f,ax=plt.subplots(figsize=(15/2.54,7/2.54));f.subplots_adjust(left=.15,right=.96,bottom=.2,top=.93)
ax.axhspan(0,.67,facecolor='#e8e8e8',edgecolor='#b0b0b0',hatch='///',lw=.5)
ax.text(1.9,.41,'주입 전 기준선 0~0.67%',ha='right',va='center',fontsize=9)
for i,(label,vals) in enumerate(CPU_POST.items()):
 for run,v in enumerate(vals):
    x=i+(run-1)*.13
    ax.plot(x,v,['o','s','^'][run],ms=5,color=ACCENT if i==0 else INK,mfc='white' if run==1 else (ACCENT if i==0 else INK),label=f'{run+1}회차' if i==0 else None)
    ax.annotate(f'{v:.2f}',(x,v),xytext=([ -13,0,13][run],12 if i==0 else (10 if run!=1 else -15)),textcoords='offset points',ha='center',fontsize=9)
ax.set(xticks=range(3),xticklabels=list(CPU_POST),xlim=(-.5,2.5),ylim=(-.05,4.05),ylabel='조치 후 SLO 위반율 (%)')
ax.set_yticks([0,1,2,3,4]);ax.grid(axis='y',lw=.4,color='#cccccc');ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
ax.legend(loc='upper left',frameon=False,ncols=3,fontsize=9,handletextpad=.25,columnspacing=.8)
save(f,'4-1')

# 표 4-3: (조치 후 위반율 %, 업로드 처리량 MB/s), 각 조건의 회차 순서.
NET_POST={'제안 방식':[(0,.63),(0,.62),(0,.62),(0,.61)],'작업 분리 단독':[(2.63,1.83),(2.83,1.83),(3.02,1.83)],'무조치':[(1.72,1.82),(2.34,1.82),(1.86,1.81)]}
f,ax=plt.subplots(figsize=(15/2.54,7/2.54));f.subplots_adjust(left=.11,right=.89,bottom=.27,top=.83);other=ax.twinx()
xs=[];vs=[];ts=[];labels=[];centers=[];pos=0
for name,vals in NET_POST.items():
 start=pos
 for i,(v,t) in enumerate(vals):xs.append(pos);vs.append(v);ts.append(t);labels.append(str(i+1));pos+=1
 centers.append((name,(start+pos-1)/2));pos+=.65
b=ax.bar(np.array(xs)-.19,vs,.36,color=ACCENT,label='조치 후 SLO 위반율 (%)')
c=other.bar(np.array(xs)+.19,ts,.36,facecolor='white',edgecolor=INK,hatch='////',lw=.6,label='업로드 처리량 (MB/s)')
for x,v,t in zip(xs,vs,ts):
 ax.text(x-.19,v+.08,f'{v:g}',ha='center',va='bottom',fontsize=9,rotation=90 if v else 0)
 other.text(x+.19,t+.06,f'{t:.2f}',ha='center',va='bottom',fontsize=9,rotation=90)
ax.set(ylim=(0,3.8),ylabel='위반율 (%)',xticks=xs,xticklabels=labels,xlim=(-.7,pos-.9));other.set(ylim=(0,2.5),ylabel='처리량 (MB/s)')
ax.set_yticks([0,1,2,3]);other.set_yticks([0,.5,1,1.5,2,2.5])
for name,center in centers:ax.text(center,-.90,name,ha='center',va='center',fontsize=9.5)
ax.set_xlabel('회차',labelpad=20);ax.grid(axis='y',lw=.4,color='#cccccc');ax.set_axisbelow(True)
ax.spines['top'].set_visible(False);other.spines['top'].set_visible(False)
f.legend([b,c],['조치 후 SLO 위반율 (%)','업로드 처리량 (MB/s)'],loc='upper center',bbox_to_anchor=(.5,.985),frameon=False,fontsize=9,ncols=1)
save(f,'4-2')

# 표 4-5 원값. 회차별 정확한 첫/마지막 실패 시각은 표에 없어 임의로 생성하지 않는다.
SHUTOFF_USED=[80.6,75.2,74.7]; SHUTOFF_UNUSED=[77.7,73.0,74.9]
FAIL_COUNT_USED=[76,74,76]; FAIL_COUNT_UNUSED=[82,79,76]
OUTAGE_USED=[75.0,73.0,75.0]; OUTAGE_UNUSED=[81.0,78.0,75.0]
CAPACITY_FROM_SHUTOFF=[216.9,207.4,214.9]
CAPACITY_FROM_STOP=[297.5,282.6,289.6]
# 4.3.4 및 구성 요소: 요청 실패 약10초 시작·73~81초 지속,
# SHUTOFF 후5~15초 내 마지막 실패. 120초는 비정상 상태 지속 조건이며
# 정지 요청 기준의 실제 판정시각이 아니다. 따라서 절대시간 축에120초 점을 찍지 않는다.
f,a=canvas(9, coord_height=11.8)
x0,x1=.9,14.15
X=lambda seconds:x0+(x1-x0)*seconds/320
text(a,.35,.35,'서비스 요청',bold=True,ha='left')
line(a,[(X(0),3.15),(X(320),3.15)])
for v in [0,50,100,150,200,250,300]:
    line(a,[(X(v),3.05),(X(v),3.25)]);text(a,X(v),3.55,str(v),size=9)
text(a,.9,4.0,'정지 요청',size=9)
text(a,9.3,4.0,'정지 요청 후 경과 시간 (초)',size=9)
# 끝 시각은 회차별 값이 제시되지 않았다. 빗금은 SHUTOFF+5~15초의 범위.
# 범위를 각 끝값으로 결합한 envelope이며 단일 회차 중단시간을 뜻하지 않는다.
failure_end_low=min(SHUTOFF_USED+SHUTOFF_UNUSED)+5
failure_end_high=max(SHUTOFF_USED+SHUTOFF_UNUSED)+15
box(a,X(10),2.45,X(failure_end_low)-X(10),.45,'',fill='#b5c6d0',accent=True)
a.add_patch(Rectangle((X(failure_end_low),2.45),X(failure_end_high)-X(failure_end_low),.45,facecolor='white',edgecolor=ACCENT,hatch='////',lw=.6))
text(a,1.7,1.7,'시작 약 10초',size=9)
arrow(a,(X(10),2.0),(X(10),2.45))
text(a,5.1,.95,'VM SHUTOFF 확인·관측 구간 시작\n73~81초',size=9)
arrow(a,(X(77),1.5),(X(77),2.2))
for shut in SHUTOFF_USED+SHUTOFF_UNUSED:line(a,[(X(shut),2.2),(X(shut),3.25)],dash=True,color=ACCENT)
text(a,8.1,2.15,'끝: SHUTOFF 후 5~15초',size=9)
arrow(a,(5.65,2.35),(X(failure_end_high),2.65))
# 용량은 모든 회차에서 2대로 시작. 실제 회차별 SHUTOFF/복원 시각으로 계단을 그린다.
text(a,.35,4.65,'MachineHealthCheck 사용',bold=True,ha='left',size=9.5)
text(a,8.15,5.45,'MachineHealthCheck 판정\n(Node 비정상 120초 지속)\n→ Machine 교체 → 새 Node Ready',size=9)
capmin,capmax=min(CAPACITY_FROM_STOP),max(CAPACITY_FROM_STOP)
a.add_patch(Rectangle((X(capmin),6.3),X(capmax)-X(capmin),1.6,facecolor='#eeeeee',edgecolor=EDGE,hatch='////',lw=.5))
text(a,13.05,5.2,'용량 복원\n283~298초',size=9)
arrow(a,(X(290),5.8),(X(290),6.3))
for shut,cap in zip(SHUTOFF_USED,CAPACITY_FROM_STOP):
    line(a,[(X(0),6.55),(X(shut),6.55),(X(shut),7.65),(X(cap),7.65),(X(cap),6.55),(X(320),6.55)],color=ACCENT)
text(a,.4,6.55,'2대',size=9);text(a,.4,7.65,'1대',size=9)
text(a,.35,8.65,'MachineHealthCheck 미사용',bold=True,ha='left',size=9.5)
for shut in SHUTOFF_UNUSED:
    line(a,[(X(0),9.25),(X(shut),9.25),(X(shut),10.35),(X(320),10.35)],dash=True)
text(a,.4,9.25,'2대',size=9);text(a,.4,10.35,'1대',size=9)
text(a,8.6,9.95,'SHUTOFF 이후 worker 노드 1대 유지',size=9)
save(f,'4-3')
