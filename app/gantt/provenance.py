"""Annotate estimated future work with its own and inherited assumptions."""
from __future__ import annotations


def apply(jobs, bars):
    resolved = {}

    def reasons(key, visited=frozenset()):
        if key in resolved:
            return resolved[key]
        if key in visited or key not in bars:
            return []
        job, bar = jobs[key], bars[key]
        option = next((candidate for candidate in job['options']
                       if candidate['resource_id'] == bar['resource_id']
                       and (candidate.get('option_id') == bar.get('option_id')
                            if bar.get('option_id') else
                            candidate['duration_minutes'] == bar['duration_minutes'])), None)
        own = []
        if job.get('balance_provisional'):
            own.append(f'Saldo provisório da operação {key}')
        if option and option.get('provisional'):
            own.append(f'Duração provisória da operação {key}')
        predecessor = job.get('predecessor_key')
        inherited = reasons(predecessor, visited | {key}) if predecessor in bars else []
        resolved[key] = sorted(set(own + inherited))
        return resolved[key]

    for key, bar in bars.items():
        bar['provisional_reasons'] = reasons(key)
        bar['provisional'] = bool(bar['provisional_reasons'])
