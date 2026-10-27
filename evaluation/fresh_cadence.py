"""Read-only timing audit of the exact S4 snapshot collector; no fault or fixture mutation."""
from pathlib import Path
import json,sys,time,statistics
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_scenarios import FreshS4Run
from graduation_evaluation_case import EvaluationS4Preparation
from fresh_evidence import epoch,utc
from lib.state import atomic_json
base=ROOT/'artifacts/fresh-evaluation-measurement-repaired-2026-10-27'
directory=base/('cadence-readonly-'+str(time.time_ns()));directory.mkdir()
runner=FreshS4Run(EvaluationS4Preparation());started=time.monotonic();observations=[]
while time.monotonic()-started<150:
    tick=time.monotonic();obs=runner.snapshot(directory,len(observations));observations.append(obs)
    print(json.dumps(dict(utc=obs['time'],errors=obs['errors'],seconds=time.monotonic()-tick)),flush=True)
    time.sleep(max(0,tick+5-time.monotonic()))
gaps=[epoch(b['time'])-epoch(a['time']) for a,b in zip(observations,observations[1:])]
# The owned S4 application/MHC are absent after cleanup; NotFound is expected
# in this read-only check. Every other failure blocks approval.
errors=[dict(index=i,query=k,error=v) for i,o in enumerate(observations) for k,v in o['errors'].items() if not (k in ('mhc','deployment') and ('NotFound' in v or 'not found' in v))]
value=dict(utc=utc(),directory=str(directory),readonly=True,seconds=time.monotonic()-started,snapshots=len(observations),intervals_seconds=gaps,median_seconds=statistics.median(gaps) if gaps else None,max_seconds=max(gaps) if gaps else None,unexpected_errors=errors,per_query_max_seconds={k:max(o['collection_timing'][k]['seconds'] for o in observations) for k in observations[0]['collection_timing']},limitation='No fault, no replacement binding or owned app creation; full H pilot verifies active resources.',passed=len(gaps)>=10 and max(gaps)<=15 and not errors)
atomic_json(directory/'summary.json',value)
if value['passed']:atomic_json(base/'cadence-approved.json',value)
else:raise SystemExit('S4 read-only cadence failed; inspect '+str(directory/'summary.json'))
