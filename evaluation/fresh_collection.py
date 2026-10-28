"""Bounded evidence retrieval; callers must supply reads, never recovery actions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts')]
from fresh_evidence import append, utc, epoch
from lib.state import atomic_json


def checkpoint_text(target, text):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name+'.partial')
    with temporary.open('w') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    fd = os.open(target.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def read_evidence(ev, label, reader, *, attempts=3, seconds=90, per_attempt=20, identity=None):
    from fresh_read_budget import read_with_budget
    def require_identity(left):
        if identity is not None:
            return identity(left)
        from lib.fresh_reads import context, identity as verify
        ctx=context()
        if ctx is None:raise RuntimeError('collection retry identity is not registered: '+label)
        verify(ctx,left)
    return read_with_budget(lambda left: reader(min(per_attempt,left())),
        timeout=seconds, identity=require_identity, label=label, evidence=ev.directory,
        attempts=attempts, log_name='collection-attempts.jsonl')


def remote_file(ev, remote, source, destination, *, host=None, bounded=False, identity=None, seconds=90):
    """Record a resumable read location before transfer; replace local file atomically."""
    target = ev.directory/destination
    if Path(destination).is_absolute() or '..' in Path(destination).parts:
        raise ValueError('evidence destination must stay inside attempt')
    append(ev.directory/'remote-files.jsonl', dict(utc=utc(), source=source, destination=destination, host=host))
    if bounded:
        # The registered adapter owns the only retry engine and full budget.
        result = remote('sudo cat '+shlex.quote(source), timeout=min(90,seconds))
    else:
        result = read_evidence(ev, source, lambda timeout: remote('sudo cat '+shlex.quote(source), timeout=timeout),
            seconds=seconds, identity=identity)
    checkpoint_text(target, result)
    append(ev.directory/'remote-files.jsonl', dict(utc=utc(), source=source, destination=destination, host=host,
        captured=True, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    return result


def durable_host_stat(ev, runtime, host, sequence, *, identity=None, seconds=90):
    """Take a timestamped snapshot once; lost SSH responses resume only its download.

    The initial telemetry command is never retried. A missing remote file stays
    missing. A later successful download cannot substitute a later observation.
    """
    token = hashlib.sha256(str(ev.directory.resolve()).encode()).hexdigest()[:24]
    source = f'/var/lib/openstack-k8s-graduation/fresh-evidence/{token}/{host}-{sequence:04}.json'
    requested = utc()
    deadline=time.monotonic()+min(seconds,90)
    append(ev.directory/'host-collection.jsonl', dict(host=host, sequence=sequence,
        source=source, requested_utc=requested, observation_bound_seconds=30))
    code = """import datetime,json,pathlib,os
p=pathlib.Path(SOURCE)
p.parent.mkdir(parents=True,exist_ok=True)
cpu=next(l for l in pathlib.Path('/proc/stat').read_text().splitlines() if l.startswith('cpu '))
memory={l.split(':')[0]:int(l.split()[1])*1024 for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith(('MemAvailable:', 'MemTotal:'))}
value={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cpu_ticks':[int(v) for v in cpu.split()[1:9]],'load_average':[float(v) for v in pathlib.Path('/proc/loadavg').read_text().split()[:3]],'cpu_pressure':pathlib.Path('/proc/pressure/cpu').read_text().splitlines(),'memory':memory,'memory_pressure':pathlib.Path('/proc/pressure/memory').read_text().splitlines(),'io_pressure':pathlib.Path('/proc/pressure/io').read_text().splitlines()}
tmp=p.with_suffix('.partial')
with tmp.open('x') as f:
 json.dump(value,f);f.flush();os.fsync(f.fileno())
os.link(tmp,p);tmp.unlink()
fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
""".replace('SOURCE', repr(source))
    try:
        runtime.remote('sudo python3 -', host=host, data=code, timeout=min(20,seconds))
    except Exception as exc:
        append(ev.directory/'host-collection.jsonl', dict(host=host, sequence=sequence,
            utc=utc(), capture_response_error=f'{type(exc).__name__}: {exc}'))
    text = remote_file(ev, lambda command, **kw: runtime.remote(command, host=host, **kw),
                       source, f'host-snapshots/{host}-{sequence:04}.json', host=host, identity=identity,
                       seconds=max(.001,deadline-time.monotonic()))
    result = json.loads(text)
    # Timestamp belongs to the remote host. Existing clock diagnostics remain
    # mandatory; this bound is freshness, never an offset accuracy guarantee.
    if not -5 <= epoch(result['time'])-epoch(requested) <= 30:
        raise RuntimeError('host snapshot outside registered observation bound')
    return result


def durable_python_capture(ev,runtime,code,label,*,host=None,seconds=90):
    """Run this capture ONCE and retry only its unique durable output file."""
    token=hashlib.sha256(str(ev.directory.resolve()).encode()).hexdigest()[:24]
    if not label.replace('-','').isalnum():raise ValueError('unsafe capture label')
    source=f'/var/lib/openstack-k8s-graduation/fresh-evidence/{token}/{label}.json'
    wrapped="""import contextlib,os,pathlib
p=pathlib.Path(SOURCE);p.parent.mkdir(parents=True,exist_ok=True)
tmp=p.with_suffix('.partial')
with tmp.open('x') as f:
 with contextlib.redirect_stdout(f):
  exec(CODE)
 f.flush();os.fsync(f.fileno())
os.link(tmp,p);tmp.unlink()
fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
""".replace('SOURCE',repr(source)).replace('CODE',repr(code))
    end=time.monotonic()+min(seconds,90)
    append(ev.directory/'capture-intents.jsonl',dict(utc=utc(),label=label,source=source,host=host))
    try:runtime.remote('sudo python3 -',host=host,data=wrapped,timeout=min(20,seconds))
    except Exception as error:
        append(ev.directory/'capture-intents.jsonl',dict(utc=utc(),label=label,response_error=str(error),capture_repeated=False))
    return json.loads(remote_file(ev,lambda command,**kw:runtime.remote(command,host=host,**kw),
        source,'captures/'+label+'.json',host=host,seconds=max(.001,end-time.monotonic())))


def preserve_s1_partial(ev, record, raw, error):
    """Preserve available canonical evidence even when required host evidence fails."""
    owned = record and record.get('fresh_attempt') == str(ev.directory.resolve())
    root = Path(record['evidence']) if owned and record.get('evidence') else None
    for source, destination in [('http.jsonl','requests.jsonl'), ('decisions.jsonl','decisions.jsonl')]:
        if root and (root/source).exists():
            (ev.directory/destination).write_bytes((root/source).read_bytes())
    checkpoint = ev.directory/'requests-checkpoint.jsonl'
    if owned and error is not None and not (ev.directory/'requests.jsonl').exists() and checkpoint.exists():
        checkpoint_text(ev.directory/'requests.jsonl', checkpoint.read_text())
    if error is not None:
        raw = {**raw, 'collection_incomplete': True, 'collection_error':f'{type(error).__name__}: {error}'}
        atomic_json(ev.directory/'observations/contract.json', raw)


def resume_download(attempt, output, runtime):
    """Download saved sources into a NEW directory; never rewrite a sealed trial."""
    from fresh_evidence import Evidence
    attempt, output = Path(attempt).resolve(), Path(output).resolve()
    if output == attempt or output.is_relative_to(attempt):
        raise ValueError('recollection must be separate from original attempt')
    records = [json.loads(line) for line in (attempt/'remote-files.jsonl').read_text().splitlines()]
    output.mkdir(parents=True, exist_ok=False)
    ev = Evidence(output, 'download-only')
    atomic_json(output/'origin.json', dict(attempt=str(attempt), utc=utc(),
        purpose='raw recollection only; original judgement and evidence remain unchanged'))
    pending = {(r.get('host'),r['source'],r['destination']) for r in records}
    failures = []
    for host, source, destination in sorted(pending,key=str):
        try:
            remote_file(ev, lambda command, **kw: runtime.remote(command,host=host,**kw),
                        source,destination,host=host)
        except Exception as exc:
            failures.append(dict(host=host,source=source,error=str(exc)))
    atomic_json(output/'result.json', dict(files=len(pending), failures=failures,
                                         original_attempt_modified=False))
    return not failures


if __name__ == '__main__':
    import argparse
    import sys
    # The shell entrypoint loads the original bed environment without bringing it up.
    sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts')]
    from lib.runtime import LabRuntime
    parser = argparse.ArgumentParser(description='Resume existing remote evidence downloads only')
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raise SystemExit(0 if resume_download(args.attempt,args.output,LabRuntime(None)) else 1)


def durable_pod_cpu(lab,pod,namespace):
    """One cgroup counter observation on the exact Pod; retry its file only."""
    from lib.fresh_reads import context, identity
    from fresh_read_budget import read_with_budget
    from fresh_evidence import Evidence
    ctx=context()
    if ctx is None:
        return lab.k('-n',namespace,'exec',pod,'--','cat','/sys/fs/cgroup/cpu.stat',timeout=60)
    ev=Evidence(ctx['evidence'],'pod-capture')
    obj=lab.obj('pod',pod,namespace);uid=obj['metadata']['uid']
    token=hashlib.sha256((ctx['evidence']+str(time.monotonic_ns())).encode()).hexdigest()[:24]
    source='/tmp/fresh-cpu-'+token+'.txt'
    code="import os,pathlib; p=pathlib.Path("+repr(source)+"); f=p.open('x'); f.write(pathlib.Path('/sys/fs/cgroup/cpu.stat').read_text()); f.flush(); os.fsync(f.fileno()); f.close()"
    end=time.monotonic()+60
    append(ev.directory/'capture-intents.jsonl',dict(utc=utc(),kind='pod-cpu',pod_uid=uid,source=source))
    try:lab.k('-n',namespace,'exec',pod,'--','python','-c',code,timeout=20)
    except Exception as error:
        append(ev.directory/'capture-intents.jsonl',dict(utc=utc(),kind='pod-cpu',response_error=str(error),capture_repeated=False))
    def verify(left):
        identity(ctx,left)
        raw=lab.k('get','pod',pod,'-n',namespace,'-o','json',timeout=left())
        if json.loads(raw)['metadata']['uid']!=uid:raise RuntimeError('CPU capture Pod UID changed')
    raw=read_with_budget(lambda left:lab.k('-n',namespace,'exec',pod,'--','cat',source,timeout=left()),
        timeout=max(.001,end-time.monotonic()),identity=verify,label='pod-cpu-file',evidence=ev.directory)
    checkpoint_text(ev.directory/'pod-cpu'/Path(source).name,raw)
    return raw
