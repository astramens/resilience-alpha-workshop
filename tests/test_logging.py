import importlib.util,json,sys,struct,hashlib
from pathlib import Path
from unittest.mock import patch
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'logging'))
import sanitize as clean
import gateway,collector

def test_sensitive_fields_never_retained():
    text=json.dumps({'event':'payment_confirmed','actor':'PRIVATE_CUSTOMER','target':'99','password':'sk_test_PRIVATE','face_features':[1,2],'cookie':'PRIVATE_COOKIE'})
    assert clean.sanitize('backend',text)=={'event':'payment_confirmed'}
@pytest.mark.parametrize('message',['password=SECRET','Traceback SECRET','{"event":"unknown","token":"SECRET"}','{"password":"SECRET"}'])
def test_unknown_logs_dropped(message):assert clean.sanitize('auth',message) is None

def test_http_path_cannot_leak_query_or_username():
    value=clean.sanitize('auth','INFO: "POST /api/auth/login?password=SECRET HTTP/1.1" 401 Unauthorized')
    assert value=={'event':'access_denied','method':'POST','route':'/api/auth/login','status':401}
    assert clean.route('/api/shop/customers/SECRET')=='/api/other'
    assert clean.route('/secret-username')=='/other'

def test_waf_block_differs_from_application_denial():
    event={'event':'waf_http','method':'GET','path':'/?token=SECRET','status':403,'upstream_status':'-'}
    assert clean.sanitize('waf',json.dumps(event))['event']=='waf_block'
    event['upstream_status']='403'
    assert clean.sanitize('waf',json.dumps(event))['event']=='access_denied'

def test_no_raw_invalid_or_nonfinite_fields():
    assert clean.sanitize('db','"GET / HTTP/1.1" 200 OK') is None
    value=clean.sanitize('ai-engine','{"event":"observation","error_rate":NaN,"healthy":true,"reason":"SECRET"}')
    assert value=={'event':'observation','healthy':True}
    assert clean.sanitize('backend','x'*16385) is None

def test_docker_frame_boundaries_and_timestamp():
    chunks=[b'2026-10-21T12:00:00.123456789Z ',b'hello\n']
    frames=b''.join(b'\1\0\0\0'+struct.pack('>I',len(x))+x for x in chunks)
    assert b''.join(gateway.frames(frames))==b''.join(chunks)
    assert gateway.timestamp_ns('2026-10-21T12:00:00.123456789Z').endswith('123456789')
    with pytest.raises(ValueError):list(gateway.frames(b'not docker'))

def test_gateway_fixed_scope_and_read_only_paths():
    calls=[];cid='a'*64
    def read(path):
        calls.append(path)
        if path.startswith('/containers/json?'):
            return json.dumps([{'Id':cid,'Labels':{'com.docker.compose.project':'TEST','com.docker.compose.service':'backend'}},
              {'Id':'b'*64,'Labels':{'com.docker.compose.project':'OTHER','com.docker.compose.service':'backend'}},
              {'Id':'c'*64,'Labels':{'com.docker.compose.project':'TEST','com.docker.compose.service':'db'}}]).encode()
        log=b'2026-10-21T12:00:00.123456789Z {"event":"payment_confirmed","actor":"SECRET"}\n'
        return b'\1\0\0\0'+struct.pack('>I',len(log))+log
    with patch.object(gateway,'PROJECT','TEST'),patch.object(gateway,'docker_get',read):data=gateway.snapshot()
    assert len(calls)==2 and calls[1].startswith('/containers/'+cid+'/logs?')
    assert 'follow=0' in calls[1] and 'tail=1000' in calls[1]
    assert data['observed']==['backend'] and 'SECRET' not in json.dumps(data)
    assert len(data['events'])==1

def test_collector_acknowledgement_dedup_and_order():
    event={'id':'one','service':'backend','timestamp':'100','data':{'event':'payment_confirmed'}}
    snapshot={'events':[event],'observed':['backend'],'failed':[],'missing':['auth']}
    batch,ids=collector.batch(snapshot,set(),True)
    assert ids==['one'] and len(batch['streams'])==2
    batch,ids=collector.batch(snapshot,{'one'},False)
    assert not ids and not batch['streams']

def test_network_and_socket_boundary():
    conf=yaml.safe_load((ROOT/'docker-compose.yml').read_text());s=conf['services']
    assert s['grafana']['ports']==['127.0.0.1:3001:3000']
    assert set(s['grafana']['networks'])=={'observability','grafana_access','log_store'}
    for name in ('loki','log-gateway','log-collector'):assert 'ports' not in s[name]
    assert set(s['log-gateway']['networks'])=={'log_source'}
    assert set(s['log-collector']['networks'])=={'log_source','log_store'}
    assert set(s['loki']['networks'])=={'log_store'}
    assert conf['networks']['log_source']['internal'] is True
    assert conf['networks']['log_store']['internal'] is True
    assert not any('docker.sock' in x for x in s['log-collector'].get('volumes',[]))
    assert set(s['log-gateway']['environment'])=={'COMPOSE_PROJECT'}
    assert 'DOCKER_HOST' not in s['log-collector'].get('environment',{})

def test_no_existing_hardware_auth_payment_changes():
    # The patch manifest is checked separately against the uploaded baseline.
    config=yaml.safe_load((ROOT/'infra/logging/loki.yml').read_text())
    assert config['auth_enabled'] is False
    assert config['limits_config']['retention_period']=='72h'
    assert config['compactor']['retention_enabled'] is True
    for p in (ROOT/'logging').glob('*.py'):compile(p.read_text(),str(p),'exec')

def test_loki_failure_never_advances_checkpoint(tmp_path,monkeypatch):
    snapshot={'events':[{'id':'one','service':'backend','timestamp':'100','data':{'event':'payment_confirmed'}}],
              'observed':['backend'],'missing':['auth'],'failed':[]}
    class EndLoop(BaseException):pass
    state=tmp_path/'checkpoint.json';monkeypatch.setattr(collector,'STATE',state)
    def request(url,data=None):
        if data is None:return snapshot
        raise OSError('Loki unavailable')
    monkeypatch.setattr(collector,'request',request)
    monkeypatch.setattr(collector.time,'sleep',lambda _:(_ for _ in ()).throw(EndLoop()))
    with pytest.raises(EndLoop):collector.main()
    assert not state.exists()

def test_loki_acknowledgement_persists_ids(tmp_path,monkeypatch):
    snapshot={'events':[{'id':'one','service':'backend','timestamp':'100','data':{'event':'payment_confirmed'}}],
              'observed':['backend'],'missing':[],'failed':[]}
    class EndLoop(BaseException):pass
    state=tmp_path/'checkpoint.json';monkeypatch.setattr(collector,'STATE',state)
    monkeypatch.setattr(collector,'request',lambda url,data=None:snapshot if data is None else None)
    monkeypatch.setattr(collector.time,'sleep',lambda _:(_ for _ in ()).throw(EndLoop()))
    with pytest.raises(EndLoop):collector.main()
    assert json.loads(state.read_text())==['one']


def test_waf_legacy_line_is_not_counted_a_second_time():
    raw='172.26.0.3 - - [21/Oct/2026:11:47:48 +0000] "GET /api/shop/products?private=SECRET HTTP/1.1" 403 146'
    assert clean.sanitize('waf',raw) is None
    assert clean.sanitize('auth',raw)['event']=='access_denied'
