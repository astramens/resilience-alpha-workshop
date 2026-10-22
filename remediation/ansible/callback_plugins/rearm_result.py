"""One bounded JSON result, no task arguments, raw exceptions or environment."""
import json
from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'rearm_result'

    def __init__(self):
        super().__init__()
        self.verified = False
        self.would_restart = False

    def v2_runner_on_ok(self, result):
        data = result._result
        self.verified = data.get('scope_verified') is True
        self.would_restart = data.get('would_restart') is True

    def v2_playbook_on_stats(self, stats):
        rows = [stats.summarize(host) for host in stats.processed]
        ok = (len(rows) == 1 and self.verified
              and rows[0]['ok'] == 1 and rows[0]['failures'] == 0
              and rows[0]['unreachable'] == 0 and rows[0]['skipped'] == 0)
        self._display.display(json.dumps({'event': 'ansible_result', 'ok': ok,
                                         'changed': sum(r['changed'] for r in rows),
                                         'would_restart': self.would_restart}))

