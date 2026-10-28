"""Read one existing S3 process capture without mixing rule-check output."""
import json
import shlex

from fresh_collection import checkpoint_text


def read_s3_capture(runner, source):
    run = runner.record['run_id']
    path = '/run/osk8s-s3-capture-' + run + '.json'
    # iptables -C may print the matching rule even on success. Its exit status
    # still gates the file read; stderr and failures remain visible to the caller.
    script = ('test "$(cat /run/osk8s-s3-owner)" = ' + shlex.quote(run) +
              ' && iptables -C OUTPUT -j OSK8S_S3_OUT >/dev/null' +
              ' && iptables -C FORWARD -j OSK8S_S3_DB >/dev/null' +
              ' && cat ' + shlex.quote(path))
    raw = runner.read_guest(source, script)
    checkpoint_text(runner.ev.directory/'old-db-running-after-fault-response.txt', raw)
    return json.loads(raw)
