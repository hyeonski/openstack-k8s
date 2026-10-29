"""Pre-cleanup durable measurement snapshot; never promotes a trial verdict."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from fresh_analysis import _judge, rows
from fresh_contract import STATES
from fresh_evidence import utc
from lib.state import atomic_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal_measurement(ev, case, profile):
    directory=ev.directory
    seal=directory/'measurement-sealed.json'
    if seal.exists():
        verify_measurement(directory)
        return json.loads(seal.read_text())
    events=rows(directory/'events.jsonl')
    phases=[e['phase'] for e in events if e['kind']=='phase']
    expected=list(STATES)[:list(STATES).index('CLEANUP')]
    from fresh_extension import is_split_only, judge_split_only
    judge = judge_split_only if is_split_only(case) else _judge
    result=judge(directory,case,profile,include_cleanup=False)
    missing=[x for x in result['missing'] if x not in ('phase_sequence_incomplete','cleanup_incomplete')]
    if phases!=expected: missing.append('measurement_phase_sequence_incomplete')
    if not (directory/'identity.json').is_file():missing.append('attempt_identity_missing')
    if missing:
        atomic_json(directory/'measurement-incomplete.json',dict(utc=utc(),missing=missing,
            posthoc=False,strict_verdict_unchanged=True))
        raise RuntimeError('measurement cannot seal: '+', '.join(missing))
    target=directory/'measurement'
    target.mkdir(exist_ok=False)
    files={}
    # This isolated snapshot is immutable even when cleanup later appends events
    # or writes a restored-object safety proof in the operational directory.
    sources=[p for p in directory.rglob('*') if p.is_file() and target not in p.parents]
    for source in sorted(sources):
        relative=source.relative_to(directory)
        dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as incoming,dest.open('xb') as outgoing:
            shutil.copyfileobj(incoming,outgoing);outgoing.flush();os.fsync(outgoing.fileno())
        files[str(relative)]=sha(dest)
    for folder in sorted([target]+[p for p in target.rglob('*') if p.is_dir()],reverse=True):
        fd=os.open(folder,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    value=dict(version=1,utc=utc(),case_id=case['id'],identity=json.loads((directory/'identity.json').read_text()),
        files=files,provisional_measurement_audit=result,
        cleanup_verified=False,strict_verdict_unchanged=True,posthoc=False)
    atomic_json(seal,value)
    ev.event('measurement_sealed',manifest_sha256=sha(seal),files=len(files))
    return value


def verify_measurement(directory):
    directory=Path(directory);path=directory/'measurement-sealed.json'
    if not path.exists():return False
    manifest=json.loads(path.read_text())
    actual={str(p.relative_to(directory/'measurement')):sha(p) for p in (directory/'measurement').rglob('*') if p.is_file()}
    if actual!=manifest['files']:raise RuntimeError('sealed measurement changed')
    return True
