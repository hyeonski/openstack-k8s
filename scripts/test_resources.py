"""Small helpers for run-owned test resources and evidence before deletion."""
import json
import os
import time
from workload_state import save

OWNER = 'test.openstack-k8s.io/cluster'
RUN = 'test.openstack-k8s.io/run'


def delete_owned(client, plane, obj):
    meta = obj['metadata']
    kind = obj['kind'].lower()
    plural = {'pod': 'pods', 'deployment': 'deployments'}[kind]
    prefix = '/api/v1' if kind == 'pod' else '/apis/apps/v1'
    url = f"{prefix}/namespaces/{meta['namespace']}/{plural}/{meta['name']}"
    # UID precondition prevents deleting a replacement created after inspection.
    client.k(plane, 'delete', '--raw', url, '-f', '-', data=json.dumps({
        'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
        'preconditions': {'uid': meta['uid']}}))


def residues(client):
    result = []
    for plane in ('m', 'w'):
        for resource in ('pods', 'deployments'):
            for obj in client.get(plane, resource, '-A', '-l', OWNER + '=' + client.cluster)['items']:
                meta = obj['metadata']
                if not meta.get('labels', {}).get(RUN) or not meta['name'].startswith(('ca-cycle-', 'infra-probe-')):
                    raise RuntimeError('test cluster label without recognized run ownership: ' + meta['name'])
                result.append((plane, obj))
    # Legacy exact names need the old repository ownership label as well.
    for resource, name in [('deployment', os.environ['CLUSTER_AUTOSCALER_TEST_NAME']),
                           ('pod', os.environ['CLUSTER_AUTOSCALER_TARGETED_PROBE_NAME'])]:
        raw = client.k('w', 'get', resource, name, '-n', os.environ['CLUSTER_AUTOSCALER_TEST_NAMESPACE'], '--ignore-not-found', '-o', 'json')
        if raw.strip():
            obj = json.loads(raw)
            if obj['metadata'].get('labels', {}).get('app.kubernetes.io/part-of') != 'openstack-k8s-m3':
                raise RuntimeError('legacy name has no repository ownership label: ' + name)
            result.append(('w', obj))
            if resource == 'deployment':
                selector = ','.join(k + '=' + v for k, v in obj['spec']['selector']['matchLabels'].items())
                replicasets = client.get('w', 'replicasets', '-n', obj['metadata']['namespace'], '-l', selector)['items']
                owned_rs = {rs['metadata']['uid'] for rs in replicasets if any(ref['uid'] == obj['metadata']['uid'] for ref in rs['metadata'].get('ownerReferences', []))}
                result.extend(('w', p) for p in client.get('w', 'pods', '-n', obj['metadata']['namespace'], '-l', selector)['items']
                              if any(ref['uid'] in owned_rs for ref in p['metadata'].get('ownerReferences', [])))
    # Older workload probes had no ownership labels. Detect and stop; never guess deletion authority.
    for plane, namespace, name in [('m', client.ns, client.cluster + '-api-probe'),
                                    ('w', 'default', client.cluster + '-cni-probe')]:
        raw = client.k(plane, 'get', 'pod', name, '-n', namespace, '--ignore-not-found', '-o', 'json')
        if raw.strip():
            obj = json.loads(raw)
            raise RuntimeError(f'legacy probe requires explicit ownership review: {plane}/{namespace}/{name} uid={obj["metadata"]["uid"]}')
    return result


def cleanup(client, path, run_id=None):
    client.deadline = time.monotonic() + 300
    old = residues(client)
    if run_id:
        old = [(p, o) for p, o in old if o['metadata'].get('labels', {}).get(RUN) == run_id]
    save(path / 'resources-before.json', [{'plane': p, 'object': o} for p, o in old])
    # Save events and Pod logs before any deletion; a failed evidence read aborts cleanup.
    for plane in ('m', 'w'):
        save(path / (plane + '-events.json'), client.get(plane, 'events', '-A'))
    for plane, obj in old:
        if obj['kind'] != 'Pod':
            continue
        status = obj.get('status', {})
        containers = status.get('initContainerStatuses', []) + status.get('containerStatuses', []) + status.get('ephemeralContainerStatuses', [])
        missing = []
        for container in containers:
            state = container.get('state', {})
            previous = not ('running' in state or 'terminated' in state) and 'terminated' in container.get('lastState', {})
            if not ('running' in state or 'terminated' in state or previous):
                missing.append({'container': container['name'], 'state': state, 'reason': 'container has not started; no log exists yet'})
                continue
            args = ['--previous'] if previous else []
            save(path / (plane + '-' + obj['metadata']['uid'] + '-' + container['name'] + '.log'), client.k(
                plane, 'logs', obj['metadata']['name'], '-n', obj['metadata']['namespace'],
                '-c', container['name'], '--tail=1000', *args))
        if missing or not containers:
            save(path / (plane + '-' + obj['metadata']['uid'] + '-logs-unavailable.json'),
                 {'pod_uid': obj['metadata']['uid'], 'containers': missing,
                  'reason': 'containers not started' if containers else 'container status not reported yet'})
    # Controllers first; child Pods are removed through their controller's ownership.
    for plane, obj in old:
        if obj['kind'] == 'Deployment' or not obj['metadata'].get('ownerReferences'):
            delete_owned(client, plane, obj)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        remaining = residues(client)
        if run_id:
            remaining = [(p, o) for p, o in remaining if o['metadata'].get('labels', {}).get(RUN) == run_id]
        if not remaining:
            save(path / 'cleanup.json', {'status': 'deleted', 'uids': [o['metadata']['uid'] for _, o in old]})
            client.deadline = None
            return
        time.sleep(3)
    raise TimeoutError('test resource cleanup timeout; evidence preserved')


class OwnedProbeReads:
    """Bound only post-scale workload probe reads; mutations delegate once."""
    def __init__(self, client, path, cluster, *, clock=None, sleep=None):
        import hashlib
        self.client, self.path = client, path
        self.clock, self.sleep = clock or time.monotonic, sleep or time.sleep
        self.enabled = False
        self.nodes = {}
        descriptor = os.environ.get('WORKER_CONTROL_LOCK_FD')
        if descriptor is None:
            return
        journal = client.state / 'worker-operation.json'
        if not journal.exists():
            return
        self.journal = json.loads(journal.read_text())
        if self.journal.get('kind') != 'manual':
            return
        actual = os.fstat(int(descriptor)); expected = os.stat(client.state / 'worker-operation.lock')
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError('probe worker lock identity changed')
        if cluster['metadata']['uid'] != self.journal['identity']['cluster_uid']:
            raise RuntimeError('probe cluster identity changed')
        self.kubeconfig = client.state / 'kubeconfigs' / (client.cluster + '.yaml')
        self.kubeconfig_sha = hashlib.sha256(self.kubeconfig.read_bytes()).hexdigest()
        self.enabled = True
        save(self.path / 'read-guard.json', {'enabled': True, 'worker_target': self.journal['target'],
             'identity': self.journal['identity'], 'kubeconfig_sha256': self.kubeconfig_sha,
             'worker_lock_inherited': True, 'mutation_repeated': False, 'ensure_called': False})

    def _log(self, **values):
        from workload_state import now
        self.path.mkdir(parents=True, exist_ok=True)
        with (self.path / 'read-attempts.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(utc=now(), observation_filled=False, **values)) + '\n')

    def _wait_transport(self, remaining):
        import fcntl, socket
        port = os.environ.get('WORKLOAD_LOCAL_API_PORT')
        if not port:
            return
        # Wait for the existing reconnect owner; never run ensure here.
        with (self.client.state / 'workload-api-reconnect.lock').open('a+') as lock:
            while True:
                remaining()
                try:
                    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.sleep(min(.1, remaining())); continue
                try:
                    with socket.create_connection(('127.0.0.1', int(port)), timeout=min(1, remaining())):
                        return
                except OSError:
                    self.sleep(min(.2, remaining()))
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _identity(self, remaining, owned, deleting):
        import hashlib
        from worker_control import WorkerControl
        remaining()
        journal = json.loads((self.client.state / 'worker-operation.json').read_text())
        if journal != self.journal or hashlib.sha256(self.kubeconfig.read_bytes()).hexdigest() != self.kubeconfig_sha:
            raise RuntimeError('probe worker journal/kubeconfig changed')
        control = WorkerControl(self.client)
        observed = control.observe(); control.require_identity(journal, observed)
        if not control.stable_workers(observed) or observed['workers'] != journal['target'] or observed['ca_replicas'] != 0:
            raise RuntimeError('probe scale target has not actually converged')
        remaining()
        if owned is not None:
            meta = owned['metadata']
            raw = self.client.k('w', 'get', 'pod', meta['name'], '-n', meta['namespace'], '--ignore-not-found', '-o', 'json')
            remaining()
            if not raw.strip():
                if deleting:return True
                raise RuntimeError('probe Pod disappeared during read')
            current = json.loads(raw)
            if (current['metadata']['uid'] != meta['uid']
                    or current['metadata'].get('labels', {}).get(OWNER) != meta.get('labels', {}).get(OWNER)
                    or current['metadata'].get('labels', {}).get(RUN) != meta.get('labels', {}).get(RUN)
                    or current['spec'].get('nodeName') != owned['spec'].get('nodeName')):
                raise RuntimeError('probe Pod/run/Node identity changed')
            node_name = current['spec'].get('nodeName')
            if node_name:
                current_node = self.client.get('w', 'node', node_name)
                if self.nodes.get(node_name) != current_node['metadata']['uid']:
                    raise RuntimeError('probe Node UID changed')
                remaining()
        return False

    def get(self, plane, resource, *args, owned=None):
        result = json.loads(self.k(plane, 'get', resource, *args, '-o', 'json', owned=owned))
        if self.enabled and plane == 'w' and resource == 'nodes':
            self.nodes = {n['metadata']['name']: n['metadata']['uid'] for n in result['items']}
        return result

    def k(self, plane, *args, owned=None):
        args = tuple(args)
        if not self.enabled or plane != 'w':
            return self.client.k(plane, *args)
        deleting = False
        allowed = args in (('get', 'nodes', '-o', 'json'), ('get', '--raw=/readyz'))
        if owned is not None:
            m = owned['metadata']; name, ns, uid = m['name'], m['namespace'], m['uid']
            if m.get('labels', {}).get(OWNER) != self.client.cluster or not m.get('labels', {}).get(RUN):
                raise ValueError('probe read target has no owned run label')
            deleting = args == ('wait', '--for=delete', 'pod/' + name, '-n', ns, '--timeout=20s')
            allowed = allowed or deleting or args in (
                ('get', 'pod', name, '-n', ns, '-o', 'json'),
                ('get', 'events', '-n', ns, '--field-selector', 'involvedObject.uid=' + uid, '-o', 'json'),
                ('logs', name, '-n', ns))
        if not allowed:
            raise ValueError('not a named owned workload probe read')
        end = self.clock() + self.client.remaining(30)
        previous = self.client.deadline
        self.client.deadline = end if previous is None else min(previous, end)
        def remaining():
            left = end - self.clock()
            if left <= 0:raise TimeoutError('owned probe read cumulative deadline exhausted')
            return left
        try:
            if os.environ.get('FRESH_READ_CONTEXT'):
                from lib.fresh_reads import ROOT
                import sys
                if str(ROOT/'evaluation') not in sys.path:sys.path.insert(0,str(ROOT/'evaluation'))
                from fresh_read_budget import read_with_budget
                from fresh_transport import deadline_args
                deleted=[False]
                def verify(left):
                    deleted[0]=self._identity(left,owned,deleting)
                return read_with_budget(
                    lambda left:'' if deleted[0] else self.client.k(plane,*deadline_args(args,left())),
                    timeout=remaining(),identity=verify,reconnect=self._wait_transport,
                    label='owned-worker-probe:'+repr(args),evidence=self.path,
                    clock=self.clock,sleep=self.sleep)
            for attempt in range(1, 4):
                remaining()
                try:
                    answer = self.client.k(plane, *args)
                    remaining()
                except Exception as error:
                    self._log(args=args, attempt=attempt, error=type(error).__name__ + ': ' + str(error))
                    text = str(error).lower()
                    permanent = any(w in text for w in ('forbidden', 'unauthorized', 'permission denied', 'notfound', 'not found', 'certificate'))
                    transient = any(w in text for w in ('connection refused', 'connection reset', 'unexpected eof', 'i/o timeout', 'tls handshake timeout', 'context deadline exceeded'))
                    if permanent or not transient:raise
                    if attempt == 3:raise TimeoutError('owned probe read attempt limit exhausted') from error
                    self._wait_transport(remaining)
                    if self._identity(remaining, owned, deleting):
                        self._log(args=args, attempt=attempt, captured=True, actual_deleted_pod_absence=True)
                        return ''
                    self.sleep(min(attempt, remaining())); remaining()
                else:
                    if attempt > 1:
                        self._identity(remaining, owned, deleting); remaining()
                        self._log(args=args, attempt=attempt, captured=True)
                    return answer
        finally:
            self.client.deadline = previous


def probe(client, path, run_id, owner_id=None):
    if os.environ.get("FRESH_READ_CONTEXT"):
        from lib.neutron_members import reconcile_before_probe
        reconcile_before_probe(client, path)
    labels = {OWNER: client.cluster, RUN: owner_id or run_id}
    cluster = client.get('m', 'cluster', client.cluster, '-n', client.ns)
    endpoint = cluster['spec']['controlPlaneEndpoint']
    reads = OwnedProbeReads(client, path, cluster)
    tests = [('m', client.ns, 'api', None, ['nc', '-z', '-w', '15', endpoint['host'], str(endpoint['port'])])]
    nodes = reads.get('w', 'nodes')['items']
    for i, node in enumerate(nodes):
        tests.append(('w', 'default', 'dns-' + str(i), node['metadata']['name'],
                      ['sh', '-ceu', 'nslookup kubernetes.default.svc.cluster.local >/dev/null']))
    for plane, namespace, suffix, node, argv in tests:
        client.deadline = time.monotonic() + 360
        name = 'infra-probe-' + run_id + '-' + suffix
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace, 'labels': labels},
               'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 240, 'terminationGracePeriodSeconds': 0,
                        'containers': [{'name': 'probe', 'image': os.environ['CLUSTER_AUTOSCALER_TEST_IMAGE'], 'command': argv}]}}
        if node:
            pod['spec']['nodeName'] = node
        obj = json.loads(client.k(plane, 'create', '-f', '-', '-o', 'json', data=json.dumps(pod)))
        save(path / (suffix + '-created.json'), obj)
        deadline = time.monotonic() + 300
        while True:
            observed = reads.get(plane, 'pod', name, '-n', namespace, owned=obj)
            save(path / (suffix + '.json'), observed)
            phase = observed.get('status', {}).get('phase')
            if phase in ('Succeeded', 'Failed') or time.monotonic() >= deadline:
                save(path / (suffix + '-events.json'), reads.get(plane, 'events', '-n', namespace, '--field-selector', 'involvedObject.uid=' + obj['metadata']['uid'], owned=obj))
                save(path / (suffix + '.log'), reads.k(plane, 'logs', name, '-n', namespace, owned=obj))
                if phase != 'Succeeded':
                    raise RuntimeError('active probe failed/timed out; Pod preserved: ' + name)
                delete_owned(client, plane, obj)
                # Deletion must complete before a subsequent scale-in stage.
                reads.k(plane, 'wait', '--for=delete', 'pod/' + name, '-n', namespace, '--timeout=20s', owned=obj)
                break
            time.sleep(3)
    client.deadline = None
    save(path / 'api-readyz.txt', reads.k('w', 'get', '--raw=/readyz'))


def main():
    import sys
    import uuid
    from workload_state import Client, artifact_dir
    client = Client()
    path = artifact_dir('workload-' + sys.argv[1])
    print('evidence=' + str(path), flush=True)
    if sys.argv[1] == 'cleanup':
        cleanup(client, path)
    else:
        try:
            probe(client, path, uuid.uuid4().hex[:12])
        except BaseException:
            from workload_state import diagnostics
            diagnostics(path)
            raise


if __name__ == '__main__':
    main()
