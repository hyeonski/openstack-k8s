import hashlib
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/d) for d in ('evaluation','scripts')]
from fresh_stability_release import protected_ast,artifact,MAIN,SUPPLEMENTS,validate_calibration_source,CALIBRATION_GATE_OLD,CALIBRATION_GATE_NEW
from fresh_read_registry import audit

class StabilityReleaseTests(unittest.TestCase):
    def test_reviewed_operational_function_does_not_exempt_other_science(self):
        old='SLO=50\ndef requests():\n return SLO\ndef scenario_checks():\n return 1\n'
        changed=old.replace('return 1','return 2')
        self.assertEqual(protected_ast(old,{'scenario_checks'}),protected_ast(changed,{'scenario_checks'}))
        self.assertNotEqual(protected_ast(old,{'scenario_checks'}),protected_ast(changed.replace('SLO=50','SLO=100'),{'scenario_checks'}))
        self.assertNotEqual(protected_ast(old,{'scenario_checks'}),protected_ast(changed.replace('return SLO','return SLO+1'),{'scenario_checks'}))
    def test_deferred_owned_cleanup_is_the_only_class_flag_exception(self):
        old='class FreshS1:\n def run(self):return 1\n'
        new='class FreshS1:\n defer_owned_cleanup=True\n def run(self):return 1\n'
        self.assertEqual(protected_ast(old,set()),protected_ast(new,set()))
        with self.assertRaises(ValueError):protected_ast(new.replace('=True','=False'),set())
    def test_proof_hash_is_checked_before_content(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'proof.json';path.write_text('{"passed": true}')
            ref={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            self.assertTrue(artifact(ref)['passed']);path.write_text('{"passed": false}')
            with self.assertRaises(ValueError):artifact(ref)
    def test_registry_blocks_new_calls_and_source_changes(self):
        root=Path(__file__).resolve().parents[1]
        result=audit(root);self.assertEqual(result['unregistered'],0);self.assertGreater(result['calls'],300)
        registry=json.loads((root/'config/fresh-read-registry.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config/fresh-read-registry.json';path.parent.mkdir()
            for name in registry['source_sha256']:
                target=Path(temp)/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
            registry['calls'].pop();path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(RuntimeError,'unregistered'):audit(temp)
            name=next(iter(registry['source_sha256']));target=Path(temp)/name;target.write_text(target.read_text()+'\n# unreviewed change\n')
            with self.assertRaisesRegex(RuntimeError,'source changed'):audit(temp)
    def test_calibration_compatibility_accepts_only_exact_operational_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'evaluation').mkdir()
            original='def gate():\n    while True:\n        requests = collect()\n'
            revised=original.replace('        requests = collect()', '        from fresh_read_budget import phase_deadline\n        with phase_deadline(deadline):\n            requests = collect()')
            path=root/'evaluation/fresh_baseline.py';path.write_text(revised)
            expected=hashlib.sha256(original.encode()).hexdigest()
            self.assertTrue(validate_calibration_source('evaluation/fresh_baseline.py',root,expected))
            path.write_text(revised.replace('collect()','collect_more()'))
            with self.assertRaises(ValueError):validate_calibration_source('evaluation/fresh_baseline.py',root,expected)
            path=root/'evaluation/fresh_calibration.py';path.write_text(CALIBRATION_GATE_NEW)
            self.assertTrue(validate_calibration_source('evaluation/fresh_calibration.py',root,hashlib.sha256(CALIBRATION_GATE_OLD.encode()).hexdigest()))

    def test_remaining_scope_is_exact_and_separate(self):
        self.assertEqual(MAIN,['s4-b02-off','s4-b03-off','s4-b03-on'])
        self.assertEqual(SUPPLEMENTS,['s1-b02-a','s2-b03-p','s3-b02-m3600','s3-b03-m3600'])
if __name__=='__main__':unittest.main()
