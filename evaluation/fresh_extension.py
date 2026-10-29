"""Separate S2 ablation extension cohort; never part of original main29.

The extension reuses the v11 scientific contract in the v12 operational profile and adds only
manifest-level cases. S is the Kubernetes-only arm: the same uploader
relocation as P without Neutron QoS. One attempt per case, no retry.
"""
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from lib.state import atomic_json
from fresh_contract import digest, load, validate
from fresh_evidence import utc

STAGE = 'extension'
# Fixed before execution: three S cases followed by one same-day P anchor.
PLAN = (('s2-x01-s', 'S', 'x01'), ('s2-x02-s', 'S', 'x02'), ('s2-x03-s', 'S', 'x03'),
        ('s2-x04-p', 'P', 'x04'))


def extension_cases(profile):
    return [dict(id=cid, scenario='s2', mode=mode, purpose=STAGE, block=block, seed=profile['seed'],
                 session='EXTENSION', order=100 + index, depends_on=[], status='pending', negative=False)
            for index, (cid, mode, block) in enumerate(PLAN, 1)]


def freeze_extension(profile_path, destination, root, synthetic=False):
    from fresh_campaign import source_hashes, policy_manifest
    root = Path(root).resolve()
    profile_path = Path(profile_path).resolve()
    destination = Path(destination).resolve()
    profile = load(profile_path, live=not synthetic)
    if destination.exists():
        raise ValueError('new dedicated extension campaign directory required')
    if not synthetic:
        ops = profile['operations']
        if not destination.is_relative_to(Path(ops['artifact_root']).resolve()):
            raise ValueError('extension campaign must be inside registered artifact root')
        if Path(ops['execution_checkout']).resolve() != root:
            raise ValueError('execution checkout mismatch')
        override = Path(os.environ.get('ENV_OVERRIDE_FILE', '')).resolve()
        if override != Path(ops['environment_override']).resolve() or not override.is_file():
            raise ValueError('explicit environment override mismatch')
        for key, field in [('ENVIRONMENT_NAME', 'environment'), ('GCP_PROJECT_ID', 'project'), ('GCP_ZONE', 'zone')]:
            if os.environ.get(key) != profile[field]:
                raise ValueError('explicit environment identity mismatch')
    initial_commit = require_committed_source(root) if not synthetic else None
    source = source_hashes(root)
    policy = policy_manifest(source)
    destination.mkdir(parents=True)
    for name in source:
        target = destination / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    documents = {}
    for name in profile['operations'].get('preregistered_documents', []):
        target = destination / 'preregistered-documents' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
        documents[name] = __import__('hashlib').sha256(target.read_bytes()).hexdigest()
    blob = profile_path.read_bytes()
    (destination / 'selected-profile.json').write_bytes(blob)
    atomic_json(destination / 'policy-manifest.json', policy)
    git = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
    manifest = dict(git_head=git.stdout.strip() if git.returncode == 0 else None, schema_version=3,
                    id='fresh-' + uuid.uuid4().hex, created=utc(), synthetic=synthetic, stage=STAGE,
                    scope=profile['scope'], profile=profile, profile_path=str(profile_path),
                    profile_sha256=__import__('hashlib').sha256(blob).hexdigest(),
                    analysis_sha256=digest(profile['analysis']), policy_sha256=digest(policy),
                    source_sha256=source, preregistered_documents_sha256=documents,
                    cases=extension_cases(profile), status='frozen', schedule_counts={STAGE:len(PLAN)},
                    inherited_profile_schedule_counts=validate(profile), attempt_cap=1,
                    historical_results='excluded',
                    primary_rule='extension ablation only; never replaces or joins original main29/supplements')
    if not synthetic:
        manifest['override_path'] = str(override)
        manifest['override_sha256'] = __import__('hashlib').sha256(override.read_bytes()).hexdigest()
    if source_hashes(root) != source:
        raise ValueError('source changed during extension freeze')
    if not synthetic:
        if require_committed_source(root) != initial_commit or manifest['git_head'] != initial_commit:
            raise ValueError('commit changed during extension freeze')
    atomic_json(destination / 'campaign.json', manifest)
    atomic_json(destination / 'frozen-manifest.json', manifest)
    (destination / 'manifest.sha256').write_text(digest(manifest) + '\n')
    return destination


def require_committed_source(root):
    """Live extension snapshots must be reviewable against a clean commit."""
    root = Path(root)
    status = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                      '--untracked-files=all'], text=True, stderr=subprocess.PIPE)
    if status.strip():
        raise ValueError('extension requires a clean committed checkout: ' + status.strip())
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()


def is_split_only(case):
    return case.get('purpose') == STAGE and case.get('scenario') == 's2' and case.get('mode') == 'S'


def judge_split_only(directory, case, profile, *, include_cleanup=True):
    """New-arm safety check only; use the unchanged primary measurement engine.

    No P/M rule, validity, milestone, bin, latency, or recovery is redefined.
    The inherited S2 fallback expects QoS; replace just that check for S.
    """
    from fresh_analysis import _judge, read
    if not is_split_only(case):
        raise ValueError('split-only judgement requires an extension S2/S case')
    result = _judge(directory, case, profile, include_cleanup=include_cleanup)
    checks = result['checks']
    if 'split_and_qos' in checks:
        raw = read(Path(directory) / 'observations/contract.json')
        del checks['split_and_qos']
        checks['split_only'] = (raw['final']['upload_node'] != raw['initial']['api_node']
                                and not raw['final']['port'].get('qos_policy_id'))
        result['safety'] = bool(checks) and all(checks.values())
        recovered = result['recovered']
        result['metrics']['safe_recovered'] = bool(recovered and result['safety']) if recovered is not None else None
    return result
