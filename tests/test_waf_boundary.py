"""Static boundary policies. Runtime CRS acceptance is checked by waf_check.py on the host."""
import re
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def load():return yaml.safe_load((ROOT/'docker-compose.yml').read_text())

def test_public_requests_have_no_direct_frontend_path():
    services=load()['services']
    assert set(services['edge']['networks']).isdisjoint(services['frontend']['networks'])
    assert set(services['waf']['networks']) & set(services['edge']['networks'])
    assert set(services['waf']['networks']) & set(services['frontend']['networks'])
    assert not services['waf'].get('ports')
    assert all(not v.get('ports') for name,v in services.items() if name not in ('edge','grafana'))
    upstreams=re.findall(r'proxy_pass\s+([^;]+);',(ROOT/'infra/nginx.conf').read_text())
    assert upstreams and all(u=='http://waf:8080' for u in upstreams)

def test_waf_cannot_access_database_or_repair_control():
    services=load()['services']
    for target in ['db','backend','auth','remediation','docker-guard','ai-engine']:
        assert set(services['waf']['networks']).isdisjoint(services[target]['networks'])
    assert not any('docker.sock' in v for v in services['waf'].get('volumes',[]))
    assert not any('TOKEN' in k or 'SECRET' in k or 'PASSWORD' in k for k in services['waf']['environment'])
    assert all(load()['networks'][n]['internal'] for n in services['waf']['networks'])

def test_preserves_stripe_and_auth_headers_and_size_budget():
    edge=(ROOT/'infra/proxy.conf').read_text();waf=(ROOT/'infra/waf/default.conf.template').read_text()
    assert 'proxy_set_header Host $http_host;' in edge and 'proxy_set_header Host $http_host;' in waf
    assert 'proxy_set_header X-Rearm-Client-IP $remote_addr;' in edge
    assert 'proxy_set_header X-Rearm-Client-IP $http_x_rearm_client_ip;' in waf
    assert 'proxy_set_header X-Rearm-Request-ID $request_id;' in edge
    # No request-body rewrite, header allowlist, cookie rewriting or signature rewriting.
    assert not re.search(r'proxy_set_body|proxy_pass_request_headers\s+off|proxy_cookie_|proxy_set_header\s+(?:Cookie|Authorization|Stripe-Signature|Origin)',waf,re.I)
    env=load()['services']['waf']['environment']
    assert int(env['MODSEC_REQ_BODY_NOFILES_LIMIT'])>=65536
    assert env['MODSEC_RULE_ENGINE']=='On' and env['MODSEC_RESP_BODY_ACCESS']=='Off'

def test_no_password_biometric_or_card_data_in_waf_audit_parts():
    env=load()['services']['waf']['environment']
    assert set(env['MODSEC_AUDIT_LOG_PARTS'])<=set('AZ')
    assert env['MODSEC_AUDIT_LOG_FORMAT']=='Native'
    template=(ROOT/'infra/waf/nginx.conf.template').read_text()
    assert 'error_log /dev/stderr crit;' in template
    assert not any(v in template for v in ['$request_body','$http_authorization','$http_cookie','$args','$request_uri'])
    assert 'escape=json' in template and '"upstream_status"' in template

def test_pinned_unprivileged_bounded_image():
    service=load()['services']['waf']
    assert re.search(r'@sha256:[0-9a-f]{64}$',service['image'])
    assert service['cap_drop']==['ALL']
    assert service['security_opt']==['no-new-privileges:true']
    assert service['mem_limit']=='512m' and service['pids_limit']==128
    assert all(v.endswith(':ro') for v in service['volumes'])
    assert service['logging']['options']['max-size']=='5m'
