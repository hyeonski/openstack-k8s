"""Timeline decomposition must use raw events and keep the frozen stability metric unchanged."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ('scripts', 'evaluation')]
from graduation_analysis_timeline import analyse, first_stable

T0 = dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc)


def at(seconds):
    return (T0 + dt.timedelta(seconds=seconds)).isoformat()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


class TimelineTests(unittest.TestCase):
    def test_first_stable_counts_later_gap_without_moving_it(self):
        samples = [{'time': at(i), 'ok': i >= 5} for i in range(60)] + [{'time': at(64), 'ok': True}]
        confirmed, interruptions = first_stable(samples, at(0))
        self.assertEqual(confirmed, at(35))
        self.assertEqual(interruptions, 1)

    def test_phases_per_scenario_and_no_action_has_no_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s1 = root / 's1'
            write(s1 / 'run.json', {'stress_observed_at': at(0), 'diagnosis_at': at(138), 'relocation_intent_at': at(163),
                                    'relocated_at': at(175), 'recovery_confirmed_at': at(392),
                                    'stabilization_windows': [{'start': at(210)}]})
            write(s1 / 'decisions.jsonl', json.dumps({'kind': 'diagnosis', 'window': {'start': at(5)}}) + '\n')
            control = root / 'control'
            write(control / 'run.json', {'stress_observed_at': at(0), 'diagnosis_at': at(138), 'relocated_at': at(150)})
            write(control / 'decisions.jsonl', '')
            s3 = root / 's3'
            write(s3 / 'run.json', {'fault_at': at(0), 'node_not_ready_at': at(70), 'fence_requested_at': at(76),
                                    'fenced_at': at(98), 'out_of_service_at': at(106), 'recovered_at': at(147),
                                    'pod_after': {'status': {'startTime': at(120)}}})
            s4 = root / 's4'
            events = {'stop_intent_at': at(0), 'node_unhealthy_at': at(54), 'pod_eviction_at': at(84),
                      'replacement_pod_ready_at': at(85)}
            write(s4 / 'analysis' / 'summary.json', {'events_utc': events, 'service': {
                'first_failure_at': at(10), 'last_failure_at': at(84), 'stable_success_confirmed_at': at(200)}})
            write(s4 / 'http.jsonl', '\n'.join(json.dumps({'time': at(i), 'ok': not 10 <= i <= 84})
                                               for i in range(10, 201)) + '\n')
            cases = [{'id': 's1-automatic-01', 'scenario': 's1', 'mode': 'automatic', 'evidence': str(s1)},
                     {'id': 's1-no-action-01', 'scenario': 's1', 'mode': 'no-action', 'evidence': str(control)},
                     {'id': 's1-no-destination', 'scenario': 's1', 'mode': 'no-destination', 'negative': True,
                      'evidence': str(control)},
                     {'id': 's3-automatic-01', 'scenario': 's3', 'mode': 'automatic', 'evidence': str(s3)},
                     {'id': 's4-normal-01', 'scenario': 's4', 'mode': 'normal', 'evidence': str(s4)}]
            for case in cases:
                case['accepted'] = True
            write(root / 'campaign.json', {'cases': cases})
            result = analyse(root)
        runs = {r['id']: r['phases'] for r in result['runs']}
        self.assertNotIn('s1-no-destination', runs)
        self.assertEqual(runs['s1-automatic-01']['destination_selection'], 25)
        self.assertEqual(runs['s1-automatic-01']['stability_windows'], 182)
        self.assertEqual(runs['s1-no-action-01']['detection'], 138)
        self.assertIsNone(runs['s1-no-action-01']['settle'])
        self.assertEqual(runs['s3-automatic-01']['replacement_scheduled'], 14)
        self.assertEqual(runs['s4-normal-01']['total_failure_to_stable'], 190)
        self.assertEqual(runs['s4-normal-01']['supplementary_failure_to_first_stable'], 105)


if __name__ == '__main__':
    unittest.main()
