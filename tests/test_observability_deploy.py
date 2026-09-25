import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GatewayCertificateTests(unittest.TestCase):
    def test_mismatched_gateway_is_refused_and_matching_gateway_accepted(self):
        source = (ROOT / 'observability/deploy-clusters.sh').read_text().split('case "${action}" in')[0]
        source = source.replace('ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"', 'ROOT=' + str(ROOT))
        for actual, code in [('selected-ca', 0), ('other-ca', 1)]:
            script = source + '''
openssl() { echo 'SHA256(ca.crt)= selected-ca'; }
run_on() { echo "$ACTUAL_CA  /etc/osk8s-observability/ca.crt"; }
verify_gateway_ca
echo 'gateway verified'
'''
            env = {**os.environ, 'ACTUAL_CA': actual}
            env.pop('ENV_OVERRIDE_FILE', None)
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, code, result.stderr)
            if code:
                self.assertIn('gateway CA differs', result.stderr)
                self.assertNotIn('gateway verified', result.stdout)
