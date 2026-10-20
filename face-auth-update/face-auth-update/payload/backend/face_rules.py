"""Pure rules shared by the authentication router and its tests."""
import math

FACE_COOLDOWN = 30
PASSWORD_COOLDOWN = 10
BLOCK_SECONDS = 300
SUCCESS_DELAY = 30
FLOW_LIFETIME = 120


def normalise(vector):
    if len(vector) != 128 or not all(math.isfinite(v) for v in vector):
        raise ValueError('Invalid facial features')
    length = math.sqrt(sum(v*v for v in vector))
    if not math.isfinite(length) or length < 1e-9:
        raise ValueError('Empty facial features')
    return [v / length for v in vector]


def face_matches(probes, references, threshold):
    if len(probes) < 3 or not references:
        return False
    refs = [normalise(x) for x in references]
    scores = [max(sum(a*b for a,b in zip(normalise(p),r)) for r in refs) for p in probes]
    return sum(s >= threshold for s in scores) >= 3


def led(data, mode, now, duration):
    data['led'] = {'mode': mode, 'started': now, 'ends': now+duration}


def face_rejected(data, flow, now):
    failures = data.setdefault('failures', {})
    entry = failures.get(flow['username'], {'count': 0, 'blocked_until': 0})
    entry['count'] += 1
    entry['updated_at'] = now
    if entry['count'] >= 2:
        entry['blocked_until'] = now + BLOCK_SECONDS
    failures[flow['username']] = entry
    flow.update(stage='face_rejected', ready_at=now+FACE_COOLDOWN,
                blocked_until=entry['blocked_until'])
    led(data, 'red_fixed', now, FACE_COOLDOWN)


def advance(data, now):
    flow = data.get('flow')
    if flow and now >= flow['expires_at']:
        if flow['stage'] == 'camera' and flow.get('claimed') and flow['kind'] == 'login':
            face_rejected(data, flow, now)
            flow['expires_at'] = now + FACE_COOLDOWN + 30
        else:
            data['flow'] = None
            led(data, 'off', now, 0)
    if data.get('led', {}).get('ends', 0) <= now:
        data['led'] = {'mode':'off', 'started':now, 'ends':now}
    # Bound usernames retained in the kiosk failure map.
    data['failures'] = {k:v for k,v in data.get('failures', {}).items()
                        if v.get('updated_at', now) >= now-3600}


def public_state(flow, now):
    return {'stage': flow['stage'], 'username': flow['username'] if flow['stage'] not in ('face_rejected','password_rejected') else '',
            'wait_seconds': max(0, math.ceil(flow.get('ready_at', now)-now)),
            'blocked_seconds': max(0, math.ceil(flow.get('blocked_until', now)-now)),
            'camera_on': flow['stage']=='camera' or (flow['stage']=='face_rejected' and now < flow.get('ready_at',0))}
