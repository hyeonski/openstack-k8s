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


def probe(client, path, run_id, owner_id=None):
    labels = {OWNER: client.cluster, RUN: owner_id or run_id}
    cluster = client.get('m', 'cluster', client.cluster, '-n', client.ns)
    endpoint = cluster['spec']['controlPlaneEndpoint']
    tests = [('m', client.ns, 'api', None, ['nc', '-z', '-w', '15', endpoint['host'], str(endpoint['port'])])]
    nodes = client.get('w', 'nodes')['items']
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
            observed = client.get(plane, 'pod', name, '-n', namespace)
            save(path / (suffix + '.json'), observed)
            phase = observed.get('status', {}).get('phase')
            if phase in ('Succeeded', 'Failed') or time.monotonic() >= deadline:
                save(path / (suffix + '-events.json'), client.get(plane, 'events', '-n', namespace, '--field-selector', 'involvedObject.uid=' + obj['metadata']['uid']))
                save(path / (suffix + '.log'), client.k(plane, 'logs', name, '-n', namespace))
                if phase != 'Succeeded':
                    raise RuntimeError('active probe failed/timed out; Pod preserved: ' + name)
                delete_owned(client, plane, obj)
                # Deletion must complete before a subsequent scale-in stage.
                client.k(plane, 'wait', '--for=delete', 'pod/' + name, '-n', namespace, '--timeout=20s')
                break
            time.sleep(3)
    client.deadline = None
    save(path / 'api-readyz.txt', client.k('w', 'get', '--raw=/readyz'))


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
