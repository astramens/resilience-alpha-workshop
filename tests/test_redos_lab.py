"""Lab controls and REAL process starvation, without touching project services."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import lab_redos as lab


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, 'STATE', tmp_path / 'arm.json')
    monkeypatch.setattr(lab, 'INSTANCE', tmp_path / 'instance.json')
    lab.INSTANCE.write_text(json.dumps({'pid': os.getpid(), 'start': 'f' * 32}))
    return lab.STATE


def test_default_closed_and_no_arbitrary_input(state):
    app = FastAPI(); app.include_router(lab.router)
    client = TestClient(app)
    assert client.get(lab.PATH).status_code == 404
    assert client.get(lab.PATH, params={'q': 'reference-ok'}).json()['single_use'] is True
    assert client.get(lab.PATH, params={'q': 'a' * 36}).status_code == 422


def test_capability_single_use_process_bound_expiring_and_private(state):
    token = 'a' * 64
    lab.arm(token, now=100)
    assert state.stat().st_mode & 0o777 == 0o600
    assert token not in state.read_text()
    assert not lab.consume('Bearer ' + 'b' * 64, lab.PAYLOAD, now=101)
    assert not lab.consume('Bearer ' + token, 'other', now=101)
    assert not lab.consume('Bearer ' + token, lab.PAYLOAD, now=401)
    assert state.exists()
    assert lab.consume('Bearer ' + token, lab.PAYLOAD, now=101)
    assert not state.exists()
    assert not lab.consume('Bearer ' + token, lab.PAYLOAD, now=102)


def test_restart_identity_invalidates_unused_arm(state):
    lab.arm('a' * 64, now=100)
    data = json.loads(state.read_text()); data['process_start'] = 'old-process'
    state.write_text(json.dumps(data))
    assert not lab.consume('Bearer ' + 'a' * 64, lab.PAYLOAD, now=101)


def test_malformed_state_and_symlink_fail_closed(state, tmp_path):
    state.write_text('{')
    assert not lab.consume('Bearer ' + 'a' * 64, lab.PAYLOAD)
    state.unlink(); target = tmp_path / 'target'; target.write_text('PRIVATE')
    state.symlink_to(target)
    assert not lab.consume('Bearer ' + 'a' * 64, lab.PAYLOAD)
    assert target.read_text() == 'PRIVATE'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def server(tmp_path, safety=120):
    port = free_port()
    script = tmp_path / ('server-' + str(port) + '.py')
    script.write_text(f'''
import sys,os
from pathlib import Path
sys.path.insert(0,{str(ROOT / 'backend')!r})
import lab_redos as lab
from fastapi import FastAPI
import uvicorn
lab.STATE=Path({str(tmp_path / 'active.json')!r})
lab.INSTANCE=Path({str(tmp_path / 'instance.json')!r})
lab.INSTANCE.write_text(__import__('json').dumps({{'pid':os.getpid(),'start':'f'*32}}))
lab.DEADLINE={safety}
app=FastAPI();app.include_router(lab.router)
@app.get('/health')
def health():return {{'status':'ok'}}
lab.STATE.unlink(missing_ok=True)
lab.arm('a'*64)
uvicorn.run(app,host='127.0.0.1',port={port},log_level='error')
''')
    process = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = 'http://127.0.0.1:' + str(port)
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError(process.communicate()[0].decode())
        try:
            with urlopen(base + '/health', timeout=0.1): return process, base
        except OSError: time.sleep(0.05)
    process.kill(); process.wait(); raise AssertionError('test server startup failed')


def trigger(base):
    from urllib.parse import urlencode
    request = Request(base + lab.PATH + '?' + urlencode({'q': lab.PAYLOAD}),
                      headers={'Authorization': 'Bearer ' + 'a' * 64})
    try: urlopen(request, timeout=1).close()
    except OSError: pass


def test_real_regex_blocks_health_and_process_replacement_restores_it(tmp_path):
    process, base = server(tmp_path)
    thread = threading.Thread(target=trigger, args=(base,), daemon=True); thread.start()
    time.sleep(0.4)
    try:
        with pytest.raises(OSError): urlopen(base + '/health', timeout=0.3)
        assert process.poll() is None
        assert not (tmp_path / 'active.json').exists()  # consumed before blocking
    finally:
        process.kill(); process.wait(); thread.join(timeout=2)
    output = process.communicate()[0].decode()
    assert 'lab_redos_started' in output
    assert 'lab_safety_timeout' not in output and 'lab_regex_returned' not in output
    # A replacement process is alive. No Ansible claim: that remains a host test.
    other, base2 = server(tmp_path)
    try:
        with urlopen(base2 + '/health', timeout=1) as r: assert r.status == 200
        # Without arming, malicious input is rejected rather than evaluated.
        (tmp_path / 'active.json').unlink()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base2 + lab.PATH + '?q=' + lab.PAYLOAD,
                            headers={'Authorization': 'Bearer ' + 'a' * 64}), timeout=1)
        assert error.value.code == 404
    finally:
        other.kill(); other.wait()


def test_real_watchdog_marks_emergency_and_kills_stuck_test_process(tmp_path):
    process, base = server(tmp_path, safety=2)
    thread = threading.Thread(target=trigger, args=(base,), daemon=True); thread.start()
    try:
        process.wait(timeout=7)
        output = process.communicate()[0].decode()
        assert process.returncode == -9
        assert 'lab_safety_timeout' in output and 'lab_redos_started' in output
    finally:
        if process.poll() is None: process.kill(); process.wait()
        thread.join(timeout=2)


def test_limited_target_and_expired_kit_refused(tmp_path):
    spec = importlib.util.spec_from_file_location('lab_client', ROOT / 'redteam/trigger_redos.py')
    client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
    ca = b'not-a-real-cert'; (tmp_path / 'ca.pem').write_bytes(ca)
    data = {'url': 'https://example.com', 'capability': 'a' * 64, 'expires': time.time() + 300,
            'ca_sha256': hashlib.sha256(ca).hexdigest()}
    (tmp_path / 'run.json').write_text(json.dumps(data))
    with pytest.raises(ValueError): client.configuration(tmp_path)
    data.update(url=client.BASE, expires=0)
    (tmp_path / 'run.json').write_text(json.dumps(data))
    with pytest.raises(ValueError): client.configuration(tmp_path)


def test_backend_is_bounded_without_extra_permissions():
    import yaml
    config = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    backend = config['services']['backend']
    assert backend['cpus'] == 1.0 and backend['mem_limit'] == '256m'
    assert backend['pids_limit'] == 96
    assert 'size=32m' in backend['tmpfs'][0]
    assert not backend.get('ports') and not backend.get('privileged')
    assert not any('docker.sock' in v for v in backend.get('volumes', []))
    assert not any('LAB_' in key for key in backend['environment'])


def test_supervisor_does_not_restart_worker_after_watchdog_exit(tmp_path):
    """Actual entrypoint + actual uvicorn + actual regex; emergency is visible."""
    port = free_port()
    instance = tmp_path / 'supervised-instance.json'
    state = tmp_path / 'supervised-arm.json'
    (tmp_path / 'main.py').write_text(f'''
from pathlib import Path
import lab_redos as lab
from fastapi import FastAPI
lab.INSTANCE=Path({str(instance)!r});lab.STATE=Path({str(state)!r});lab.DEADLINE=2
app=FastAPI();app.include_router(lab.router)
@app.get('/health')
def health():return {{'status':'ok'}}
@app.on_event('startup')
def startup():lab.arm('a'*64)
''')
    # Port is the only variation from the delivered supervisor command.
    original = (ROOT / 'backend/lab_entrypoint.py').read_text()
    script = tmp_path / 'entry.py'
    script.write_text(original.replace("from lab_redos import INSTANCE", f"INSTANCE = Path({str(instance)!r})")
                      .replace("'8000'", repr(str(port))))
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'backend'), PYTHONUNBUFFERED='1')
    process = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path,
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = 'http://127.0.0.1:' + str(port)
    try:
        for _ in range(100):
            if process.poll() is not None: raise AssertionError(process.communicate()[0].decode())
            try:
                with urlopen(base + '/health', timeout=0.1): break
            except OSError: time.sleep(0.05)
        assert instance.exists()
        thread = threading.Thread(target=trigger, args=(base,), daemon=True); thread.start()
        process.wait(timeout=8)
        output = process.communicate()[0].decode()
        assert process.returncode == 137
        assert 'lab_redos_started' in output and 'lab_safety_timeout' in output
        assert not instance.exists()
        thread.join(timeout=2)
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)


def test_host_proof_rejects_emergency_or_natural_completion(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import redos_lab as host
    for bad in ('lab_safety_timeout', 'lab_regex_returned'):
        monkeypatch.setattr(host, 'logs', lambda *args: [{'event': 'lab_redos_started'}, {'event': bad}])
        with pytest.raises(RuntimeError): host.evidence({'since': '2026-01-01T00:00:00Z', 'prior': []})


def test_host_proof_requires_ansible_guard_and_new_ledger(monkeypatch):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import redos_lab as host
    records = {'backend': [{'event': 'lab_redos_started'}],
               'remediation': [{'event': 'ansible_repair_completed', 'playbook_success': True, 'check_mode': False}],
               'docker-guard': [{'event': 'scoped_backend_restart'}]}
    monkeypatch.setattr(host, 'logs', lambda service, since: records[service])
    monkeypatch.setattr(host, 'private_status', lambda: {'ledger': {'incidents': [
        {'ref': 'INC-new', 'state': 'technical_recovered'}]}})
    run = {'since': '2026-01-01T00:00:00Z', 'prior': ['INC-old']}
    assert host.evidence(run)['ref'] == 'INC-new'
    records['remediation'][0]['check_mode'] = True
    assert host.evidence(run) is None
    records['remediation'][0]['check_mode'] = False
    run['prior'].append('INC-new')
    assert host.evidence(run) is None
