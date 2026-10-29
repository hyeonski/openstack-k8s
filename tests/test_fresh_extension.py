import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/d) for d in ('evaluation','scripts','experiments')]
from fresh_campaign import FreshCampaign, check_frozen
from fresh_extension import freeze_extension, PLAN
from fresh_fake import FakeBackend, synthetic_profile
from lib.state import atomic_json
from fresh_analysis import _judge, rows, read
from fresh_evidence import Evidence
from fresh_extension import judge_split_only


def profile():return json.loads((ROOT/'config/graduation-evaluation-fresh.json').read_text())


class ExtensionTests(unittest.TestCase):
    def test_extension_freeze_runs_split_only_and_anchor_once(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(profile()))
            campaign=freeze_extension(source,Path(root)/'extension',ROOT,synthetic=True)
            frozen=check_frozen(campaign)
            self.assertEqual([(c['id'],c['mode'],c['purpose']) for c in frozen['cases']],[(i,m,'extension') for i,m,_ in PLAN])
            FreshCampaign(campaign,FakeBackend()).run()
            data=check_frozen(campaign)
            for case in data['cases']:
                self.assertEqual(len(case['attempts']),1)
                judgement=case['judgement']
                self.assertTrue(judgement['trial_valid'],judgement)
                if case['mode']=='S':
                    self.assertEqual(judgement['checks'].get('split_only'),True)
                    self.assertNotIn('split_and_qos',judgement['checks'])
                    self.assertTrue(judgement['safety'])
                    seal=read(campaign/case['attempts'][0]['path']/'measurement-sealed.json')
                    self.assertTrue(seal['provisional_measurement_audit']['checks']['split_only'])
                else:
                    self.assertEqual(judgement['checks'].get('split_and_qos'),True)

    def test_extension_cap_is_one_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'profile.json';atomic_json(source,synthetic_profile(profile()))
            campaign=freeze_extension(source,Path(root)/'extension',ROOT,synthetic=True)
            fake=FakeBackend(unrecovered=True)
            FreshCampaign(campaign,fake).run(limit=1)
            data=json.loads((campaign/'campaign.json').read_text())
            data['cases'][0]['judgement']['trial_valid']=False
            atomic_json(campaign/'campaign.json',data)
            with self.assertRaisesRegex(ValueError,'retry cap'):
                FreshCampaign(campaign,fake).run(retry_case=PLAN[0][0])

    def test_split_only_never_sets_qos(self):
        tree=ast.parse((ROOT/'evaluation/fresh_scenarios.py').read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='split_if_enabled')
        guarded=[n for n in ast.walk(method) if isinstance(n,ast.If) and "self.case['mode'] == 'P'" in ast.unparse(n.test)]
        calls=[ast.unparse(n) for n in ast.walk(method) if isinstance(n,ast.Call) and 'set_rate' in ast.unparse(n.func)]
        self.assertEqual(len(calls),1)
        self.assertTrue(any('set_rate' in ast.unparse(g) for g in guarded))

    def test_real_split_path_has_identical_events_target_and_patch_except_qos(self):
        from fresh_scenarios import FreshS2
        traces={}
        for mode in ('P','S','M'):
            runner=FreshS2.__new__(FreshS2)
            runner.case={'mode':mode};runner.ev=Mock();runner.ns='fixture'
            runner.set_rate=Mock();runner.k=Mock();runner.ready=Mock(return_value=True)
            runner.pods=Mock(return_value=[{'spec':{'nodeName':'destination'}}])
            with patch('fresh_scenarios.wait_for',side_effect=lambda f:f()):
                moved=runner.split_if_enabled({}, {'node':'destination','port':{'id':'port-b'}}, 6000)
            traces[mode]=(moved,runner.ev.mock_calls,runner.k.mock_calls,runner.ready.mock_calls,runner.pods.mock_calls)
            self.assertEqual(runner.set_rate.call_count, int(mode=='P'))
        self.assertEqual(traces['P'],traces['S'])
        self.assertFalse(traces['M'][0]);self.assertEqual(traces['M'][1],[])

    def test_unattached_qos_policy_is_deleted_without_port_unset(self):
        from experiments.graduation_s2 import S2
        lab=S2.__new__(S2)
        lab.record={'phase':'rule-created','policy_id':'owned','workers':[{}, {'port':{'id':'b'}}]}
        for name in ('acquire','ownership','delete_namespace','save','restore_workers','write'):
            setattr(lab,name,Mock())
        lab.admin=Mock()
        lab.admin_json=Mock(side_effect=[{'id':'b','qos_policy_id':None},
                                        {'id':'b','qos_policy_id':None},[{'ID':'owned'}]])
        lab.cleanup()
        lab.admin.assert_called_once_with('network','qos','policy','delete','owned')
        lab.write.assert_called_once_with('cleaned',cleanup_errors=[])

    def test_owned_6000_rule_readback_needs_no_port_attachment(self):
        from fresh_scenarios import FreshOwnedLab
        lab=FreshOwnedLab();lab.record={'run_id':'unique-run','policy_id':'owned'}
        lab.ev=Mock();lab.write=Mock()
        rule={'id':'rule','max_kbps':6000,'direction':'egress'}
        lab.admin_json=Mock(side_effect=[rule,[{'ID':'rule'}],rule])
        self.assertEqual(lab.create_owned('qos-rule','--max-kbps','6000','owned'),rule)
        self.assertFalse(any('port' in call.args for call in lab.admin_json.call_args_list))
        lab.admin_json=Mock(side_effect=[rule,[{'ID':'rule'}],{**rule,'max_kbps':10000}])
        with self.assertRaisesRegex(RuntimeError,'ownership missing'):
            lab.create_owned('qos-rule','--max-kbps','6000','owned')

    def test_split_judgement_changes_only_arm_safety_and_preserves_failure_contracts(self):
        p=synthetic_profile(profile())
        case={'id':'s2-x01-s','mode':'S','scenario':'s2','purpose':'extension','block':'x01','seed':p['seed']}
        with tempfile.TemporaryDirectory() as root:
            ev=Evidence(root);fake=FakeBackend();fake.execute(case,p,ev)
            atomic_json(Path(root)/'cleanup.json',fake.cleanup(case,p,ev))
            fake.event('phase',41,phase='CLEANUP');fake.event('phase',42,phase='VERIFIED')
            before=_judge(root,case,p);after=judge_split_only(root,case,p)
            self.assertTrue(after['trial_valid']);self.assertTrue(after['safety'])
            self.assertEqual({k:v for k,v in before.items() if k not in ('checks','safety','metrics')},
                             {k:v for k,v in after.items() if k not in ('checks','safety','metrics')})
            self.assertEqual({k:v for k,v in before['metrics'].items() if k!='safe_recovered'},
                             {k:v for k,v in after['metrics'].items() if k!='safe_recovered'})
            events=rows(Path(root)/'events.jsonl')
            (Path(root)/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events if e['kind']!='action_requested'))
            invalid=judge_split_only(root,case,p)
            self.assertFalse(invalid['trial_valid'])
            self.assertIn('action_outside_horizon_or_without_request',invalid['missing'])
            raw=read(Path(root)/'observations/contract.json');raw.update(offered_seconds=1,horizon_seconds=40)
            atomic_json(Path(root)/'observations/contract.json',raw)
            self.assertFalse(judge_split_only(root,case,p)['checks']['uploader_offered_through_H'])

    def test_split_judgement_rejects_non_extension_cases(self):
        with self.assertRaisesRegex(ValueError,'extension S2/S'):
            judge_split_only('/unused',{'scenario':'s2','mode':'P','purpose':'main'},profile())


if __name__=='__main__':
    unittest.main()
