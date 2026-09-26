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
        elif action == 'graduation-s4-observe':
            record = json.loads(self.experiment.read_text())
            record['phase'] = 'completed_with_gap'
            record['resumed_with_gap'] = True
            atomic_json(self.experiment, record)
        elif action == 'graduation-s4-cleanup':
            atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'restored',
                                       'original_mode': 'auto', 'restored_workers': 1})
            atomic_json(self.state / 'worker-control.json', {'mode': 'auto'})
        elif action == 'graduation-env-down':
            self.write_environment('stopped')
        return ''

    def fake_analysis(self, _evidence):
        return {'state': 'complete',
                'service': {'requests': 10, 'stable_success_confirmed_at': '2026-09-26T00:01:00Z'},
                'durations_seconds': {'worker': 3, 'shutoff_to_capacity_stable_seconds': 3},
                'observation_quality': {'resumed_with_gap': False,
                                        'infrastructure_snapshot_errors': {}}}

    def seed_interrupted(self, experiment_phase='injected', workflow_phase='injecting', mode='e2e'):
        self.write_environment()
        atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'prepared',
                                   'original_mode': 'auto'})
        atomic_json(self.experiment, {'environment_run_id': 'env-1', 'phase': experiment_phase,
                                      'run_id': 's4-1', 'evidence': str(self.evidence),
                                      'stop_intent_at': '2026-09-26T00:00:00Z'})
        atomic_json(self.state / 's4-workflow.json',
                    {'run_id': 'workflow-1', 'environment_run_id': 'env-1',
                     'phase': workflow_phase, 'mode': mode})
        self.steps = []

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

    def test_partial_preparation_failure_cleans_fixture_and_owned_environment(self):
        self.write_environment('stopped')
        self.steps = []

        def fails(target, timeout):
            if target[-1] == 'graduation-s4-prepare':
                self.steps.append(target[-1])
                atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'failed',
                                           'original_mode': 'auto', 'original_workers': 1,
                                           'mhc_apply_intent': True, 'app_apply_intent': True})
                raise RuntimeError('HTTP rollout timed out after partial preparation')
            return self.fake_steps(target, timeout)

        workflow = Workflow(FakeClient(self.state), runner=fails)
        with self.assertRaisesRegex(RuntimeError, 'HTTP rollout timed out'):
            workflow.run(include_environment=True)
        self.assertEqual(self.steps, ['graduation-env-ensure', 'graduation-s4-prepare',
                                      'graduation-s4-cleanup', 'graduation-env-down'])
        self.assertEqual(json.loads(self.fixture.read_text())['phase'], 'restored')
        self.assertEqual(json.loads(self.environment.read_text())['phase'], 'stopped')

    def test_resume_observes_same_fault_and_marks_gap(self):
        self.seed_interrupted()
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        incomplete = self.fake_analysis(None)
        incomplete['state'] = 'incomplete'
        incomplete['observation_quality']['resumed_with_gap'] = True
        with patch('graduation_s4_workflow.analyze', return_value=incomplete):
            result = workflow.resume()
        self.assertEqual(self.steps, ['graduation-s4-observe', 'graduation-s4-cleanup',
                                      'graduation-env-down'])
        self.assertEqual(result['phase'], 'completed_with_gap')
        self.assertEqual(result['analysis_state'], 'incomplete')

    def test_resume_after_interruption_while_observing_never_reinjects(self):
        self.seed_interrupted(experiment_phase='observing', workflow_phase='observing')
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        incomplete = self.fake_analysis(None)
        incomplete['state'] = 'incomplete'
        incomplete['observation_quality']['resumed_with_gap'] = True
        with patch('graduation_s4_workflow.analyze', return_value=incomplete):
            result = workflow.resume()
        self.assertEqual(self.steps, ['graduation-s4-observe', 'graduation-s4-cleanup',
                                      'graduation-env-down'])
        self.assertEqual(result['phase'], 'completed_with_gap')

    def test_resume_completed_fault_skips_observation_and_finished_cleanup(self):
        self.seed_interrupted(experiment_phase='completed', workflow_phase='cleaning')
        atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'restored',
                                   'original_mode': 'auto', 'restored_workers': 1})
        atomic_json(self.state / 'worker-control.json', {'mode': 'auto'})
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        with patch('graduation_s4_workflow.analyze', side_effect=self.fake_analysis):
            result = workflow.resume()
        self.assertEqual(self.steps, ['graduation-env-down'])
        self.assertEqual(result['phase'], 'completed')

    def test_resume_finishes_interrupted_environment_stop(self):
        self.seed_interrupted(experiment_phase='completed', workflow_phase='stopping-environment')
        self.write_environment('stopping')
        atomic_json(self.fixture, {'environment_run_id': 'env-1', 'phase': 'restored',
                                   'original_mode': 'auto', 'restored_workers': 1})
        atomic_json(self.state / 'worker-control.json', {'mode': 'auto'})
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        with patch('graduation_s4_workflow.analyze', side_effect=self.fake_analysis):
            result = workflow.resume()
        self.assertEqual(self.steps, ['graduation-env-down'])
        self.assertEqual(result['phase'], 'completed')

    def test_resume_refuses_fault_without_stop_intent(self):
        self.seed_interrupted()
        record = json.loads(self.experiment.read_text())
        del record['stop_intent_at']
        atomic_json(self.experiment, record)
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        with self.assertRaisesRegex(RuntimeError, 'no matching S4 stop intent'):
            workflow.resume()
        self.assertEqual(self.steps, [])

    def test_resume_refuses_unexplained_incomplete_analysis(self):
        self.seed_interrupted(experiment_phase='completed_with_gap')
        workflow = Workflow(FakeClient(self.state), runner=self.fake_steps)
        incomplete = self.fake_analysis(None)
        incomplete['state'] = 'incomplete'
        incomplete['observation_quality']['resumed_with_gap'] = True
        incomplete['observation_quality']['infrastructure_snapshot_errors'] = {'nodes': 'timeout'}
        with patch('graduation_s4_workflow.analyze', return_value=incomplete):
            with self.assertRaisesRegex(RuntimeError, 'analysis is incomplete'):
                workflow.resume()
        self.assertEqual(self.steps, ['graduation-s4-cleanup', 'graduation-env-down'])
        self.assertEqual(workflow.read()['phase'], 'failed')


if __name__ == '__main__':
    unittest.main()
