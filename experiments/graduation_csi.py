#!/usr/bin/env python3
"""Install the vendored Cinder CSI version without logging credentials."""
import json
from graduation_recovery import RecoveryLab
from workload_state import ROOT


def main():
    lab = RecoveryLab('s3')
    # Read the pre-existing restricted application credential into memory only.
    code = '''import yaml,json
with open('/etc/kolla/capi-clouds.yaml') as stream:
 auth=yaml.safe_load(stream)['clouds']['capi']['auth']
print(json.dumps(auth))
'''
    auth = json.loads(lab.remote('sudo /opt/kolla-venv/bin/python3 -', data=code))
    config = '[Global]\n' + '\n'.join(key + '=' + auth[source] for key, source in (
        ('auth-url', 'auth_url'), ('application-credential-id', 'application_credential_id'),
        ('application-credential-secret', 'application_credential_secret'))) + '\nregion=RegionOne\n'
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {
        'name': 'graduation-cinder-config', 'namespace': 'kube-system',
        'labels': {'openstack-k8s.dev/managed-by': 'graduation-foundation'}},
        'stringData': {'cloud.conf': config}}
    old = lab.k('get', 'secret', 'graduation-cinder-config', '-n', 'kube-system', '--ignore-not-found', '-o', 'json')
    if old and json.loads(old)['metadata'].get('labels', {}).get('openstack-k8s.dev/managed-by') != 'graduation-foundation':
        raise RuntimeError('unowned CSI credential Secret exists')
    lab.apply(secret)
    lab.k('apply', '-k', ROOT / 'kubernetes/graduation-s3/csi')
    lab.k('apply', '-f', ROOT / 'kubernetes/graduation-s3/storageclass.yaml')
    for kind in ('deployment/csi-cinder-controllerplugin', 'daemonset/csi-cinder-nodeplugin'):
        lab.k('-n', 'kube-system', 'rollout', 'status', kind, '--timeout=10m', timeout=660)
    print('Cinder CSI v1.35.0 controller/node plugins ready; graduation-cinder StorageClass installed.')


if __name__ == '__main__':
    main()
