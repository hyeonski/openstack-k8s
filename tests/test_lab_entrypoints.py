"""Public workflows preserve failure boundaries and optional feature separation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / d) for d in ('scripts', 'experiments', 'evaluation')]
from lib.runtime import LabRuntime
from lib.state import atomic_json
from graduation_evaluation import source_files


class EntryPointTests(unittest.TestCase):
    def dispatch(self, scenario, action='run', fail=''):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            fake = folder / 'make'
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "${@: -1}" >> "$CALL_LOG"\n'
                            'if [[ "${@: -1}" == "$FAIL_TARGET" ]]; then exit 23; fi\n')
            fake.chmod(0o755)
            log = folder / 'calls'
            env = {**os.environ, 'PATH': str(folder) + os.pathsep + os.environ['PATH'],
                   'CALL_LOG': str(log), 'FAIL_TARGET': fail}
            result = subprocess.run(['bash', ROOT / 'experiments/run.sh', scenario, action],
                                    env=env, text=True, capture_output=True, cwd=folder)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_s1_prepares_then_cleans_only_after_success(self):
        result, calls = self.dispatch('s1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['graduation-s1-prepare', 'graduation-s1-spread',
                                'graduation-s1-verify', 'graduation-s1-auto',
                                'graduation-s1-auto-cleanup', 'graduation-s1-cleanup'])

    def test_failure_preserves_existing_recovery_path_and_exit_code(self):
        for failure in ('graduation-s1-spread', 'graduation-s1-auto', 'graduation-s1-auto-cleanup'):
            with self.subTest(failure=failure):
                result, calls = self.dispatch('s1', fail=failure)
                self.assertEqual(result.returncode, 23)
                self.assertEqual(calls[-1], failure)
                self.assertNotIn('graduation-s1-cleanup', calls)
                self.assertIn('retained evidence', result.stderr)

    def test_s2_s3_do_not_redeploy_foundation_or_enable_optional_features(self):
        for scenario in ('s2', 's3'):
            result, calls = self.dispatch(scenario)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, ['graduation-' + scenario, 'graduation-' + scenario + '-cleanup'])

    def test_s4_uses_existing_workflow_and_resume_never_injects(self):
        for action, target in [('run', 'graduation-s4-run'), ('resume', 'graduation-s4-resume')]:
            result, calls = self.dispatch('s4', action)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, [target])

    def test_invalid_selection_never_invokes_make(self):
        for scenario, action in [('', 'run'), ('s5', 'run'), ('s1', 'resume'), ('s2', 'delete')]:
            result, calls = self.dispatch(scenario, action)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(calls, [])

    def test_help_does_not_require_environment_or_cloud(self):
        result = subprocess.run(['make', 'help'], cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, 'ENV_OVERRIDE_FILE': '/missing/lab.env'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('make experiment SCENARIO=s1', result.stdout)
        self.assertLess(len(result.stdout.splitlines()), 25)

    def test_s2_s3_import_without_s1_or_optional_services(self):
        code = ('import sys; import graduation_s2, graduation_s3; '
                'assert not any(n.startswith(("graduation_s1", "graduation_evaluation")) '
                'for n in sys.modules)')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                env={**os.environ, 'PYTHONPATH': os.pathsep.join(
                                    str(ROOT / d) for d in ('scripts', 'experiments'))},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_freeze_covers_moved_code_shared_helpers_and_make_fragments(self):
        files = {p.relative_to(ROOT).as_posix() for p in source_files()}
        self.assertTrue({'experiments/graduation_s2.py', 'experiments/run.sh',
                         'evaluation/graduation_evaluation_case.py', 'scripts/lib/runtime.py',
                         'scripts/lib/state.py', 'make/infrastructure.mk',
                         'experiments/commands.mk', 'evaluation/commands.mk'} <= files)


class RuntimeTests(unittest.TestCase):
    def test_environment_rejects_other_profile_before_remote_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LabRuntime(SimpleNamespace(state=Path(directory), cluster='workload'))
            record = {'phase': 'ready', 'profile': {'environment': 'lab', 'project': 'p',
                                                   'zone': 'z', 'cluster': 'workload'}}
            atomic_json(Path(directory) / 'graduation-environment.json', record)
            with patch.dict(os.environ, ENVIRONMENT_NAME='lab', GCP_PROJECT_ID='p', GCP_ZONE='z'), \
                    patch('lib.runtime.command') as command:
                self.assertEqual(runtime.environment(), record)
                record['profile']['project'] = 'another-project'
                atomic_json(Path(directory) / 'graduation-environment.json', record)
                with self.assertRaisesRegex(RuntimeError, 'selected profile'):
                    runtime.environment()
                command.assert_not_called()

    def test_unstable_worker_is_rejected(self):
        with patch('lib.runtime.WorkerControl') as control:
            current = control.return_value.__enter__.return_value
            current.preflight.return_value = ('fixed', {'workers': 2})
            current.stable_workers.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'unstable'):
                LabRuntime(Mock()).worker()

    def test_openstack_arguments_stay_quoted_and_user_data_uses_temporary_file(self):
        runtime = LabRuntime(Mock())
        runtime.remote = Mock(return_value='{}')
        runtime.admin('server', 'show', 'name; touch /tmp/not-a-command')
        script = runtime.remote.call_args.args[0]
        self.assertIn("'name; touch /tmp/not-a-command'", script)
        self.assertEqual(runtime.remote.call_args.kwargs, {'timeout': 60})
        runtime.admin('server', 'create', '--user-data', '@user-data', 'test', user_data='payload')
        script = runtime.remote.call_args.args[0]
        self.assertIn('mktemp', script)
        self.assertIn('trap', script)
        self.assertIn('--user-data "$file"', script)
        self.assertNotIn('payload', script)


if __name__ == '__main__':
    unittest.main()
