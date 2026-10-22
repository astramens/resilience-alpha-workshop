"""PID 1 supervision only; no repair loop. Docker/Ansible keep their roles.

The API must not be PID 1: Linux protects a namespace init from SIGKILL sent
inside that namespace. A safety child can kill this non-init API at its deadline.
"""
import json
import os
from pathlib import Path
import signal
import secrets
import subprocess
import sys


def main():
    worker = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app',
                               '--host', '0.0.0.0', '--port', '8000',
                               '--no-proxy-headers'], start_new_session=True)
    def forward(signum, frame):
        try: os.killpg(worker.pid, signum)
        except ProcessLookupError: pass
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    from lab_redos import INSTANCE
    try:
        fd = os.open(INSTANCE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(json.dumps({'pid': worker.pid, 'start': secrets.token_hex(16)}))
        code = worker.wait()
    finally:
        if worker.poll() is None:
            forward(signal.SIGTERM, None)
            try: worker.wait(timeout=3)
            except subprocess.TimeoutExpired: worker.kill(); worker.wait()
        INSTANCE.unlink(missing_ok=True)
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    raise SystemExit(main())
