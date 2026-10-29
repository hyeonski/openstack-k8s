"""Read-only extension readiness snapshot. Never ensures hosts or acquires a clock lease."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from fresh_campaign import ROOT, source_hashes
from fresh_contract import load
from fresh_credit import forward_credit
from fresh_evidence import utc
from fresh_extension import require_committed_source
from fresh_extension_analysis import write_new_json
from fresh_read_registry import audit
from fresh_identity import validate_controller_policy

RESERVED_SECONDS = 4 * 37 * 72 + 1500


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=45).strip()


def profile_changes(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            path = prefix + '.' + key if prefix else key
            result.extend(profile_changes(before.get(key), after.get(key), path))
        return result
    return [prefix] if before != after else []


def assert_v12(profile, previous):
    changes = profile_changes(previous, profile)
    expected = ['operations.artifact_root', 'operations.stability.credit_reference.path',
                'operations.stability.credit_reference.sha256']
    if changes != expected or Path(profile['operations']['artifact_root']).name != 'bed-extension-v12':
        raise ValueError('v12 must change only artifact_root and credit_reference: ' + repr(changes))
    return changes


def lock_status(paths):
    """Probe existing files without creating/truncating them; release immediately."""
    held = []
    existing = []
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        existing.append(str(path))
        with path.open('rb') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(str(path))
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
    return dict(passed=not held, held=held, inspected=existing,
                semantics='absence of active advisory locks; retained unlocked files are harmless')


def evaluation_processes(text, excluded=()):
    found = []
    # Match executable/script paths, not incidental tool prompt strings. Clock
    # guard is an expected idle service; this preflight excludes only its own PID.
    pattern = re.compile(r'(?:^|[/\s])(?:fresh_[\w-]+\.py|graduation[_-][\w-]+(?:\.py|\.sh)|workload-api-(?:watch|keeper)\S*)')
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) in excluded:
            continue
        if pattern.search(parts[1]):
            if re.search(r'(?:^|/)fresh_clock_guard\.py\s+--serve\s+\d+$', parts[1]):
                continue
            found.append(dict(pid=int(parts[0]), command=parts[1]))
    return found


def preflight(profile_path, previous_path, *, root=ROOT, state=None, run=command,
              service_root=Path('/var/db/openstack-k8s-clock-guard'),
              request_root=Path('/var/run/openstack-k8s-clock-guard'),
              installed_service=Path('/Library/Application Support/openstack-k8s-clock-guard/service.py')):
    root = Path(root).resolve()
    raw = json.loads(Path(profile_path).read_text())
    state = Path(state) if state else root / '.state' / raw['environment']
    checks = {}

    def check(name, fn):
        try:
            value = fn()
            checks[name] = value if isinstance(value, dict) and 'passed' in value else dict(passed=True, evidence=value)
        except Exception as error:
            detail = (error.stderr or '').strip() if isinstance(error, subprocess.CalledProcessError) else ''
            checks[name] = dict(passed=False, error=type(error).__name__ + ': ' + str(error), detail=detail)

    def clock():
        data = json.loads((service_root / 'state.json').read_text())
        service = run('/bin/launchctl', 'print', 'system/dev.openstack-k8s.clock-guard')
        installed = hashlib.sha256(installed_service.read_bytes()).hexdigest()
        expected = hashlib.sha256((root / 'evaluation/fresh_clock_guard.py').read_bytes()).hexdigest()
        pending = (request_root / 'request.json').exists()
        restored = data.get('status') == 'idle' or (type(data.get('original_network_time')) is bool
                    and type(data.get('restored_network_time')) is bool
                    and data['restored_network_time'] == data['original_network_time'])
        passed = data.get('status') in ('idle', 'restored') and not pending and restored and bool(re.search(r'\bstate = running\b', service)) and installed == expected
        return dict(passed=passed, state=data, pending_request=pending,
                    service_running=bool(re.search(r'\bstate = running\b', service)), installed_sha256=installed,
                    installed_matches_source=installed == expected)

    def sleep():
        custom = run('/usr/bin/pmset', '-g', 'custom')
        assertions = run('/usr/bin/pmset', '-g', 'assertions')
        power = run('/usr/bin/pmset', '-g', 'batt')
        active = re.search(r"Now drawing from '([^']+)'", power)
        settings = {}
        section = None
        for line in custom.splitlines():
            if line.endswith(':'):
                section = line[:-1].strip()
            setting = re.fullmatch(r'\s*sleep\s+(\d+)\s*', line)
            if setting and section:
                settings[section] = int(setting[1])
        selected = active[1] if active else None
        # Check persistent settings for the power source actually supplying the
        # machine. Incidental application assertions can disappear at any time.
        return dict(passed=selected in settings and settings[selected] == 0,
                    active_power=selected, sleep_minutes_by_power_source=settings,
                    power_source_must_remain=selected, custom=custom, power=power, assertions=assertions)

    def processes():
        found = evaluation_processes(run('/bin/ps', '-axo', 'pid=,command='), {os.getpid()})
        return dict(passed=not found, processes=found)

    def ledger():
        path = Path(raw['operations']['bed_ledger_path'])
        data = json.loads(path.read_text())
        opened = [s for s in data['sessions'] if not s.get('stopped')]
        identity = data['environment'] == raw['environment'] and data['project'] == raw['project']
        return dict(passed=identity and not opened, path=str(path), open_sessions=opened,
                    identity_matches=identity, sessions=len(data['sessions']))

    def hosts():
        data = json.loads(run('gcloud', 'compute', 'instances', 'list', '--project='+raw['project'],
                             '--filter=zone:('+raw['zone']+')', '--format=json(name,id,status,machineType,zone)'))
        selected = [h for h in data if h['name'] in raw['hosts']]
        identities = raw['operations']['stability']['read_identity']['hosts']
        ok = len(selected) == 3 and {h['name'] for h in selected} == set(raw['hosts'])
        ok = ok and all(h['status'] == 'TERMINATED' and str(h['id']) == identities[h['name']]
                        and h['machineType'].split('/')[-1] == raw['hosts'][h['name']]
                        and h['zone'].split('/')[-1] == raw['zone'] for h in selected)
        return dict(passed=ok, hosts=selected)

    def source():
        commit = require_committed_source(root)
        branch = run('git', '-C', str(root), 'branch', '--show-current')
        return dict(passed=branch == 'codex/fresh-evaluation-execution-20261026', commit=commit,
                    branch=branch, source_sha256=source_hashes(root), read_registry=audit(root))

    def profile():
        value = load(profile_path, live=True)
        validate_controller_policy(value, live=True)
        changes = assert_v12(value, json.loads(Path(previous_path).read_text()))
        return dict(passed=True, path=str(Path(profile_path).resolve()),
                    sha256=hashlib.sha256(Path(profile_path).read_bytes()).hexdigest(), changes=changes)

    def credit():
        value = forward_credit(raw, RESERVED_SECONDS)
        return dict(passed=value is not None and value['margin_krw'] > 0,
                    reference=raw['operations']['stability']['credit_reference'], forward_credit=value)

    check('clock_guard', clock)
    check('sleep_prevention', sleep)
    check('evaluation_processes', processes)
    check('locks', lambda: lock_status([*state.rglob('*.lock'), *(root/'artifacts').rglob('*.lock')]))
    check('ledger', ledger)
    check('hosts', hosts)
    check('committed_source', source)
    check('v12_profile', profile)
    check('credit', credit)
    return dict(checked_utc=utc(), passed=all(c['passed'] for c in checks.values()), checks=checks,
                read_only=True, experiment_executed=False,
                limitation='point-in-time snapshot; recheck before ensure; no guarantee of future live execution',
                handoff_targets_kst={'ensure':'2026-10-29 16:30', 'first_case':'2026-10-29 17:00',
                    'no_new_case_at_or_after':'2026-10-29 19:50', 'down_complete':'2026-10-29 20:40'},
                time_gate_note='Inherited profile uses cost-bounded-targets-only; the executor must enforce these wall-clock cutoffs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--previous-profile', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    # A preflight output is new evidence only, never an update to a campaign.
    for parent in [args.output.resolve().parent, *args.output.resolve().parents]:
        if (parent/'campaign.json').exists() or (parent/'frozen-manifest.json').exists():
            parser.error('output must be outside existing campaigns')
    value = preflight(args.profile, args.previous_profile)
    write_new_json(args.output, value)
    print(json.dumps(dict(passed=value['passed'], output=str(args.output.resolve()),
                         checks={k:v['passed'] for k,v in value['checks'].items()}), indent=2))
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
