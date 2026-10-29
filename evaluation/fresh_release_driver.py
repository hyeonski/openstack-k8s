"""Sequential CLI driver for the already authorized release; no retries or tuning.

Invoke only after reviewing DEV. Every case runs and reports separately. All
research and operational gates remain in the frozen CLI. This file is an
operator script, not experiment policy or an independent result source.
"""
from pathlib import Path
import datetime as dt
import json,os,subprocess,sys,time,traceback,fcntl,hashlib
ROOT=Path.cwd();sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_campaign import check_frozen, operational_failure_action
from fresh_operations import BedLedger
from fresh_host_lifetime import effective_host_deadline, validate_host_lifetime_policy
from fresh_evidence import epoch,utc
from lib.state import atomic_json
BASE=ROOT/'artifacts/fresh-evaluation-measurement-repaired-2026-10-27'
ACTIVE_PATH=BASE/'transport-release-active.json'
ACTIVE=json.loads(ACTIVE_PATH.read_text()) if ACTIVE_PATH.exists() else None
PROFILE=Path(ACTIVE['profile']) if ACTIVE else ROOT/'.state/cloud-gcp-amd64-greenfield/evaluation-profiles/fresh-20261027-measurement-repaired.json'
P=json.loads(PROFILE.read_text());BED=Path(P['operations']['artifact_root'])
AUTH=json.loads((BASE/'restart-authorization.json').read_text())
assert AUTH['scope']=={'preparation':8,'main':29}
assert hashlib.sha256(PROFILE.read_bytes()).hexdigest()==(ACTIVE['profile_sha256'] if ACTIVE else AUTH['profile_sha256'])
TRANSITION=None
if ACTIVE:
 from fresh_transport_release import audit_transition, historical_campaign, supplemental_origins, supplemental_plan
 assert hashlib.sha256(Path(ACTIVE['authorization']).read_bytes()).hexdigest()==ACTIVE['authorization_sha256']
 TRANSITION=json.loads(Path(ACTIVE['authorization']).read_text())
 audit_transition(P,TRANSITION,ROOT)
assert hashlib.sha256((Path(AUTH['prior_root'])/'HOLD-NEXT-EXPERIMENTS.json').read_bytes()).hexdigest()==AUTH['old_hold_sha256']
from fresh_failure_policy import next_action
class OperationalPause(RuntimeError):pass

if (BASE/'HOLD-NEXT-EXPERIMENTS.json').exists():
 raise SystemExit('New session HOLD blocks entry; preserve original HOLD separately')
os.environ.setdefault('ENV_OVERRIDE_FILE',P['operations']['environment_override'])
validate_host_lifetime_policy(P,live=True)
os.environ['FRESH_HOST_RUNTIME_LIMIT']='disabled'
os.environ['FRESH_OPERATIONAL_HARD_STOP_UTC']=P['operations']['hard_stop_utc']
os.environ['FRESH_TIME_POLICY']='cost-bounded-targets-only'
OPS=BASE/'operations';DEV=ROOT/'artifacts/fresh-evaluation-development-calibrated-2026-10-26/dev-v1'
REG=BASE/'release-registry.json';DATA={'profile':str(PROFILE),'campaigns':{},'events':[],'pilot_no_go':{}}
if REG.exists():DATA=json.loads(REG.read_text())
DATA['profile']=str(PROFILE)

def campaign_files():
 paths=set(BED.glob('*/campaign.json'))
 if TRANSITION:paths.update(Path(row['path'])/'campaign.json' for row in TRANSITION['prior_campaigns'].values())
 return sorted(paths)

def planning_manifest(path):
 if TRANSITION:
  for row in TRANSITION['prior_campaigns'].values():
   if Path(row['path']).resolve()==Path(path).resolve():
    return historical_campaign(path,row['frozen_manifest_sha256'])
 return check_frozen(path,current=True)
LOCK=(BASE/'operator-driver.lock').open('a+');fcntl.flock(LOCK,fcntl.LOCK_EX|fcntl.LOCK_NB)
DATA['operator_pid']=os.getpid()
DATA['driver_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
if Path('/usr/bin/caffeinate').is_file():
 awake=subprocess.Popen(['/usr/bin/caffeinate','-is','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 DATA['awake_guard_pid']=awake.pid
# Historical evidence is reviewed against its own immutable inputs, never
# re-labelled as a current-source DEV or re-reported through a source bypass.
def review_dev():
 from fresh_campaign import evidence_hashes
 from fresh_analysis import judge
 prior=check_frozen(DEV)
 assert prior['git_head']=='6730ecfa68a0628b83b0f9e5924fffcbf72a95ae'
 unchanged=('kubernetes/graduation-s1/app.py','kubernetes/graduation-s1/loadgen.py','evaluation/fresh_baseline.py','evaluation/fresh_analysis.py','evaluation/fresh_contract.py','evaluation/fresh_calibration.py')
 if TRANSITION and TRANSITION.get('kind') in ('user-authorized-stability-continuation-v4','user-authorized-inventory-continuation-v5','user-authorized-s1-read-continuation-v6','user-authorized-s3-capture-continuation-v7','user-authorized-dns-readiness-continuation-v8'):
  unchanged=tuple(n for n in unchanged if n not in ('evaluation/fresh_baseline.py','evaluation/fresh_analysis.py','evaluation/fresh_calibration.py'))
 for name in unchanged:
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==prior['source_sha256'][name],name
 case=prior['cases'][0];rows=[]
 for attempt in case['attempts']:
  path=DEV/attempt['path']
  assert attempt['state']=='VERIFIED'
  assert evidence_hashes(path)==attempt['evidence_sha256']
  judged=judge(path,case,prior['profile'])
  rows.append(dict(attempt=attempt['id'],**judged))
 value=dict(source_commit=prior['git_head'],reviewed_utc=utc(),primary_sample_count=0,run_results=rows,note='original-source evidence reuse; no old artifact rewritten; strict analysis recomputation; authorised stability sidecar equivalence required for v4')
 atomic_json(BASE/'reused-dev-review.json',value)
 return value


def save(stage,**fields):
 DATA['updated_utc']=utc();DATA['stage']=stage;DATA.update(fields);atomic_json(REG,DATA)
 progress=json.loads((BASE/'progress.json').read_text());ledger=BedLedger(P);ledger.save()
 results=[];injections=[];attempted=[]
 for campaign in campaign_files():
  manifest=json.loads(campaign.read_text())
  for case in manifest['cases']:
   for attempt in case.get('attempts',[]):
    attempted.append(case)
    path=campaign.parent/attempt['path']
    if (path/'judgement.json').exists():results.append((case,json.loads((path/'judgement.json').read_text())))
    for events in (path/'events.jsonl',):
     if events.exists():
      injections.extend(e['utc'] for e in map(json.loads,events.read_text().splitlines()) if e.get('kind')=='injection_applied')
 progress.update(preparation_attempted=sum(c['purpose'] in ('smoke','pilot') for c in attempted),preparation_valid=sum(c['purpose'] in ('smoke','pilot') and j['trial_valid'] is True for c,j in results),preparation_invalid=sum(c['purpose'] in ('smoke','pilot') and j['trial_valid'] is not True for c,j in results),main_attempted=sum(c['purpose']=='main' for c in attempted),first_injection_utc=min(injections) if injections else progress.get('first_injection_utc'))
 progress.update(main_valid=sum(c['purpose']=='main' and j['trial_valid'] is True for c,j in results),main_invalid=sum(c['purpose']=='main' and j['trial_valid'] is not True for c,j in results),supplemental_attempted=sum(c['purpose']=='supplemental' for c in attempted),supplemental_valid=sum(c['purpose']=='supplemental' and j['trial_valid'] is True for c,j in results),supplemental_invalid=sum(c['purpose']=='supplemental' and j['trial_valid'] is not True for c,j in results))
 progress.update(updated_utc=utc(),stage=stage,release_registry=str(REG),uptime_and_estimated_cost=ledger.data['usage'],**fields)
 atomic_json(BASE/'progress.json',progress)
 print(json.dumps({'utc':utc(),'stage':stage,**fields}),flush=True)

def cli(action,*extra,campaign=None):
 args=['bash',str(ROOT/'evaluation/graduation-evaluation.sh'),'--fresh',action]
 if campaign:args+=['--campaign',str(campaign)]
 args+=list(map(str,extra))
 def fingerprint():
  saved=Path(campaign)/'campaign.json' if campaign else None
  if not saved or not saved.exists():return None
  d=json.loads(saved.read_text())
  return [(c['id'],c['status'],[(a['id'],a['state']) for a in c.get('attempts',[])]) for c in d['cases']]
 before=fingerprint();admission_until=time.time()+120
 old_deadline=os.environ.get('FRESH_ADMISSION_DEADLINE_UTC')
 if action=='run':os.environ['FRESH_ADMISSION_DEADLINE_UTC']=str(admission_until)
 try:
  for attempt in range(1,2 if P['operations'].get('stability') else 4):
   log=BASE/('driver-command-'+str(time.time_ns())+'.log')
   DATA['events'].append({'utc':utc(),'argv':args,'log':str(log),'step_attempt':attempt})
   save('CLI '+action,current_campaign=str(campaign) if campaign else None,last_command_log=str(log))
   with log.open('w') as stream:
    with subprocess.Popen(args,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT) as process:
     while True:
      try:
       rc=process.wait(timeout=30);break
      except subprocess.TimeoutExpired:
       save('CLI '+action+' in progress',child_pid=process.pid)
   DATA['child_pid']=None
   if not rc:return
   text=log.read_text()
   transient=any(word in text for word in ('UNEXPECTED_EOF','Connection reset','Connection refused','Unable to connect','i/o timeout','TLS handshake','context deadline exceeded'))
   safe=action=='run' and before is not None and fingerprint()==before and transient and attempt<3 and time.time()<admission_until
   if not safe:raise RuntimeError(f'{action} exited {rc}; inspect {log}')
   DATA['events'].append({'utc':utc(),'kind':'bounded_read_only_admission_retry','operation':action,'attempt':attempt,'reason':'transient read error; exact case/attempt fingerprint unchanged; same cumulative120s deadline'})
   save('transient admission read error; retrying step only',last_step_retry=attempt)
 finally:
  if action=='run':
   if old_deadline is None:os.environ.pop('FRESH_ADMISSION_DEADLINE_UTC',None)
   else:os.environ['FRESH_ADMISSION_DEADLINE_UTC']=old_deadline


def environment(action):cli('environment-'+action,'--profile',PROFILE,campaign=OPS)

def planned_idle(now):return 0

def operational_gate(case=None):
 if (BASE/'REPAIR-REQUIRED.json').exists():raise OperationalPause('measurement repair remains pending')

def remaining_budget(label):
 # Preserve the registered nominal schedule and its 20%/session allowances.
 # Completed calibration/DEV/preparation are never counted as future work.
 completed=set();observed={};now=time.time()
 for saved in campaign_files():
  manifest=planning_manifest(saved.parent)
  if manifest.get('synthetic'):continue
  records=[json.loads(line) for line in (saved.parent/'attempts.jsonl').read_text().splitlines()] if (saved.parent/'attempts.jsonl').exists() else []
  for c in manifest['cases']:
   if c['status']=='finished':completed.add(c['id'])
   start=next((epoch(r['utc']) for r in records if r['case_id']==c['id'] and r['attempt_id']=='attempt-01' and r['state']=='started'),None)
   end=next((epoch(r['utc']) for r in records if r['case_id']==c['id'] and r['attempt_id']=='attempt-01' and r['state'] in ('finished','resumed_cleanup_only')),None)
   if start and end:observed[c['scenario']]=max(observed.get(c['scenario'],0),1.2*(end-start))
 nominal={'s1':44,'s2':37,'s3':32,'s4':37};pending=[c for c in P['cases'] if c['id'] not in completed]
 supplement_pending=[next(c for c in P['cases'] if c['id']==entry['origin']) for entry in supplemental_plan(TRANSITION) if entry['id'] not in completed] if TRANSITION else []
 seconds=sum(max(nominal[c['scenario']]*72,observed.get(c['scenario'],0)) for c in pending+supplement_pending)
 if TRANSITION and TRANSITION.get('kind')=='user-authorized-dns-readiness-continuation-v8':seconds+=600*len(supplement_pending)
 idle=planned_idle(now)
 lifecycle=P['operations']['single_host_lifecycle_estimate_seconds'] if pending or supplement_pending else P['operations']['host_shutdown_timeout_seconds']
 seconds+=idle+lifecycle
 ledger=BedLedger(P);ledger.save();usage=ledger.data['usage'];hard=epoch(P['operations']['hard_stop_utc'])
 projected=usage['estimated_cost_krw']+seconds/3600*P['operations']['cost_estimate']['bed_hour_krw']+seconds/86400*P['operations']['cost_estimate']['calendar_day_krw']
 DATA['observed_max_case_seconds']={k:v/1.2 for k,v in observed.items()}
 budget=dict(idle_seconds=idle,remaining_lifecycle_estimate_seconds=lifecycle,calendar_estimate_advisory=True,updated_utc=utc(),label=label,completed_registered_cases=len(completed),remaining_registered_cases=len(pending),supplemental_remaining=len(supplement_pending),remaining_plan_seconds=seconds,planned_finish_kst=dt.datetime.fromtimestamp(now+seconds,dt.timezone(dt.timedelta(hours=9))).isoformat(),calendar_margin_seconds=hard-now-seconds,soft_uptime_margin_after_plan_seconds=P['operations']['bed_uptime_soft_limit_seconds']-usage['bed_seconds']-seconds,projected_estimate_krw=projected,usage=usage,notes='case nominal or observed x1.2; one measured lifecycle25min, no fixed host rotation; scheduled idle included; total forecast advisory; phase deadlines and credit/cost gates remain; calendar/uptime advisory; completed work excluded; not Billing')
 prep_seconds=sum(max(nominal[c['scenario']]*72,observed.get(c['scenario'],0)) for c in pending if c['purpose']!='main')
 budget['first_main_forecast_kst']=dt.datetime.fromtimestamp(now+prep_seconds+(lifecycle if completed==set() else 0),dt.timezone(dt.timedelta(hours=9))).isoformat() if prep_seconds else ('main in progress or admitted' if pending else None)
 atomic_json(BASE/('remaining-budget-'+str(time.time_ns())+'.json'),budget);save('remaining work budget checked',remaining_budget=budget,first_main_forecast=budget['first_main_forecast_kst'],completion_forecast=budget['planned_finish_kst'])
 forward=ledger.forward_credit(seconds)
 if forward is not None:
  budget['forward_credit']=forward
  atomic_json(BASE/'latest-forward-credit.json',budget)
  if forward['margin_krw']<=0:raise OperationalPause('latest credit forward forecast cannot cover remaining authorised scope and reserves')
 if forward is None and projected>P['operations']['new_work_budget_krw']:
  raise OperationalPause('remaining authorised scope planning shortfall KRW '+str(round(projected-P['operations']['new_work_budget_krw']))+'; retain all pending cases and request budget decision before admission')
 if not ledger.budget_available():
  raise RuntimeError('actual accumulated planning cost limit reached; preserve pending scope')

def verify_headroom(force=False):
 record=json.loads((ROOT/'.state/cloud-gcp-amd64-greenfield/graduation-environment.json').read_text())
 if record.get('phase')!='ready':raise RuntimeError('environment readiness lost before admission')
 for h in record['final_hosts'].values():
  assert effective_host_deadline(P,h) is None,'disabled timer/cost-bounded contract mismatch'
 # Explicit targets-only approval: no elapsed-time gate and no forced rotation.


def frozen(name,stage,scenario,pilot=None,origin=None):
 path=BED/name
 if not (path/'campaign.json').exists():
  args=['--profile',PROFILE,'--stage',stage,'--scenario',scenario]
  if origin is not None:args+=['--supplemental-origin',origin]
  if TRANSITION:
   args+=['--transport-authorization',ACTIVE['authorization']]
   cli('freeze-transport',*args,campaign=path)
  else:
   if pilot:args+=['--pilot-campaign',pilot,'--policy-manifest',BED/'s1-pilot-v1/policy-manifest.json']
   cli('freeze',*args,campaign=path)
 DATA['campaigns'][name]=str(path);save('campaign frozen',current_campaign=str(path))
 return path

def measured(path):
 cli('report',campaign=path)
 out=json.loads((path/'fresh-report.json').read_text())
 DATA.setdefault('counts',{})[str(path)]=dict(stage=out['stage'],observed_first_attempts=sum(r['attempt']=='attempt-01' for r in out['run_results']),primary=out['primary_sample_count'],missingness=out['missingness'])
 save('case independently reported',current_campaign=str(path),preparation_completed=sum(v['observed_first_attempts'] for v in DATA['counts'].values() if v['stage']=='preparation'),main_completed=sum(v['observed_first_attempts'] for v in DATA['counts'].values() if v['stage']=='main'),primary_sample_count=sum(v['primary'] for v in DATA['counts'].values()))
 return out

def run_one(path):
 waiting=next(c for c in check_frozen(path)['cases'] if c['status']=='pending')
 operational_gate(waiting)
 remaining_budget('before next case')
 verify_headroom()
 before=check_frozen(path,current=True)
 pending=next(c for c in before['cases'] if c['status']=='pending')
 save('one case running',current_case=pending['id'],current_campaign=str(path))
 cli('run','--limit','1',campaign=path)
 out=measured(path)
 row=next(r for r in out['run_results'] if r['case_id']==pending['id'] and r['attempt']=='attempt-01')
 if not row['cleanup'] or row['safety'] is not True or not row['trial_valid']:
  action=operational_failure_action(row,cleanup_verified=row['cleanup'] is True,budget_available=BedLedger(P).budget_available())
  atomic_json(BASE/'REPAIR-REQUIRED.json',dict(utc=utc(),action=action,case=pending['id'],result=row,no_fault_replay=True))
  DATA['failure_action']=action
  # A scientific safety=false with verified owned cleanup pauses for review;
  # it does not end the newly authorised supplementary scope by itself.
  if action=='safe_shutdown' and (row['cleanup'] is not True or not BedLedger(P).budget_available()):
   environment('down')
  raise OperationalPause(action+': '+pending['id'])
 DATA['events'].append({'utc':utc(),'case':pending['id'],'judgement':{k:row[k] for k in ('trial_valid','fault_realized','impact_realized','recovered','safety','cleanup','v1_outcome')}})
 save('one case complete',current_case=pending['id'])
 return row

def run_pilot(s):
 if not (BED/(s+'-pilot-v1')/'campaign.json').exists():
  operational_gate(next(c for c in P['cases'] if c['scenario']==s and c['purpose']!='main'))
 path=frozen(s+'-pilot-v1','preparation',s)
 while any(c['status']=='pending' for c in check_frozen(path)['cases']):
  row=run_one(path)
  go=row['fault_realized'] is True and (row['mode'] not in ('P','P3600','on') or row['recovered'] is True) and (row['mode']!='V1' or row['v1_outcome']=='held')
  if not go:
   DATA['pilot_no_go'][s]={'case':row['case_id'],'mode':row['mode'],'fault_realized':row['fault_realized'],'recovered':row['recovered'],'v1_outcome':row['v1_outcome']}
  save('pilot go/no-go recorded',pilot_no_go=DATA['pilot_no_go'])
 return path

try:
 dev=review_dev()
 latest=dev['run_results'][-1] if dev['run_results'] else {}
 if dev['primary_sample_count']!=0 or latest.get('trial_valid') is not True or latest.get('safety') is not True or latest.get('cleanup') is not True:
  raise RuntimeError('DEV requires independent validity/safety/cleanup review before preparation')
 remaining_budget('after DEV')
 save('DEV reviewed; full pilot wave starting',dev_intervention_delivered=latest['metrics'].get('intervention_delivered'),dev_attempts_preserved=len(dev['run_results']))
 record=json.loads((ROOT/'.state/cloud-gcp-amd64-greenfield/graduation-environment.json').read_text())
 ledger=BedLedger(P)
 if not ledger.data['sessions'] or ledger.data['sessions'][-1].get('stopped'):
  environment('ensure')
 elif record.get('phase')!='ready':
  raise RuntimeError('active ledger without ready environment; reconcile startup without duplicate ensure')
 if not (BASE/'cadence-approved.json').exists():
  save('environment ready; read-only S4 cadence check running')
  command=['bash','-c','set -a; source scripts/lib/common.sh; set +a; export STATE_DIR; exec python3 evaluation/fresh_cadence.py']
  with (BASE/'cadence.log').open('a') as stream:
   rc=subprocess.call(command,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
  if rc or not (BASE/'cadence-approved.json').exists():raise OperationalPause('cadence verification requires investigation')
 pilots={s:Path(TRANSITION['prior_campaigns'][s+'-pilot-v1']['path']) for s in ('s4','s1','s2','s3')} if TRANSITION else {s:run_pilot(s) for s in ('s4','s1','s2','s3')}
 if TRANSITION:save('hash-bound preparation reuse approved; no preparation replay',transport_authorization=ACTIVE['authorization'],source_boundary=TRANSITION['boundary_case'])
 remaining_budget('after full pilot wave')
 if DATA['pilot_no_go']:
  save('pilot wave no-go; main blocked',pilot_no_go=DATA['pilot_no_go'])
 else:
  save('all pilot gates passed; main starting')
  for s in ('s1','s2','s3','s4'):
   if TRANSITION and not any(c['scenario']==s and c['id'] in TRANSITION['remaining_main_ids'] for c in P['cases']):continue
   operational_gate(next(c for c in P['cases'] if c['scenario']==s and c['purpose']=='main'))
   verify_headroom()
   path=frozen(s+('-main-transport-v2' if TRANSITION else '-main-v1'),'main',s,pilots[s]);previous=None
   for c in check_frozen(path)['cases']:
    if c['status']!='pending':previous=c['session'];continue
    if previous and previous!=c['session']:verify_headroom()
    run_one(path);previous=c['session']
   measured(path)
  observed_main={c['id'] for saved in campaign_files() for c in planning_manifest(saved.parent)['cases'] if c['purpose']=='main' and c.get('attempts') and c['attempts'][0]['state']=='VERIFIED'}
  assert observed_main=={c['id'] for c in P['cases'] if c['purpose']=='main'},'original main29 coverage incomplete'
  save('registered 29 main cases measured')
  if TRANSITION:
   for origin in supplemental_origins(TRANSITION):
    original=next(c for c in P['cases'] if c['id']==origin);scenario=original['scenario']
    same_scenario=[value for value in supplemental_origins(TRANSITION) if next(c for c in P['cases'] if c['id']==value)['scenario']==scenario]
    supplement_name=(origin if len(same_scenario)>1 else scenario)+'-supplement-transport-v2'
    supplement=frozen(supplement_name,'supplemental',scenario,pilots[scenario],origin=origin)
    if any(c['status']=='pending' for c in check_frozen(supplement)['cases']):run_one(supplement)
    measured(supplement)
    assert len(check_frozen(supplement)['cases'])==1 and sum(len(c.get('attempts',[])) for c in check_frozen(supplement)['cases'])==1,'exactly one authorised attempt per supplementary origin required'
   save('original main29 and all authorised supplementary measurements sealed; ready for final owned cleanup')
 environment('down')
 save('hosts down verified; release ready for final analysis')
except OperationalPause as exc:
 save('paused for agent investigation; no new fault injection',error=str(exc),first_main_forecast=None,remaining_budget=None,completion_forecast=None)
 raise
except BaseException as exc:
 DATA['error']=f'{type(exc).__name__}: {exc}';save('execution stopped for investigation',error=DATA['error'])
 (BASE/'driver-error.txt').write_text(traceback.format_exc())
 # No fault/action replay. Only verified ownership restoration permits down.
 try:
  active=[];proofs=[]
  for root in (BED,DEV):
   for saved in root.rglob('campaign.json'):
    manifest=json.loads(saved.read_text())
    if manifest.get('synthetic'):continue
    for case in manifest['cases']:
     for attempt in case.get('attempts',[]):
      active.append(attempt['state']!='VERIFIED')
      proof=saved.parent/attempt['path']/'cleanup.json'
      proofs.append(json.loads(proof.read_text())['checks'] if proof.exists() else {})
  if any(active) or any(not proof or not all(v is True for v in proof.values()) for proof in proofs):
   save('stop: owned cleanup verification required before down')
  else:
   action=next_action(dict(trial_valid=False,safety=True,cleanup=True,missing=[]),cleanup_verified=True,budget_available=BedLedger(P).budget_available())
   if action=='safe_shutdown':
    environment('down');save('cost safety shutdown; pending scope preserved',error=DATA['error'])
   else:
    atomic_json(BASE/'REPAIR-REQUIRED.json',dict(utc=utc(),action=action,error=DATA['error'],cleanup_verified=True,no_fault_replay=True))
    save('paused for agent investigation; cleanup verified',failure_action=action,first_main_forecast=None)
 except BaseException as down_error:
  save('stop: shutdown/ownership needs operator investigation',shutdown_error=f'{type(down_error).__name__}: {down_error}')
 raise
