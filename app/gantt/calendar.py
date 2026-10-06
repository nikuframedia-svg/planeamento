"""Working-minute axis; only confirmed resource windows enter the schedule."""
from __future__ import annotations

from .contracts import minute


def windows(snapshot, resource_id):
    origin = snapshot['started_at']
    horizon = snapshot['horizon_minutes']
    result = []
    for row in snapshot['resources'][resource_id]['windows']:
        start = max(0, minute(row['start'], origin))
        end = min(horizon, minute(row['end'], origin))
        if end > start:
            result.append((start, end))
    result.sort()
    if any(left[1] > right[0] for left, right in zip(result, result[1:])):
        raise ValueError('Há janelas sobrepostas no recurso.')
    return result


def consume(available, start, duration, occupied=()):
    """One uninterrupted operation, pausing only at calendar boundaries."""
    if duration <= 0:
        return None
    first = start
    remaining = duration
    used = []
    for low, high in available:
        if high <= first:
            continue
        begin = max(low, first)
        if not used and begin != first:
            return None  # a fixed start in closed time is invalid
        stop = min(high, begin + remaining)
        if stop <= begin:
            continue
        if any(begin < other_end and other_start < stop for other_start, other_end in occupied):
            return None
        used.append((begin, stop))
        remaining -= stop - begin
        if not remaining:
            return {'start': first, 'end': stop, 'segments': used}
    return None


def first_fit(available, earliest, duration, occupied=(), fixed=None):
    if fixed is not None:
        return consume(available, fixed, duration, occupied) if fixed >= earliest else None
    candidates = {max(earliest, start) for start, end in available if end > earliest}
    candidates.update(max(earliest, end) for _, end in occupied)
    for start in sorted(candidates):
        if any(low <= start < high for low, high in available):
            found = consume(available, start, duration, occupied)
            if found:
                return found
    return None


def working_offset(available, instant, *, end=False):
    """Map a wall instant to the compact useful-minute coordinate."""
    counted = 0
    for low, high in available:
        if (low < instant <= high) if end else (low <= instant < high):
            return counted + instant - low
        counted += high - low
    return None


def option_windows(snapshot, option):
    result = windows(snapshot, option['resource_id'])
    for pool in option.get('shared_demands', {}):
        if pool not in snapshot['resources']:
            return []
        available = windows(snapshot, pool)
        result = [(max(a, c), min(b, d)) for a, b in result for c, d in available
                  if max(a, c) < min(b, d)]
    return sorted(result)


def shared_conflicts(snapshot, option, segments, occupied):
    """Sweep actual wall-clock segments, not machine-specific working offsets."""
    for pool, demand in option.get('shared_demands', {}).items():
        capacity = snapshot['resources'][pool].get('capacity', 1)
        events = []
        for left, right in segments:
            events.extend([(left, demand), (right, -demand)])
        for left, right, amount in occupied.get(pool, []):
            events.extend([(left, amount), (right, -amount)])
        used = 0
        for _, delta in sorted(events, key=lambda x: (x[0], x[1])):
            used += delta
            if used > capacity:
                return True
    return False


def option_fit(snapshot, option, earliest, occupied, shared, fixed=None):
    available = option_windows(snapshot, option)
    candidates = {max(earliest, start) for start, end in available if end > earliest}
    candidates.update(max(earliest, end) for _, end in occupied)
    for pool in option.get('shared_demands', {}):
        candidates.update(max(earliest, end) for _, end, _ in shared.get(pool, []))
    for start in ([fixed] if fixed is not None else sorted(candidates)):
        if start is None or start < earliest:
            continue
        found = consume(available, start, option['duration_minutes'], occupied)
        if found and not shared_conflicts(snapshot, option, found['segments'], shared):
            if option.get('latest_minute') is None or found['end'] <= option['latest_minute']:
                return found
    return None
