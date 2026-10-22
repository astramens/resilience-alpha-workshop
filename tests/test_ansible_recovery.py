"""Policy, real Ansible engine against an isolated HTTP guard fixture, no Docker."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remediation'))
import ansible_runner as runner


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


module = load('scoped_ansible_module', ROOT / 'remediation/ansible/library/rearm_backend_restart.py')
CID = 'a' * 64
LABELS = {'com.docker.compose.project': 'test', 'com.docker.compose.service': 'backend'}


def guard_fixture():
    state = {'inventory': [{'Id': CID, 'Names': ['/test-backend-1'], 'Labels': dict(LABELS)}],
             'details': {'Id': CID, 'Name': '/test-backend-1', 'Config': {'Labels': dict(LABELS)}},
             'posts': [], 'calls': [], 'restart_status': 204}
    def transport(method, path):
        state['calls'].append((method, path))
        if method == 'GET' and path == '/containers/json':
            return 200, state['inventory']
        if method == 'GET' and path == '/containers/' + CID + '/json':
            return 200, state['details']
        if method == 'POST':
            state['posts'].append(path)
            return state['restart_status'], None
        raise AssertionError((method, path))
    return state, transport


def test_check_mode_reads_without_restart():
    state, transport = guard_fixture()
    result = module.execute('test', check=True, transport=transport)
    assert result == {'changed': False, 'scope_verified': True, 'would_restart': True}
    assert not state['posts'] and len(state['calls']) == 2


def test_one_fixed_restart_only():
    state, transport = guard_fixture()
    assert module.execute('test', transport=transport)['changed'] is True
    assert state['posts'] == ['/containers/' + CID + '/restart?t=10']


@pytest.mark.parametrize('case', ['empty', 'ambiguous', 'other_project', 'other_service',
                                 'inspection_scope', 'inspection_id', 'target', 'bad_id'])
def test_reject_before_mutation(case):
    state, transport = guard_fixture()
    if case == 'empty': state['inventory'] = []
    if case == 'ambiguous': state['inventory'] *= 2
    if case == 'other_project': state['inventory'][0]['Labels']['com.docker.compose.project'] = 'other'
    if case == 'other_service': state['inventory'][0]['Labels']['com.docker.compose.service'] = 'db'
    if case == 'inspection_scope': state['details']['Config']['Labels']['com.docker.compose.service'] = 'auth'
    if case == 'inspection_id': state['details']['Id'] = 'b' * 64
    if case == 'bad_id': state['inventory'][0]['Id'] = '../../create'
    with pytest.raises(module.RecoveryError):
        module.execute('test', target='missing' if case == 'target' else '', transport=transport)
    assert not state['posts']


def test_failed_restart_is_not_retried():
    state, transport = guard_fixture(); state['restart_status'] = 503
    with pytest.raises(module.RecoveryError): module.execute('test', transport=transport)
    assert len(state['posts']) == 1


def test_runner_environment_drops_secrets_and_external_configuration(monkeypatch):
    monkeypatch.setenv('COMPOSE_PROJECT', 'test')
    for key in ['REMEDIATION_TOKEN', 'STRIPE_SECRET_KEY', 'HTTP_PROXY', 'PYTHONPATH',
                'ANSIBLE_STDOUT_CALLBACK', 'ANSIBLE_LIBRARY']:
        monkeypatch.setenv(key, 'SECRET_OR_UNTRUSTED')
    env = runner.environment()
    assert 'SECRET_OR_UNTRUSTED' not in json.dumps(env)
    assert 'REMEDIATION_TOKEN' not in env and 'HTTP_PROXY' not in env
    assert '--extra-vars' not in runner.command() and '--check' in runner.command(True)


@pytest.mark.parametrize('output,code', [(b'not-json',0), (b'{}',0),
    (b'{"event":"ansible_result","ok":true,"changed":0,"would_restart":false}',0),
    (b'{"event":"ansible_result","ok":true,"changed":1,"would_restart":false}',2)])
def test_parent_rejects_unconfirmed_process(monkeypatch, output, code):
    p = Mock(returncode=code); p.communicate.return_value = (output, b'PRIVATE')
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: p)
    with pytest.raises(runner.PlaybookError): runner.run_playbook()


def test_parent_kills_process_group_on_timeout(monkeypatch):
    p = Mock(pid=321); p.communicate.side_effect = [subprocess.TimeoutExpired('ansible',25), (b'',b'')]
    kill = Mock(); monkeypatch.setattr(runner.os, 'killpg', kill)
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: p)
    with pytest.raises(runner.PlaybookError): runner.run_playbook()
    kill.assert_called_once_with(321, runner.signal.SIGKILL)


def test_actual_ansible_engine_check_restart_and_rejection(tmp_path, monkeypatch):
    # Only replace the isolated test copy's fixed HTTP destination with loopback.
    # The production module has no user-supplied endpoint or proxy override.
    tree = tmp_path / 'ansible'; shutil.copytree(ROOT/'remediation/ansible', tree)
    source = tree / 'library/rearm_backend_restart.py'
    state, transport = guard_fixture()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self): self.reply('GET')
        def do_POST(self): self.reply('POST')
        def reply(self, method):
            status, data = transport(method, self.path)
            self.send_response(status); self.end_headers()
            if data is not None: self.wfile.write(json.dumps(data).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    source.write_text(source.read_text().replace(module.GUARD, 'http://127.0.0.1:' + str(server.server_port)))
    monkeypatch.setattr(runner, 'ROOT', tree); monkeypatch.setenv('COMPOSE_PROJECT', 'test')
    monkeypatch.setenv('TARGET_CONTAINER', '')
    try:
        checked = runner.run_playbook(check=True)
        assert checked['check_mode'] is True and not state['posts']
        result = runner.run_playbook()
        assert result['executor'] == 'ansible' and result['playbook_success'] is True
        assert state['posts'] == ['/containers/' + CID + '/restart?t=10']
        state['inventory'] = []
        with pytest.raises(runner.PlaybookError): runner.run_playbook()
        assert len(state['posts']) == 1
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_compose_does_not_expand_privileges():
    c = yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    rem = c['services']['remediation']
    assert rem['read_only'] is True and rem['cap_drop'] == ['ALL']
    assert set(rem['networks']) == {'control','docker_control','probe_services'}
    assert not rem.get('ports') and not rem.get('volumes')
    assert not any('STRIPE' in k or 'CAMERA' in k for k in rem['environment'])
    assert 'USER 65532:65532' in (ROOT/'remediation/Dockerfile').read_text()


def test_playbook_failure_stops_before_readiness(monkeypatch):
    os.environ.setdefault('REMEDIATION_TOKEN', 'PRIVATE')
    rem = load('failed_ansible_remediator', ROOT/'remediation/remediator.py')
    monkeypatch.setattr(rem,'TOKEN','PRIVATE'); monkeypatch.setattr(rem,'last_restart',0)
    monkeypatch.setattr(rem,'run_playbook', Mock(side_effect=runner.PlaybookError('PRIVATE')))
    get = Mock(); monkeypatch.setattr(rem.requests,'get',get)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        rem.remediate(rem.Alert(reason='do not execute arbitrary text'), authorization='Bearer PRIVATE')
    assert exc.value.status_code == 503 and not get.called



def test_new_execution_events_are_filtered_without_context_secrets():
    sanitize = load('ansible_sanitize', ROOT/'logging/sanitize.py').sanitize
    raw = {'event':'ansible_repair_completed','playbook_success':True,'check_mode':False,
           'stdout':'PRIVATE','Authorization':'Bearer PRIVATE','executor':'ansible',
           'target':'private-container','reason':'PRIVATE'}
    assert sanitize('remediation',json.dumps(raw)) == {
        'event':'ansible_repair_completed','playbook_success':True,'check_mode':False}
