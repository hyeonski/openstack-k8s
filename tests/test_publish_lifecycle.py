"""Publishing two ordinal attempts must never share a remote object key."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublishTests(unittest.TestCase):
    def test_parent_run_scopes_attempt_upload_and_retains_legacy_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            fake = bin_dir / 'gcloud'
            fake.write_text('#!/bin/sh\nif [ "$1" = projects ]; then echo 123; else printf "%s\\n" "$*" >> "$UPLOAD_LOG"; fi\n')
            fake.chmod(0o700)
            log = root / 'calls'
            env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'UPLOAD_LOG': str(log)}
            env.pop('ENV_OVERRIDE_FILE', None)
            for parent in ['autoscaler-run-one', 'autoscaler-run-two', 'legacy']:
                attempt = root / parent / 'autoscaler-cycle-attempt-001'
                attempt.mkdir(parents=True)
                (attempt / 'observability-manifest.json').write_text(json.dumps({'state': 'passed'}))
                subprocess.run(['bash', str(ROOT / 'observability/publish-run.sh'), str(attempt)],
                               env=env, check=True, capture_output=True)
            lines = log.read_text().splitlines()
            self.assertIn('/autoscaler-run-one/autoscaler-cycle-attempt-001/manifest.json', lines[0])
            self.assertIn('/autoscaler-run-two/autoscaler-cycle-attempt-001/manifest.json', lines[1])
            self.assertIn('/cloud-gcp-amd64/autoscaler-cycle-attempt-001/manifest.json', lines[2])
            self.assertTrue(all('--if-generation-match=0' in line for line in lines))
