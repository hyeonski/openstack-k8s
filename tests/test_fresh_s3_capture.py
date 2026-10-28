import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/x) for x in ('evaluation','scripts','experiments')]
from fresh_s3_capture import read_s3_capture
from fresh_evidence import Evidence


class S3CaptureTests(unittest.TestCase):
    def run_fixture(self, root, *, fail=False, owner='fixture', raw='{"containers":[{"id":"owned"}]}'):
        path=Path(root);(path/'owner').write_text(owner);(path/'capture').write_text(raw)
        runner=SimpleNamespace(record={'run_id':'fixture'},ev=Evidence(path/'evidence'),guest=Mock())
        def guest_read(source,script):
            script=script.replace('/run/osk8s-s3-owner',str(path/'owner')).replace('/run/osk8s-s3-capture-fixture.json',str(path/'capture'))
            function='iptables() { printf "%s\\n" "matched rule from iptables -C"; '
            function+=('echo "rule missing" >&2; return 1;' if fail else 'return 0;')+' };\n'
            p=subprocess.run(['bash','-c',function+script],text=True,capture_output=True)
            if p.returncode:raise RuntimeError(p.stderr or 'ownership/rule check failed')
            return p.stdout
        runner.read_guest=Mock(side_effect=guest_read)
        return runner

    def test_matching_rule_stdout_is_excluded_from_json(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.run_fixture(root)
            self.assertEqual(read_s3_capture(runner,{'id':'source'}),{'containers':[{'id':'owned'}]})
            runner.read_guest.assert_called_once();runner.guest.assert_not_called()
            self.assertEqual((runner.ev.directory/'old-db-running-after-fault-response.txt').read_text(),'{"containers":[{"id":"owned"}]}')

    def test_missing_rule_or_changed_owner_prevents_capture_acceptance(self):
        for args in ({'fail':True},{'owner':'another-run'}):
            with tempfile.TemporaryDirectory() as root:
                runner=self.run_fixture(root,**args)
                with self.assertRaises(RuntimeError):read_s3_capture(runner,{})
                runner.read_guest.assert_called_once();runner.guest.assert_not_called()
                self.assertFalse((runner.ev.directory/'old-db-running-after-fault-response.txt').exists())

    def test_malformed_response_is_preserved_without_recreating_capture(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.run_fixture(root,raw='not json')
            with self.assertRaises(json.JSONDecodeError):read_s3_capture(runner,{})
            self.assertEqual((runner.ev.directory/'old-db-running-after-fault-response.txt').read_text(),'not json')
            runner.read_guest.assert_called_once();runner.guest.assert_not_called()

if __name__=='__main__':unittest.main()
