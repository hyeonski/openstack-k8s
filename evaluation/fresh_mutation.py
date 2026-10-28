"""Execute a named mutation once, then prove its state after a lost response."""
from fresh_read_budget import transient_error


def mutation_once(ev,operation,invoke,readback,applied):
    ev.event('mutation_intent',operation=operation,mutation_repeated=False)
    try:
        result=invoke()
    except Exception as error:
        ev.event('mutation_response_error',operation=operation,detail=type(error).__name__+': '+str(error),mutation_repeated=False)
        if not transient_error(error):raise
        observed=readback()
        confirmed=bool(applied(observed))
        ev.event('mutation_state_readback',operation=operation,applied=confirmed,mutation_repeated=False)
        if not confirmed:raise
        return observed
    observed=readback()
    confirmed=bool(applied(observed))
    ev.event('mutation_state_readback',operation=operation,applied=confirmed,mutation_repeated=False)
    if not confirmed:raise RuntimeError('mutation readback mismatch: '+operation)
    return result
