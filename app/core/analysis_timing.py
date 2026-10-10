"""실제 호출 시간과 캐시 적중을 단계별로 집계한다."""


def summarize_timings(trace):
    phases = {}
    for record in trace:
        phase = phases.setdefault(record.get('phase', 'unknown'),
                                  {'seconds': 0.0, 'llm_calls': 0, 'cache_hits': 0})
        phase['seconds'] += record.get('elapsed_seconds', 0)
        if record.get('kind') == 'embedding':
            phase.setdefault('embedding_calls', 0)
            phase['cache_hits' if record.get('cache_hit') else 'embedding_calls'] += 1
        else:
            phase['cache_hits' if record.get('cache_hit') else 'llm_calls'] += 1
    for phase in phases.values():
        phase['seconds'] = round(phase['seconds'], 3)
    return {'llm_calls': sum(p['llm_calls'] for p in phases.values()),
            'embedding_calls': sum(p.get('embedding_calls', 0) for p in phases.values()),
            'cache_hits': sum(p['cache_hits'] for p in phases.values()), 'phases': phases}
