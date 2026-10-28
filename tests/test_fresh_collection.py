"""Collection failures must retain evidence without replaying a fault or action."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_collection import read_evidence, remote_file, durable_host_stat, preserve_s1_partial, resume_download
from fresh_evidence import Evidence, utc
from fresh_scenarios import FreshS1


class CollectionTests(unittest.TestCase):
    def test_transient_read_error_preserved_and_retry_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root);reader=Mock(side_effect=[RuntimeError('TLS EOF'),'raw'])
            self.assertEqual(read_evidence(ev,'raw',reader,identity=lambda left:left()),'raw')
            records=[json.loads(l) for l in (Path(root)/'collection-attempts.jsonl').read_text().splitlines()]
            self.assertEqual(len(records),2)
            self.assertIn('TLS EOF',records[0]['error'])
            self.assertTrue(records[1]['captured'])

    def test_cumulative_budget_is_not_reset(self):
        with tempfile.TemporaryDirectory() as root:
            reader=Mock(side_effect=RuntimeError('unavailable'))
            with patch('fresh_collection.time.monotonic',side_effect=[0,0,91]),self.assertRaises(RuntimeError):
                read_evidence(Evidence(root),'file',reader,seconds=90)
            self.assertEqual(reader.call_count,1)

    def test_failed_download_preserves_previous_file_and_can_resume(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root);target=Path(root)/'requests.jsonl';target.write_text('checkpoint')
            remote=Mock(side_effect=RuntimeError('SSH255'))
            with self.assertRaises(RuntimeError):remote_file(ev,remote,'/remote/file','requests.jsonl')
            self.assertEqual(target.read_text(),'checkpoint')
            remote=Mock(return_value='complete')
            self.assertEqual(remote_file(ev,remote,'/remote/file','requests.jsonl'),'complete')
            self.assertEqual(target.read_text(),'complete')
            self.assertTrue(all(call.args[0]=='sudo cat /remote/file' for call in remote.call_args_list))

    def test_lost_snapshot_response_only_downloads_original_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            now=utc();runtime=Mock()
            runtime.remote.side_effect=[RuntimeError('response lost'),RuntimeError('TLS EOF'),json.dumps({'time':now,'cpu_ticks':[1]*8})]
            value=durable_host_stat(Evidence(root),runtime,'osk8s-compute02',1,identity=lambda left:left())
            self.assertEqual(value['time'],now)
            self.assertEqual(runtime.remote.call_count,3)
            self.assertEqual(runtime.remote.call_args_list[0].args[0],'sudo python3 -')
            self.assertTrue(all(c.args[0].startswith('sudo cat ') for c in runtime.remote.call_args_list[1:]))

    def test_missing_snapshot_never_regenerates_or_backfills(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Mock();runtime.remote.side_effect=RuntimeError('not found')
            with self.assertRaises(RuntimeError):durable_host_stat(Evidence(root),runtime,'osk8s-compute02',1)
            self.assertEqual(sum(c.args[0]=='sudo python3 -' for c in runtime.remote.call_args_list),1)
            self.assertEqual(runtime.remote.call_count,2)

    def test_stale_remote_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Mock();runtime.remote.side_effect=['',json.dumps({'time':utc(1000)})]
            with self.assertRaisesRegex(RuntimeError,'observation bound'):
                durable_host_stat(Evidence(root),runtime,'osk8s-compute02',1)

    def test_s1_failure_still_writes_standard_partial_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(Path(root)/'attempt');raw=Path(root)/'raw';raw.mkdir()
            (raw/'http.jsonl').write_text('{"index":0}\n');(raw/'decisions.jsonl').write_text('{}\n')
            runner=FreshS1.__new__(FreshS1)
            runner.case={'mode':'A'};runner.profile={'s1':{'rate':5,'rounds':100000,'seconds':1800}}
            runner.ev=ev;runner.raw={'service_before':{'pod_uid':'original'}}
            runner.s1=Mock();runner.client=Mock()
            runner.run=Mock(side_effect=RuntimeError('completion stat unavailable'))
            runner.read=Mock(return_value={'evidence':str(raw),'fresh_attempt':str(ev.directory.resolve())})
            with self.assertRaisesRegex(RuntimeError,'completion stat'):runner.finish()
            self.assertEqual((ev.directory/'requests.jsonl').read_bytes(),(raw/'http.jsonl').read_bytes())
            contract=json.loads((ev.directory/'observations/contract.json').read_text())
            self.assertTrue(contract['collection_incomplete'])
            self.assertNotIn('completion_host_metrics',contract)

    def test_recollection_never_changes_original_or_its_judgement(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(Path(root)/'attempt');runtime=Mock()
            runtime.remote.return_value='original'
            remote_file(ev,runtime.remote,'/remote/source','requests.jsonl',host='compute')
            (ev.directory/'judgement.json').write_text('{"trial_valid":false}')
            before={p.name:p.read_bytes() for p in ev.directory.iterdir() if p.is_file()}
            runtime.remote.return_value='recollected'
            output=Path(root)/'recollection'
            self.assertTrue(resume_download(ev.directory,output,runtime))
            self.assertEqual((output/'requests.jsonl').read_text(),'recollected')
            self.assertEqual(before,{p.name:p.read_bytes() for p in ev.directory.iterdir() if p.is_file()})
            with self.assertRaises(FileExistsError):resume_download(ev.directory,output,runtime)

    def test_partial_salvage_rejects_previous_attempt_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(Path(root)/'new');raw=Path(root)/'old';raw.mkdir()
            (raw/'http.jsonl').write_text('old trial')
            preserve_s1_partial(ev,{'evidence':str(raw),'fresh_attempt':'old'},{},RuntimeError('failed before ownership'))
            self.assertFalse((ev.directory/'requests.jsonl').exists())

    def test_existing_s1_log_reads_checkpoint_without_extra_queries(self):
        with tempfile.TemporaryDirectory() as root:
            runner=FreshS1.__new__(FreshS1);runner.ev=Evidence(root);runner.s1=Mock()
            original=runner.s1.k;original.return_value='existing log\n'
            def run(record,node):
                return runner.s1.k('-n','graduation-s1','logs','job/probe',timeout=10)
            with patch('fresh_scenarios.EvaluationS1.run_locked',side_effect=run):
                self.assertEqual(runner.run_locked({'job_name':'probe'},'cp'),'existing log\n')
            original.assert_called_once_with('-n','graduation-s1','logs','job/probe',timeout=10)
            self.assertIs(runner.s1.k,original)
            self.assertEqual((Path(root)/'requests-checkpoint.jsonl').read_text(),'existing log\n')


if __name__=='__main__':unittest.main()
