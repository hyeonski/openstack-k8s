"""Explicit controller architecture contract; workload compute identity stays exact."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fresh_evidence import append, utc

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = 'docs/graduation/controller-platform-amendment-2026-10-26.md'
KEY = 'controller_platform_policy'


def validate_controller_policy(profile, live=False):
    policy = profile.get('operations', {}).get(KEY)
    if policy is None:
        return None  # Historical profiles retain strict CPU-platform equality.
    fixed = dict(host='osk8s-controller', machine_type='e2-standard-4',
                 architecture='x86_64', cpu_platform='provider-selected',
                 scope='controller-only', same_instance_id=True,
                 preregistered_document=DOCUMENT)
    if not isinstance(policy, dict) or set(policy) != set(fixed) | {'document_sha256'} or any(policy.get(k) != v for k, v in fixed.items()) or type(policy.get('same_instance_id')) is not bool:
        raise ValueError('unsupported controller architecture policy; only registered x86_64 E2 controller variation is allowed')
    expected = profile.get('observed_environment', {}).get('host_identity', {}).get(policy['host'], {})
    if profile.get('hosts', {}).get(policy['host']) != policy['machine_type'] or expected.get('machine_type') != policy['machine_type'] or not expected.get('id'):
        raise ValueError('controller policy requires the registered exact instance and e2-standard-4 type')
    if policy['host'] in {profile.get(k) for k in ('source_compute', 'target_compute', 'control_plane_compute')}:
        raise ValueError('controller exception cannot apply to workload/control-plane compute')
    sha = policy['document_sha256']
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or DOCUMENT not in profile['operations'].get('preregistered_documents', []):
        raise ValueError('controller amendment must be hash-bound and preregistered')
    if live and hashlib.sha256((ROOT / DOCUMENT).read_bytes()).hexdigest() != sha:
        raise ValueError('controller architecture amendment changed')
    return policy


def identity_matches(profile, expected, observed, controller_architecture=None):
    policy = validate_controller_policy(profile)
    if policy is None:
        return expected == observed
    if controller_architecture != policy['architecture'] or set(expected) != set(profile['hosts']) or set(observed) != set(expected):
        return False
    host = policy['host']
    if not all(isinstance(values.get('cpuPlatform'), str) and values['cpuPlatform'] and values['cpuPlatform'] != 'Unknown CPU Platform' for values in (expected[host], observed[host])):
        return False
    if not observed[host]['cpuPlatform'].startswith(('Intel ', 'AMD ')):
        return False  # Conflicting ARM/unknown provider readback must not pass on uname alone.
    # Compare copies only: retain the actual CPU in every raw/snapshot record.
    left = {n: dict(v) for n, v in expected.items()}
    right = {n: dict(v) for n, v in observed.items()}
    right[host]['cpuPlatform'] = left[host]['cpuPlatform']
    return left == right


def read_controller_architecture(profile, lab, evidence_path=None):
    policy = validate_controller_policy(profile, live=True)
    if policy is None:
        return None
    before = utc()
    architecture = lab.remote('uname -m', timeout=30).strip()
    observation = dict(requested_utc=before, observed_utc=utc(), host=policy['host'],
                       architecture=architecture, source='controller guest uname -m over existing GCP SSH/IAP access')
    if evidence_path:
        append(evidence_path, observation)
    if architecture != policy['architecture']:
        raise RuntimeError('controller architecture must be x86_64; ARM/unknown architecture is not admitted: ' + architecture)
    return architecture
