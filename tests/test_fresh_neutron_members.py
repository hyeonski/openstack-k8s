import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/x) for x in ('scripts','evaluation','experiments')]
from lib import neutron_members as nm

class Runtime:
    def __init__(self,states,fail=False,replaced=False):self.states=states;self.calls=[];self.fail=fail;self.replaced=replaced
    def remote(self,cmd,host,timeout):
        self.calls.append((host,cmd))
        if cmd.startswith('sudo docker inspect'):
            return json.dumps([{'Id':host+('-new' if self.replaced else '-id'),'Name':'/neutron_openvswitch_agent','State':{'Running':True}}])
        if cmd.startswith('sudo docker restart'):
            if self.fail:raise TimeoutError('ambiguous SSH outcome')
            self.states[host]=['10.6.0.47'];return 'neutron_openvswitch_agent'
        return 'create NIPv4test hash:net family inet\n'+''.join('add NIPv4test '+v+'\n' for v in self.states[host])

class NeutronMembershipTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.journal=self.path/'journal.json';self.ctx={'environment_run_id':'env-one'};self.expected={'NIPv4test':['10.6.0.47']}
    def tearDown(self):self.tmp.cleanup()
    def run_reconcile(self,runtime,path=None):
        with patch.object(nm,'read',side_effect=lambda label,fn,timeout:fn(timeout)):
            return nm.reconcile_hosts(runtime,sorted(runtime.states),self.expected,path or self.path,self.journal,self.ctx,lambda:30,lambda:None,lambda:None)
    def test_correct_hosts_are_not_restarted(self):
        r=Runtime({'compute1':['10.6.0.47'],'compute2':['10.6.0.47']});self.assertEqual(self.run_reconcile(r),[]);self.assertFalse(any('restart' in cmd for _,cmd in r.calls));self.assertFalse(self.journal.exists())
    def test_missing_current_or_stale_deleted_members_restart_only_affected_host_once(self):
        for wrong in (['10.6.0.179'],['10.6.0.47','10.6.0.237']):
            r=Runtime({'compute1':wrong,'compute2':['10.6.0.47']});self.assertEqual(self.run_reconcile(r),['compute1']);self.assertEqual(sum('restart' in cmd for _,cmd in r.calls),1);self.assertFalse(self.journal.exists())
    def test_ambiguous_restart_is_not_replayed(self):
        r=Runtime({'compute1':['10.6.0.179']},fail=True)
        with self.assertRaises(TimeoutError):self.run_reconcile(r)
        self.assertTrue(self.journal.exists())
        with self.assertRaisesRegex(RuntimeError,'no replay'):self.run_reconcile(r)
        self.assertEqual(sum('restart' in cmd for _,cmd in r.calls),1)
        r.states['compute1']=['10.6.0.47'];self.assertEqual(self.run_reconcile(r),[]);self.assertFalse(self.journal.exists())
    def test_pending_restart_cannot_be_resolved_on_replaced_container(self):
        self.journal.write_text(json.dumps({'host':'compute1','environment_run_id':'env-one','container_id':'compute1-id'}));r=Runtime({'compute1':['10.6.0.47']},replaced=True)
        with self.assertRaises(RuntimeError):self.run_reconcile(r)
        self.assertFalse(any('restart' in cmd for _,cmd in r.calls))
    def test_measurement_lease_forbids_network_reconciliation(self):
        with patch.dict(os.environ,{'FRESH_CLOCK_TOKEN':'active'}):
            with self.assertRaisesRegex(RuntimeError,'during measurement'):nm.require_idle_clock()
    def test_missing_sets_and_broader_networks_are_rejected(self):
        for raw in ('','create NIPv4test hash:net\nadd NIPv4test 10.6.0.0/24\n'):
            with self.assertRaises(ValueError):nm.parse_sets(raw,['NIPv4test'])
        self.assertEqual(nm.set_name('803bc172-4953-464f-bd7f-6999ef65e5aa'),'NIPv4803bc172-4953-464f-bd7f-')
    def test_policy_or_membership_change_after_restart_blocks_probe(self):
        snapshot=dict(bindings=[{'host':'compute1'}],expected=self.expected,groups={'policy':'unchanged'})
        client=SimpleNamespace(state=self.path)
        with patch.object(nm,'context',return_value=self.ctx),patch.object(nm,'require_idle_clock'),patch.object(nm,'identity'),patch.object(nm,'LabRuntime'),patch.object(nm,'authoritative',side_effect=[snapshot,{**snapshot,'groups':{'policy':'changed'}}]),patch.object(nm,'reconcile_hosts',return_value=['compute1']):
            with self.assertRaisesRegex(RuntimeError,'policy or authoritative membership changed'):nm.reconcile_before_probe(client,self.path/'probe')

if __name__=='__main__':unittest.main()
