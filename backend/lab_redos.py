"""OPT-IN LAB ONLY: single-use, bounded demonstration of CWE-1333.

The pathological regex is deliberately introduced for the workshop, never a
claim that this weakness existed in REARM. No SQL, payment or arbitrary regex.
Only a local Docker operator can arm it; restart closes the lab automatically.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from fastapi import APIRouter, Header, HTTPException, Query

STATE = Path('/tmp/rearm-redos-arm.json')
INSTANCE = Path('/tmp/rearm-api-instance.json')
PATH = '/api/shop/lab/reference'
PATTERN = r'^(a+)+$'
PAYLOAD = 'a' * 34 + '!'
DEADLINE = 120
router = APIRouter()


def event(name):
    print(json.dumps({'event': name, 'lab_only': True}), flush=True)


def arm(token, now=None):
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ValueError('Invalid lab capability')
    if STATE.exists():
        raise ValueError('Disarm the previous lab first')
    instance = json.loads(INSTANCE.read_text())
    pid = instance['pid']
    if type(pid) is not int or pid <= 1 or not re.fullmatch('[a-f0-9]{32}', instance['start']):
        raise ValueError('API instance unavailable')
    os.kill(pid, 0)
    now = time.monotonic() if now is None else now
    raw = json.dumps({'hash': hashlib.sha256(token.encode()).hexdigest(),
                      'expires': now + 3600, 'process_start': instance['start']})
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(raw)
    event('lab_redos_armed')


def consume(authorization, text, now=None):
    now = time.monotonic() if now is None else now
    try:
        if STATE.is_symlink() or STATE.stat().st_size > 1024:
            return False
        data = json.loads(STATE.read_text())
        instance = json.loads(INSTANCE.read_text())
        if (data['expires'] < now or instance['pid'] != os.getpid()
                or data['process_start'] != instance['start']
                or not authorization.startswith('Bearer ')):
            return False
        token = authorization[7:]
        if not re.fullmatch(r'[a-f0-9]{64}', token):
            return False
        if not secrets.compare_digest(data['hash'], hashlib.sha256(token.encode()).hexdigest()):
            return False
        # Exactly one fixed pathological string is permitted, never larger inputs.
        if text != PAYLOAD:
            return False
        STATE.unlink()  # before entering the blocking call; no replay after restart
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def watchdog(pid, seconds):
    """Independent emergency stop. This is NOT an autonomous-recovery proof."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        # The API is a child of the tiny PID 1 supervisor, never PID 1 itself.
        # After API death this child is reparented, so it cannot kill a reused PID.
        if os.getppid() != pid:
            return
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    try:
        if os.getppid() == pid:
            event('lab_safety_timeout')
            os.kill(pid, 9)
    except ProcessLookupError:
        pass


@router.get(PATH)
async def reference(q: str = Query(default='', max_length=35),
                    authorization: str = Header(default='')):
    if q == 'reference-ok':
        # Harmless preflight, even when the vulnerable path is not armed.
        return {'lab': 'redos_reference_v1', 'default': 'closed',
                'single_use': True, 'safety_seconds': DEADLINE}
    if not consume(authorization, q):
        raise HTTPException(404, 'Laboratory closed or capability invalid')
    pid = os.getpid()
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                              '--watchdog', str(pid), str(DEADLINE)],
                             stdin=subprocess.DEVNULL, close_fds=True,
                             env={k: os.environ[k] for k in ('PATH', 'LANG', 'PYTHONUNBUFFERED',
                                                            'PYTHONDONTWRITEBYTECODE') if k in os.environ})
    event('lab_redos_started')
    try:
        # Deliberately synchronous on the event loop: the actual regex causes
        # CPU starvation, including /health and catalogue. There is NO sleep,
        # fake health status, Docker call or call to remediation in this path.
        matched = re.fullmatch(PATTERN, q) is not None
        event('lab_regex_returned')
        return {'matched': matched, 'lab': True}
    finally:
        child.terminate()
        child.wait(timeout=3)


if __name__ == '__main__' and len(sys.argv) == 4 and sys.argv[1] == '--watchdog':
    watchdog(int(sys.argv[2]), int(sys.argv[3]))
