"""Pure case-boundary admission decisions for an explicitly scheduled pause."""
def pause_decision(now, pause_start, resume, expected_case_seconds=0, margin_seconds=600):
    if resume <= pause_start or expected_case_seconds < 0 or margin_seconds < 0:
        raise ValueError('invalid pause/admission interval')
    if now >= resume:
        return {'hold':False,'reason':'resume window open','wait_seconds':0}
    if now >= pause_start:
        return {'hold':True,'reason':'scheduled experiment pause','wait_seconds':resume-now}
    if now+expected_case_seconds+margin_seconds >= pause_start:
        return {'hold':True,'reason':'next complete case cannot fit before pause with margin','wait_seconds':resume-now}
    return {'hold':False,'reason':'complete case fits before pause','wait_seconds':0}
