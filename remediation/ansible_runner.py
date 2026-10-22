"""Fixed Ansible entry point. No request data, tokens or shell interpolation."""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'ansible'


class PlaybookError(Exception):
    pass


def command(check=False):
    executable = Path(sys.executable).parent / 'ansible-playbook'
    return [str(executable), '-i', str(ROOT / 'inventory.yml'),
            str(ROOT / 'recover_backend.yml')] + (['--check'] if check else [])


def environment():
    # Deliberately discard all incoming ANSIBLE_*, PYTHONPATH, proxy and secret vars.
    return {'PATH': str(Path(sys.executable).parent) + ':/usr/local/bin:/usr/bin:/bin',
            'HOME': '/tmp/rearm-ansible', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'ANSIBLE_CONFIG': str(ROOT / 'ansible.cfg'), 'ANSIBLE_NOCOLOR': '1',
            'ANSIBLE_LOCAL_TEMP': '/tmp/rearm-ansible/controller',
            'ANSIBLE_REMOTE_TEMP': '/tmp/rearm-ansible/target',
            'COMPOSE_PROJECT': os.environ['COMPOSE_PROJECT'],
            'TARGET_CONTAINER': os.getenv('TARGET_CONTAINER', ''),
            'PYTHONDONTWRITEBYTECODE': '1'}


def run_playbook(check=False):
    try:
        process = subprocess.Popen(command(check), cwd=ROOT, env=environment(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise PlaybookError('Ansible unavailable') from None
    try:
        stdout, _ = process.communicate(timeout=25)
    except subprocess.TimeoutExpired:
        # Stop Ansible AND its local module child; never launch a second attempt.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise PlaybookError('Ansible deadline exceeded; action outcome uncertain') from None
    try:
        if process.returncode != 0 or len(stdout) > 8192:
            raise ValueError()
        result = json.loads(stdout)
        if (result.get('event') != 'ansible_result' or result.get('ok') is not True
                or type(result.get('changed')) is not int
                or result['changed'] != (0 if check else 1)
                or result.get('would_restart') is not check):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise PlaybookError('Playbook failed or result unconfirmed') from None
    return {'executor': 'ansible', 'check_mode': check, 'playbook_success': True}


if __name__ == '__main__':
    # Interactive diagnostics can only use check mode. Mutation is through /alerts.
    if sys.argv[1:] != ['--check']:
        raise SystemExit('Usage: python ansible_runner.py --check')
    try:
        print(json.dumps(run_playbook(check=True)))
    except PlaybookError:
        raise SystemExit('ECHEC : controle Ansible indisponible ou cible non unique.')
