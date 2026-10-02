import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from graduation_s2 import S2, analyze, impacted, stable, next_rate
spec = importlib.util.spec_from_file_location('s2_workload', ROOT / 'kubernetes/graduation-s2/workload.py')
workload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workload)


class S2Tests(unittest.TestCase):
    def test_cleanup_removes_an_unattached_owned_security_group(self):
        runner = S2.__new__(S2)
        runner.record = {'phase': 'failed', 'run_id': 's2-test', 'security_group_id': 'sg',
                         'workers': [{'port': {'id': 'port'}}]}
        runner.acquire = Mock()
        runner.ownership = Mock()
        runner.delete_namespace = Mock()
        runner.admin_json = Mock(side_effect=[[{'ID': 'sg'}], {'id': 'port', 'security_group_ids': ['original']}])
        runner.admin = Mock()
        runner.restore_workers = Mock()
        runner.write = Mock()
        runner.cleanup()
        runner.admin.assert_called_once_with('security', 'group', 'delete', 'sg')
        runner.delete_namespace.assert_called_once()
        runner.restore_workers.assert_called_once()

    def test_controller_is_bounded_and_requires_progress(self):
        self.assertEqual(next_rate(6000, False), 6000)
        self.assertEqual(next_rate(18000, True), 18000)
        self.assertEqual(next_rate(14000, False), 10000)
        metric = dict(complete=True, failures=0, p95_ms=90, upload_bytes=100)
        self.assertTrue(stable(80, metric))
        self.assertFalse(stable(80, {**metric, 'upload_bytes': 0}))
        self.assertFalse(stable(80, {**metric, 'complete': False}))
        self.assertTrue(impacted(80, {**metric, 'p95_ms': 150}))
        self.assertFalse(impacted(80, {**metric, 'complete': False, 'failures': 3}))

    def test_missing_samples_and_bottleneck_counters(self):
        sample = dict(rows=[dict(index=i, ok=True, latency_ms=100) for i in range(120)],
                      qdisc_before=[dict(bytes=0, drops=0, overlimits=0)],
                      qdisc_after=[dict(bytes=150000000, drops=4, overlimits=100)],
                      progress_before={'bytes': 0}, progress_after={'bytes': 100000000}, elapsed=60)
        self.assertTrue(analyze(sample)['complete'])
        self.assertEqual(analyze(sample)['egress_bps'], 20000000)
        sample['rows'][-1]['index'] = 0
        self.assertFalse(analyze(sample)['complete'])

    def test_duplicate_upload_does_not_advance_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with sqlite3.connect(root / 'progress.db') as db:
                db.execute('create table chunks(id integer primary key, size integer, sha text)')
            statuses = []
            for body in (workload.payload(0), workload.payload(0), b'x' * workload.CHUNK):
                handler = workload.Handler.__new__(workload.Handler)
                handler.server = SimpleNamespace(root=root)
                handler.path = '/chunk/0'
                handler.headers = {'Content-Length': str(len(body))}
                handler.rfile = io.BytesIO(body)
                handler.reply = lambda data, status=200: statuses.append(status)
                handler.do_PUT()
            self.assertEqual(statuses, [200, 200, 400])
            with sqlite3.connect(root / 'progress.db') as db:
                self.assertEqual(db.execute('select count(*), sum(size) from chunks').fetchone(), (1, workload.CHUNK))
            self.assertEqual((root / '000000.chunk').read_bytes(), workload.payload(0))


if __name__ == '__main__':
    unittest.main()
