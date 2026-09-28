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
