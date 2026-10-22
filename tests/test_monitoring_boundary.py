"""Security and setup regression checks; no Docker daemon required."""
from pathlib import Path
import json,re,runpy,shutil
from unittest.mock import patch
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]

def test_supervision_has_no_public_exporter_or_socket():
    c=yaml.safe_load((ROOT/'docker-compose.yml').read_text());services=c['services']
    assert services['grafana']['ports']==['127.0.0.1:3001:3000']
    for name in ['prometheus','blackbox']:
        assert not services[name].get('ports')
    for name in ['prometheus','blackbox','grafana']:
        s=services[name]
        assert re.search(r'@sha256:[0-9a-f]{64}$',s['image'])
        assert s['cap_drop']==['ALL'] and s['read_only'] is True
        assert all('docker.sock' not in v for v in s.get('volumes',[]))
        assert all(c['networks'][n].get('internal', False) for n in s['networks'] if n != 'grafana_access')
        if 'grafana_access' in s['networks']: assert name == 'grafana'
        assert not any(k.startswith(('STRIPE_','CAMERA_','LED_','REMEDIATION_','POSTGRES_')) for k in s.get('environment',{}))
    assert set(services['edge']['networks']).isdisjoint(services['frontend']['networks'])
    assert set(services['waf']['networks']).isdisjoint(services['backend']['networks'])
    assert set(services['grafana']['networks']).isdisjoint(services['db']['networks'])

def test_grafana_has_no_anonymous_or_default_password():
    env=yaml.safe_load((ROOT/'docker-compose.yml').read_text())['services']['grafana']['environment']
    assert env['GF_AUTH_ANONYMOUS_ENABLED']=='false' and env['GF_USERS_ALLOW_SIGN_UP']=='false'
    assert env['GF_PLUGINS_PREINSTALL_DISABLED']=='true' and env['GF_PLUGINS_PLUGIN_ADMIN_ENABLED']=='false'
    assert ':?' in env['GF_SECURITY_ADMIN_PASSWORD'] and ':?' in env['GF_SECURITY_SECRET_KEY']
    ds=yaml.safe_load((ROOT/'infra/monitoring/grafana/provisioning/datasources/prometheus.yml').read_text())['datasources'][0]
    assert ds['editable'] is False and ds['url']=='http://prometheus:9090'

def test_dashboard_has_queries_and_does_not_invent_data():
    d=json.loads((ROOT/'infra/monitoring/grafana/dashboards/rearm.json').read_text())
    assert d['uid']=='rearm-availability'
    targets=[target for p in d['panels'] for target in p.get('targets',[])]
    assert targets and all(t['expr'] and t['datasource']['uid']=='rearm-prometheus' for t in targets)
    stats=[p for p in d['panels'] if p['id'] in (2,3,4,5)]
    assert all(p['fieldConfig']['defaults']['noValue']=='Aucune mesure' for p in stats)
    assert all('up{' in p['targets'][0]['expr'] for p in stats)
    assert not any('testdata' in json.dumps(p) or 'randomWalk' in json.dumps(p) for p in d['panels'])

def setup_copy(tmp_path):
    p=tmp_path/'scripts/monitoring_setup.py';p.parent.mkdir();shutil.copy2(ROOT/'scripts/monitoring_setup.py',p)
    text='STRIPE_SECRET_KEY=private-fixture\nCAMERA_AGENT_TOKEN=private-camera\nPOSTGRES_PASSWORD=private-db\n'
    (tmp_path/'.env').write_text(text)
    return p,text

def test_setup_preserves_existing_secrets_and_never_prints_password(tmp_path,capsys):
    p,original=setup_copy(tmp_path);password='Secret # $ \\ de test 2026!'
    with patch('getpass.getpass',side_effect=[password,password]):runpy.run_path(str(p),run_name='__main__')
    value=(tmp_path/'.env').read_text()
    assert value.startswith(original)
    assert "REARM_GRAFANA_PASSWORD='"+password+"'" in value
    assert 'REARM_GRAFANA_SECRET_KEY=' in value
    assert password not in capsys.readouterr().out
    before=(tmp_path/'.env').read_bytes()
    with patch('getpass.getpass',side_effect=AssertionError('Should not prompt again')),pytest.raises(SystemExit) as exc:runpy.run_path(str(p),run_name='__main__')
    assert exc.value.code==0 and (tmp_path/'.env').read_bytes()==before

@pytest.mark.parametrize('password',['short',"apostrophe'interdite12"])
def test_invalid_setup_does_not_touch_secrets(tmp_path,password):
    p,original=setup_copy(tmp_path)
    with patch('getpass.getpass',return_value=password),pytest.raises(SystemExit):runpy.run_path(str(p),run_name='__main__')
    assert (tmp_path/'.env').read_text()==original

def test_probes_do_not_execute_payment_or_repair():
    cfg=yaml.safe_load((ROOT/'infra/monitoring/blackbox.yml').read_text())
    assert all(m['http']['method']=='GET' for m in cfg['modules'].values())
    assert all(m['http']['follow_redirects'] is False for m in cfg['modules'].values())
    assert cfg['modules']['http_catalogue']['http']['fail_if_header_not_matches'][0]['header']=='X-Rearm-Inspection'
    jobs=yaml.safe_load((ROOT/'infra/monitoring/prometheus.yml').read_text())['scrape_configs']
    urls=[target for j in jobs for c in j.get('static_configs',[]) for target in c['targets']]
    assert not any('/alerts' in x or 'stripe.com' in x or '/orders' in x for x in urls)
