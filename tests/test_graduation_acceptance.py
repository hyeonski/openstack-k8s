"""Regression cases for false-positive recovery and invalid statistics."""
import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('scripts', 'experiments', 'evaluation')]
from graduation_evaluation_verify import verify, verify_s2, verify_s3, verify_s4, raw_http_stable
from graduation_s4_analyze import stable_success, analyze
from graduation_s4_run import summarize_http
from evaluation_fixtures import put, s2_evidence, s3_evidence, s4_evidence


def stamp(second):
    return (dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=second)).isoformat()


class AcceptanceTests(unittest.TestCase):
    def test_s3_audit_checks_seed_fencing_identity_and_durability(self):
        for kind in ('valid', 'same_corrupted_records', 'other_vm_fenced', 'image_changed', 'no_fsync', 'dual_attach'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); record = s3_evidence(root)
                if kind == 'same_corrupted_records':
                    records = json.loads((root / 'committed-records-before.json').read_text())
                    records[0]['value'] = 'corrupt'
                    for name in ('before', 'after'):
                        put(root, 'committed-records-' + name + '.json', records)
                elif kind == 'other_vm_fenced':
                    fence = json.loads((root / 'fence.json').read_text()); fence['server']['id'] = 'other'
                    put(root, 'fence.json', fence)
                elif kind == 'image_changed':
                    record['pod_after']['status']['containerStatuses'][0]['imageID'] = 'different'
                elif kind == 'no_fsync':
                    record['durability'] = 'off:on:on:/var/lib/postgresql/data/pgdata'
                elif kind == 'dual_attach':
                    put(root, 'volume-after.json', {'id': 'volume', 'attachments': [{'server_id': 'target'}, {'server_id': 'source'}]})
                put(root, 'run.json', record)
                self.assertEqual(all(verify_s3(root)[0].values()), kind == 'valid')

    def test_s4_full_analysis_and_independent_audit_reject_sparse_success(self):
        for sparse in (False, True):
            with self.subTest(sparse=sparse), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); s4_evidence(root, sparse=sparse)
                summary = analyze(root)
                self.assertEqual(summary['state'], 'incomplete' if sparse else 'complete')
                checks, _, _ = verify_s4(root)
                self.assertEqual(all(checks.values()), not sparse)
                if sparse:
                    summary['state'] = 'complete'
                    put(root / 'analysis', 'summary.json', summary)
                    self.assertFalse(verify_s4(root)[0]['raw_http_stable'])

    def test_s4_audit_rejects_forged_capacity_and_missing_snapshots(self):
        for kind in ('old_vm', 'probe_not_ready', 'missing', 'duration'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); s4_evidence(root); analyze(root)
                final = root / 'observations/0002.json'
                snap = json.loads(final.read_text())
                if kind == 'old_vm':
                    snap['nova'].append({'ID': 'vm-old', 'Status': 'SHUTOFF'})
                    put(final.parent, final.name, snap)
                elif kind == 'probe_not_ready':
                    snap['pods']['items'][0]['status']['conditions'][0]['status'] = 'False'
                    put(final.parent, final.name, snap)
                elif kind == 'missing':
                    for p in final.parent.iterdir():
                        p.unlink()
                else:
                    summary = json.loads((root / 'analysis/summary.json').read_text())
                    summary['durations_seconds']['shutoff_to_capacity_stable_seconds'] = 1
                    put(root / 'analysis', 'summary.json', summary)
                self.assertFalse(all(verify_s4(root)[0].values()))

    def test_successful_samples_separated_by_silence_are_not_stable(self):
        for times in ([1, 244], [1, 2, 33], list(range(1, 20)) + [100]):
            rows = [{'time': stamp(0), 'ok': False}] + [{'time': stamp(t), 'ok': True} for t in times]
            with self.subTest(times=times):
                self.assertEqual(summarize_http(rows, stamp(0))['state'], 'not_stable')
                self.assertIsNone(stable_success(rows, stamp(0))[1])
                self.assertIsNone(raw_http_stable(rows))

    def test_no_observed_outage_also_requires_dense_stable_samples(self):
        rows = [{'time': stamp(t), 'ok': True} for t in [1, 244]]
        self.assertEqual(summarize_http(rows, stamp(0))['state'], 'not_stable')

    def test_gap_resets_window_then_new_contiguous_tail_can_recover(self):
        rows = [{'time': stamp(0), 'ok': False}] + [
            {'time': stamp(t), 'ok': True} for t in list(range(1, 21)) + list(range(100, 131))]
        self.assertEqual(stable_success(rows, stamp(0)), (stamp(100), stamp(130)))
        self.assertEqual(raw_http_stable(rows), stamp(130))
        self.assertEqual(summarize_http(rows, stamp(0))['service_recovered_at'], stamp(100))

    def test_duplicate_and_backward_timestamps_do_not_extend_stability(self):
        for times in ([1] * 30 + [31], list(range(1, 30)) + [20, 32]):
            rows = [{'time': stamp(t), 'ok': True} for t in times]
            self.assertIsNone(stable_success(rows, None)[1])
            self.assertIsNone(raw_http_stable(rows))

    def test_s2_rejects_matching_but_unrecovered_metrics(self):
        for kind in ('latency', 'upload_stopped', 'failure', 'missing_window', 'no_policy', 'all_failed'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                summary = s2_evidence(root)
                raw = json.loads((root / 'stable-0.json').read_text())
                if kind == 'latency':
                    for row in raw['rows']:
                        row['latency_ms'] = 5000
                    summary['windows']['stable-0']['p95_ms'] = 5000
                elif kind == 'upload_stopped':
                    raw['progress_after']['bytes'] = 0
                    summary['windows']['stable-0']['upload_bytes'] = 0
                elif kind in ('failure', 'all_failed'):
                    for row in raw['rows'][:1 if kind == 'failure' else 120]:
                        row['ok'] = False
                    summary['windows']['stable-0']['failures'] = 1 if kind == 'failure' else 120
                    if kind == 'all_failed':
                        summary['windows']['stable-0']['p95_ms'] = None
                elif kind == 'missing_window':
                    del summary['windows']['split-unlimited']
                else:
                    record = json.loads((root / 'run.json').read_text())
                    record['policy_changes'] = []
                    put(root, 'run.json', record)
                put(root, 'stable-0.json', raw)
                put(root, 'summary.json', summary)
                checks, _, _ = verify_s2(root)
                self.assertFalse(all(checks.values()))

    def test_s2_requires_real_congestion_and_unchanged_summary_failure_count(self):
        for field in ('cpu', 'egress', 'hidden_failure'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); s2_evidence(root)
                name = 'uncontrolled-0' if field != 'hidden_failure' else 'stable-0'
                raw = json.loads((root / (name + '.json')).read_text())
                if field == 'cpu':
                    raw['host_after']['compute']['cpu_ticks'] = [95, 0, 0, 5, 0, 0, 0, 0]
                elif field == 'egress':
                    raw['qdisc_after'][0]['bytes'] = 0
                else:
                    raw['rows'][0]['ok'] = False
                put(root, name + '.json', raw)
                checks, _, _ = verify_s2(root)
                self.assertFalse(all(checks.values()))

    def campaign(self, root):
        evidence = root / 'evidence'; evidence.mkdir(); s2_evidence(evidence)
        source = root / 'source'; source.mkdir(); (source / 'code.py').write_text('# frozen\n')
        case = dict(id='s2-fixed-first-01', scenario='s2', mode='fixed-first', status='complete',
                    negative=False, accepted=True, evidence=str(evidence),
                    evidence_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir()})
        cleanup = root / 'cases' / case['id']; cleanup.mkdir(parents=True)
        put(cleanup, 'cleanup-verification.json', {'passed': True, 'checks': {'restored': True}})
        campaign = dict(id='synthetic-campaign', profile={'hosts': {'controller': 'type'}}, cases=[case],
                        source_sha256={'code.py': hashlib.sha256((source / 'code.py').read_bytes()).hexdigest()})
        put(root, 'environment-final.json', {'final_hosts': {'controller': {'status': 'TERMINATED'}}})
        return campaign

    def test_invalid_cases_stay_in_denominator_but_out_of_statistics(self):
        for kind in ('hash', 'not_accepted', 'missing_summary', 'source', 'empty_cleanup', 'no_hashes'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); campaign = self.campaign(root); case = campaign['cases'][0]
                if kind == 'hash':
                    case['evidence_sha256']['summary.json'] = '0' * 64
                elif kind == 'not_accepted':
                    case['accepted'] = False; case['status'] = 'needs_review'
                elif kind == 'missing_summary':
                    (root / 'evidence/summary.json').unlink()
                elif kind == 'source':
                    (root / 'source/code.py').unlink()
                elif kind == 'empty_cleanup':
                    put(root / 'cases' / case['id'], 'cleanup-verification.json', {'passed': True, 'checks': {}})
                else:
                    case['evidence_sha256'] = {}
                put(root, 'campaign.json', campaign)
                with contextlib.redirect_stdout(io.StringIO()):
                    result = verify(root, partial=True)
                self.assertEqual(result['statistics'], {})
                self.assertTrue(result['cases'][0]['statistics_exclusions'])
                counts = json.loads((root / 'outcome-counts.json').read_text())['s2:comparison']
                self.assertEqual((counts['planned'], counts['finished'], counts['performance_samples']), (1, 1, 0))
                self.assertIn(case['id'], (root / 'report.md').read_text())

    def test_valid_campaign_generates_report_csv_and_nonempty_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); put(root, 'campaign.json', self.campaign(root))
            with contextlib.redirect_stdout(io.StringIO()):
                result = verify(root)
            self.assertEqual(result['statistics']['s2:comparison']['runs'], 1)
            self.assertTrue(result['verification_complete'])
            self.assertTrue((root / 'results.csv').is_file())

    def test_empty_host_snapshot_does_not_confirm_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); put(root, 'campaign.json', self.campaign(root))
            put(root, 'environment-final.json', {'final_hosts': {}})
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                verify(root)


if __name__ == '__main__':
    unittest.main()
