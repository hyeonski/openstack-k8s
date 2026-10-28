"""Forward-only reconciliation of the user's latest displayed credit.

The historical bed ledger remains an audit estimate. It is never subtracted
again from a newer displayed balance with an unknown billing cutoff.
"""
import hashlib
import json
from pathlib import Path
import time
from fresh_evidence import epoch


def forward_credit(profile,seconds=0,now=None):
    policy=profile['operations'].get('stability',{}).get('credit_reference')
    if policy is None:return None
    if seconds<0:raise ValueError('negative forward reservation')
    path=Path(policy['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=policy['sha256']:
        raise RuntimeError('latest credit evidence changed')
    record=json.loads(path.read_text());credit=record['latest_credit']
    if credit['cash_overage_authorized'] is not False or credit['paid_conversion_authorized'] is not False:
        raise RuntimeError('unpaid-only credit policy required')
    balance=credit['total_krw']-credit['used_krw']
    if balance!=credit['displayed_remaining_krw']:raise RuntimeError('credit arithmetic mismatch')
    now=time.time() if now is None else now
    rate=profile['operations']['cost_estimate']['bed_hour_krw']+profile['operations']['cost_estimate']['calendar_day_krw']/24
    elapsed=max(0,now-epoch(record['recorded_utc']))/3600
    cleanup=record['forward_plan']['cleanup_reserve_krw']
    uncertainty=record['forward_plan']['other_uncertainty_reserve_krw']
    if cleanup<40000 or uncertainty<20000:raise RuntimeError('credit reserves weakened')
    future=seconds/3600*rate;since=elapsed*rate
    # A conservative admission assumption, explicitly not a measured billing delay.
    assumed_lag=12;lag=assumed_lag*rate
    base_margin=balance-since-future-cleanup-uncertainty
    return dict(displayed_remaining_krw=balance,reported_utc=record['recorded_utc'],
        billing_cutoff_unknown=True,historical_ledger_subtracted=False,rate_krw_per_hour=rate,
        elapsed_since_report_hours=elapsed,elapsed_since_report_estimate_krw=since,
        future_seconds=seconds,future_estimate_krw=future,cleanup_reserve_krw=cleanup,
        uncertainty_reserve_krw=uncertainty,assumed_unposted_hours=assumed_lag,
        unposted_assumption_confirmed=False,assumed_unposted_krw=lag,
        margin_krw=base_margin-lag,break_even_unposted_hours=base_margin/rate,
        sensitivity=[dict(assumed_hours=h,margin_krw=base_margin-h*rate) for h in (0,6,12)],
        credit_expires_utc=record['previous_credit_for_audit']['expires_utc'],
        cash_overage_authorized=False,paid_conversion_authorized=False)
