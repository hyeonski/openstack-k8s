"""Classify operational pauses without changing a trial's scientific verdict."""

MEASUREMENT_ERRORS = frozenset({
    'request_time_reversed', 'request_monotonic_invalid',
    'wall_monotonic_duration_disagreement', 'clock_step_between_requests',
    'arrival_schedule_mismatch', 'request_arrivals_incomplete',
    'early_observation_end',
})


def next_action(result, *, cleanup_verified, budget_available):
    """A clean measurement failure can wait for repair; never replay its fault."""
    if not cleanup_verified or result.get('cleanup') is not True:
        return 'resolve_owned_cleanup'
    if not budget_available or result.get('safety') is not True:
        return 'safe_shutdown'
    if result.get('trial_valid') is True:
        return 'record_result'
    errors = set(result.get('missing') or [])
    if errors and errors.issubset(MEASUREMENT_ERRORS):
        return 'pause_for_measurement_repair'
    return 'investigate_before_next_case'
