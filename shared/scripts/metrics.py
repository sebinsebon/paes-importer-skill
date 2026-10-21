"""Measured provider usage accounting. Missing measurements remain unknown."""
import math
FIELDS = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cost', 'duration_seconds')

def aggregate_usage(events):
    identifiers = set()
    currencies = set()
    known = {key: 0 for key in FIELDS}
    measured = {key: 0 for key in FIELDS}
    for event in events:
        event_id = event.get('event_id')
        if not isinstance(event_id, str) or not event_id.strip() or event_id in identifiers:
            raise ValueError('Each measured call needs a unique event_id; do not repeat coordinator/worker totals')
        identifiers.add(event_id)
        if event.get('aggregate', False):
            raise ValueError('Supply individual provider calls, not overlapping aggregates')
        for key in FIELDS:
            value = event.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid measured usage: ' + key)
            if key.endswith('_tokens') and not isinstance(value, int):
                raise ValueError('Measured tokens must be integers')
            if key == 'cost':
                currency = event.get('currency')
                if not isinstance(currency, str) or not currency.strip():
                    raise ValueError('Measured cost requires its currency')
                currencies.add(currency.upper())
                if len(currencies) > 1:
                    raise ValueError('Cannot aggregate different cost currencies')
            known[key] += value
            measured[key] += 1
    return {'calls': len(events), 'provider_receipts_count': len(events), 'total_provider_calls': None,
        'currency': next(iter(currencies)) if currencies else None,
        **{key: known[key] if events and measured[key] == len(events) else None for key in FIELDS},
        'known_subtotals': known, 'measured_calls': measured,
        'accounting': 'individual_provider_calls_only', 'estimated_from_characters': False}

def measured_savings(baseline, candidate):
    result = {}
    for key in FIELDS:
        before, after = baseline.get(key), candidate.get(key)
        result[key] = None if (key == 'cost' and (not baseline.get('currency') or baseline.get('currency') != candidate.get('currency'))) or before is None or after is None or before <= 0 else (before - after) / before
    return result


def summarize_timeline(events, *, requested_at=None, finished_at=None):
    """Disjoint wall-time attribution from observed intervals, never call-duration sums.

    Overlapping categories remain unattributed. Retry counts and announced backoff
    are observations, not additional time intervals. Legacy events remain readable.
    """
    from datetime import datetime
    def instant(value):
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timeline timestamps require timezone offsets')
        return parsed.timestamp()
    categories = ('importer', 'auxiliary', 'provider', 'backoff', 'pause')
    intervals = []
    totals = {}
    retries = 0
    announced = 0
    operations = set()
    for row in events:
        if row.get('phase') == 'start':
            continue
        operation = row.get('operation_id')
        if operation:
            if operation in operations:
                raise ValueError('Duplicate completed operation_id')
            operations.add(operation)
        category = row.get('category', 'importer' if row.get('stage', '').startswith('command_') else None)
        start, end = instant(row.get('started_at')), instant(row.get('finished_at'))
        if start is not None and end is not None:
            if end < start:
                raise ValueError('Timeline interval ends before it starts')
            if category in categories:
                intervals.append((start, end, category))
        duration = row.get('duration_seconds')
        if duration is not None:
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                raise ValueError('Invalid operation duration')
            stage = row.get('stage', category or 'unknown')
            totals[stage] = totals.get(stage, 0) + duration
        count = row.get('retry_count', 1 if row.get('event') == 'provider_retry' else 0)
        delay = row.get('announced_backoff_seconds', 0)
        if type(count) is not int or count < 0 or isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
            raise ValueError('Invalid retry/backoff observation')
        retries += count
        announced += delay
    start, end = instant(requested_at), instant(finished_at)
    if start is not None and end is not None and end < start:
        raise ValueError('Finish precedes request')
    wall = end-start if start is not None and end is not None else None
    attribution = {key: None for key in categories}
    unassigned = None
    if wall is not None:
        attribution = {key: 0.0 for key in categories}
        edges = sorted({start, end, *[max(start, min(end, p)) for a, b, _ in intervals for p in (a,b)]})
        for a, b in zip(edges, edges[1:]):
            active = {key for left, right, key in intervals if left <= a and right >= b}
            if len(active) == 1:
                attribution[next(iter(active))] += b-a
        unassigned = max(0.0, wall-sum(attribution.values()))
    return {'wall_seconds': wall, 'requested_at': requested_at, 'finished_at': finished_at,
            'attributed_seconds': attribution, 'unattributed_seconds': unassigned,
            'command_duration_sums': totals, 'retry_count': retries,
            'announced_backoff_seconds': announced,
            'intervals_observed': len(intervals), 'events_observed': len(events),
            'policy': 'Overlaps and unobserved gaps remain unattributed; durations are not wall time.'}
