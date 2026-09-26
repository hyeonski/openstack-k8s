"""The composite runner must preserve stage order and not hide uncertain faults."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from graduation_env import atomic_json
from graduation_s4_workflow import Workflow


class FakeClient:
    def __init__(self, state):
        self.state = state
        self.cluster = 'workload'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.environment = self.state / 'graduation-environment.json'
        self.fixture = self.state / 's4-preparation.json'
        self.experiment = self.state / 's4-experiment.json'
        self.evidence = self.state / 'evidence'
        self.evidence.mkdir()
        self.profile = {'environment': 'test', 'project': 'project', 'zone': 'zone', 'cluster': 'workload'}
        self.env = patch.dict('os.environ', {'ENVIRONMENT_NAME': 'test', 'GCP_PROJECT_ID': 'project',
                                            'GCP_ZONE': 'zone'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_environment(self, phase='ready'):
        atomic_json(self.environment, {'run_id': 'env-1', 'phase': phase, 'profile': self.profile})

    def fake_steps(self, target, timeout):
        action = target[-1]
        self.steps.append(action)
        if action == 'graduation-env-ensure':
            self.write_environment()
        elif action == 'graduation-s4-prepare':
            atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'prepared',
                                       'original_mode': 'auto'})
        elif action == 'graduation-s4-inject':
            atomic_json(self.experiment, {'environment_run_id': 'env-1', 'phase': 'completed',
                                          'run_id': 's4-1', 'evidence': str(self.evidence)})
        elif action == 'graduation-s4-cleanup':
            atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'restored',
                                       'original_mode': 'auto', 'restored_workers': 1})
            atomic_json(self.state / 'worker-control.json', {'mode': 'auto'})
        elif action == 'graduation-env-down':
            self.write_environment('stopped')
        return ''

    def fake_analysis(self, _evidence):
        return {'state': 'complete', 'service': {'requests': 10}, 'durations_seconds': {'worker': 3}}

    def test_scenario_does_not_reprepare_environment_or_stop_hosts(self):
        self.write_environment()
        self.steps = []
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        with patch('graduation_s4_workflow.analyze', side_effect=self.fake_analysis):
            result = workflow.run()
        self.assertEqual(self.steps, ['graduation-s4-prepare', 'graduation-s4-inject',
                                      'graduation-s4-cleanup'])
        self.assertEqual(result['phase'], 'completed')
        self.assertEqual(json.loads(self.environment.read_text())['phase'], 'ready')

    def test_e2e_ensures_then_stops_only_after_cleanup(self):
        self.write_environment('stopped')
        self.steps = []
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        with patch('graduation_s4_workflow.analyze', side_effect=self.fake_analysis):
            result = workflow.run(include_environment=True)
        self.assertEqual(self.steps, ['graduation-env-ensure', 'graduation-s4-prepare',
                                      'graduation-s4-inject', 'graduation-s4-cleanup',
                                      'graduation-env-down'])
        self.assertEqual(result['phase'], 'completed')
        self.assertEqual(json.loads(self.environment.read_text())['phase'], 'stopped')

    def test_uncertain_stop_preserves_fixture_and_hosts(self):
        self.write_environment()
        self.steps = []
        def fails(target, timeout):
            if target[-1] == 'graduation-s4-inject':
                atomic_json(self.experiment, {'environment_run_id': 'env-1',
                    'phase': 'stop-intent', 'stop_intent_at': '2026-09-26T00:00:00Z'})
                raise RuntimeError('injection interrupted')
            return self.fake_steps(target, timeout)
        workflow = Workflow(FakeClient(self.state), runner=fails)
        with self.assertRaisesRegex(RuntimeError, 'injection interrupted'):
            workflow.run(include_environment=True)
        self.assertNotIn('graduation-s4-cleanup', self.steps)
        self.assertNotIn('graduation-env-down', self.steps)
        self.assertEqual(workflow.read()['phase'], 'failed')
        self.assertEqual(json.loads(self.fixture.read_text())['phase'], 'prepared')

    def test_failure_before_stop_cleans_fixture_and_owned_environment(self):
        self.write_environment('stopped')
        self.steps = []
        def fails(target, timeout):
            if target[-1] == 'graduation-s4-inject':
                raise RuntimeError('preflight failed before stop')
            return self.fake_steps(target, timeout)
        workflow = Workflow(FakeClient(self.state), runner=fails)
        with self.assertRaisesRegex(RuntimeError, 'preflight failed before stop'):
            workflow.run(include_environment=True)
        self.assertEqual(self.steps[-2:], ['graduation-s4-cleanup', 'graduation-env-down'])
        self.assertEqual(json.loads(self.environment.read_text())['phase'], 'stopped')


if __name__ == '__main__':
    unittest.main()
