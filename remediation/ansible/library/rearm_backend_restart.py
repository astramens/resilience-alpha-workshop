#!/usr/bin/python
"""Project-local Ansible module. Only list, inspect and one guarded restart.

No shell, SSH, Docker socket, external collection, payment or arbitrary URL.
The existing docker-guard independently checks scope again before mutation.
"""
import json
import re
from urllib.request import Request, build_opener, ProxyHandler
from ansible.module_utils.basic import AnsibleModule

GUARD = 'http://docker-guard:2375'
MAX_BYTES = 1024 * 1024


class RecoveryError(Exception):
    pass


def exchange(method, path):
    # Never inherit host proxy settings or follow redirects to another endpoint.
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(GUARD + path, method=method,
                             data=b'' if method == 'POST' else None), timeout=15) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise RecoveryError('Guard response too large')
        return response.status, json.loads(raw) if raw else None


def execute(project, target='', check=False, transport=exchange):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise RecoveryError('Invalid configured project')
    if target and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', target):
        raise RecoveryError('Invalid configured target')
    status, candidates = transport('GET', '/containers/json')
    if status != 200 or not isinstance(candidates, list):
        raise RecoveryError('Invalid guard inventory')
    # Fail closed even if a compromised/misconfigured proxy returns another scope.
    for item in candidates:
        labels = item.get('Labels') or {}
        if (labels.get('com.docker.compose.project') != project
                or labels.get('com.docker.compose.service') != 'backend'):
            raise RecoveryError('Inventory outside configured scope')
    if target:
        candidates = [c for c in candidates if '/' + target in c.get('Names', [])]
    if len(candidates) != 1:
        raise RecoveryError('Expected exactly one backend')
    cid = candidates[0].get('Id', '')
    if not isinstance(cid, str) or not re.fullmatch(r'[a-f0-9]{64}', cid):
        raise RecoveryError('Invalid container identifier')
    status, details = transport('GET', '/containers/' + cid + '/json')
    if status != 200 or not isinstance(details, dict) or details.get('Id') != cid:
        raise RecoveryError('Invalid target inspection')
    labels = details.get('Config', {}).get('Labels') or {}
    if (labels.get('com.docker.compose.project') != project
            or labels.get('com.docker.compose.service') != 'backend'
            or (target and details.get('Name') != '/' + target)):
        raise RecoveryError('Inspected target outside configured scope')
    if check:
        return {'changed': False, 'scope_verified': True, 'would_restart': True}
    status, _ = transport('POST', '/containers/' + cid + '/restart?t=10')
    if status != 204:
        raise RecoveryError('Restart not acknowledged')
    return {'changed': True, 'scope_verified': True, 'would_restart': False}


def main():
    module = AnsibleModule(argument_spec={'project': {'type': 'str', 'required': True},
                                         'target': {'type': 'str', 'default': ''}},
                           supports_check_mode=True)
    try:
        result = execute(module.params['project'], module.params['target'], module.check_mode)
    except Exception:
        # No raw response/exception, inventory, environment or secret in telemetry.
        module.fail_json(msg='Scoped backend action failed; inspect the guard and configuration.', changed=False)
    module.exit_json(**result)


if __name__ == '__main__':
    main()

