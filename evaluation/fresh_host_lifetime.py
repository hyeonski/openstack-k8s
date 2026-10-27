"""Explicit, hash-bound permission to remove the existing hosts' cloud runtime cap."""
import hashlib
from pathlib import Path

from lib.host_lifetime import host_deadline

ROOT=Path(__file__).resolve().parents[1]
DOCUMENT='docs/graduation/no-host-auto-stop-pause-contract-2026-10-27.md'


def validate_host_lifetime_policy(profile, live=False):
    policy=profile.get('operations',{}).get('host_lifetime_policy')
    if policy is None:
        if profile.get('operations',{}).get('calendar_targets_only') or profile.get('operations',{}).get('uptime_targets_only'):
            raise ValueError('time-target-only behavior needs explicit hash-bound approval')
        return None
    expected={'mode':'no-cloud-runtime-limit','scope':'existing-three-hosts-only',
              'completion_target_utc':'2026-10-28T23:00:00+00:00',
              'time_policy':'cost-bounded-targets-only','preregistered_document':DOCUMENT}
    if not isinstance(policy,dict) or set(policy)!=set(expected)|{'document_sha256'} or any(policy.get(k)!=v for k,v in expected.items()):
        raise ValueError('unsupported no-auto-stop host policy')
    ops=profile['operations']
    if ops.get('hard_stop_utc')!=expected['completion_target_utc'] or ops.get('calendar_targets_only') is not True or ops.get('uptime_targets_only') is not True:
        raise ValueError('explicit completion/uptime target-only contract required')
    if ops.get('new_work_budget_krw',1e99)>146234 or ops.get('cleanup_reserve_krw',0)<40000 or ops.get('credit_budget_krw',0)<ops.get('new_work_budget_krw',0)+ops.get('cleanup_reserve_krw',0):
        raise ValueError('time relaxation cannot remove credit/cost/cleanup reserve gates')
    if set(profile['hosts'])!={'osk8s-controller','osk8s-compute01','osk8s-compute02'} or DOCUMENT not in ops.get('preregistered_documents',[]):
        raise ValueError('no-auto-stop approval is limited to existing registered hosts')
    sha=policy['document_sha256']
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('no-auto-stop document SHA required')
    if live and hashlib.sha256((ROOT/DOCUMENT).read_bytes()).hexdigest()!=sha:
        raise ValueError('no-auto-stop approval document changed')
    return policy


def effective_host_deadline(profile, host):
    policy=validate_host_lifetime_policy(profile,live=True)
    if policy:
        scheduling=host.get('scheduling',{})
        raw=host.get('max_run_seconds',scheduling.get('maxRunDuration',{}).get('seconds'))
        if raw not in (None,0,'0') or host.get('termination_time',scheduling.get('terminationTime')):
            raise RuntimeError('cloud automatic stop still present under disabled-timer contract')
    return host_deadline(host,hard_stop=None if policy else profile.get('operations',{}).get('hard_stop_utc'),allow_unlimited=bool(policy),targets_only=bool(policy))


def time_targets_only(profile):
    return bool(validate_host_lifetime_policy(profile,live=True))
