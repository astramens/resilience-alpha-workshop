"""Actual local certificate/NGINX tests; no host trust changes or Docker required."""
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import https_setup as setup
import https_check as checker
import https_rollback as rollback
import secrets_vault as vault
from secret_permissions import SecretError
from test_secrets import isolated, actual_tools


@pytest.fixture
def prepared(actual_tools,monkeypatch):
    root,home,values=actual_tools
    mkcert=ROOT.parent/'tmp/tls-assets/mkcert'
    if not mkcert.exists():pytest.skip('Official mkcert test binary not provisioned')
    monkeypatch.setattr(setup,'ROOT',root);monkeypatch.setattr(setup,'require_port_available',lambda:None);monkeypatch.setattr(checker,'ROOT',root)
    monkeypatch.setattr(rollback,'ROOT',root)
    monkeypatch.setattr(setup,'find_mkcert',lambda:mkcert)
    (root/'.env').write_bytes(values['.env']+b'ALLOWED_ORIGINS=http://localhost:3000,http://192.168.137.1:3000\nPAYMENT_PUBLIC_URL=http://localhost:3000\nCOOKIE_SECURE=false\n')
    (root/'infra').mkdir();shutil.copy2(ROOT/'infra/nginx-https.conf.template',root/'infra/nginx-https.conf.template')
    vault.setup();setup.prepare('192.168.137.1')
    return root,home,values


def test_prepare_actual_certificate_preserves_secrets_and_is_repeatable(prepared):
    root,home,values=prepared;state=setup.load_state();external=setup.tls_home()
    before={n:(external/n).read_bytes() for n in ['ca/rootCA-key.pem','leaf/key.pem','leaf/cert.pem']}
    env=setup.parse_env((root/'.env').read_bytes())
    assert env['COOKIE_SECURE']=='true' and env['PAYMENT_PUBLIC_URL']=='https://localhost'
    assert 'http://localhost:3000' in env['ALLOWED_ORIGINS'] and 'https://192.168.137.1' in env['ALLOWED_ORIGINS']
    assert 'sk_test_FICTITIOUS_ONLY' in env['STRIPE_SECRET_KEY']
    assert not external.is_relative_to(root)
    setup.prepare('192.168.137.1')
    assert all((external/n).read_bytes()==raw for n,raw in before.items())
    assert all((root/n).read_bytes()==v for n,v in values.items() if n!='.env')
    vault.seal();assert vault.check()['.env']==(root/'.env').read_bytes()


def test_rollback_preserves_later_unrelated_secret_changes(prepared):
    root,_,_=prepared
    raw=(root/'.env').read_bytes()+b'OTHER_SECRET=updated-after-tls\n'
    setup.atomic_private(root/'.env',raw)
    rollback.rollback()
    assert not (root/'docker-compose.override.yml').exists()
    env=setup.parse_env((root/'.env').read_bytes())
    assert env['OTHER_SECRET']=='updated-after-tls' and env['COOKIE_SECURE']=='false'
    assert env['PAYMENT_PUBLIC_URL']=='http://localhost:3000' and 'REARM_TLS_CERT_DIR' not in env
    assert (setup.tls_home()/'ca/rootCA-key.pem').exists()
    assert (setup.tls_home()/'state-rolled-back.json').exists()


def test_refuses_to_overwrite_existing_compose_override(actual_tools,monkeypatch):
    root,_,_=actual_tools;monkeypatch.setattr(setup,'ROOT',root);monkeypatch.setattr(setup,'require_port_available',lambda:None)
    path=root/'docker-compose.override.yml';path.write_bytes(b'EXISTING_CUSTOM_CONFIG')
    old=(root/'.env').read_bytes()
    with pytest.raises(SecretError,match='existe deja'):setup.prepare('192.168.137.1')
    assert path.read_bytes()==b'EXISTING_CUSTOM_CONFIG' and (root/'.env').read_bytes()==old


def test_malformed_ip_refused_before_writes(actual_tools,monkeypatch):
    root,_,_=actual_tools;monkeypatch.setattr(setup,'ROOT',root);old=(root/'.env').read_bytes()
    for value in ['8.8.8.8','127.0.0.1','0.0.0.0','192.168.137.1; dangerous']:
        with pytest.raises((ValueError,SecretError)):setup.prepare(value)
    assert (root/'.env').read_bytes()==old and not (root/'docker-compose.override.yml').exists()


def test_managed_changes_refuse_automatic_rollback(prepared):
    root,_,_=prepared
    setup.atomic_private(root/'.env',(root/'.env').read_bytes().replace(b"COOKIE_SECURE='true'",b"COOKIE_SECURE='false'"))
    before=(root/'.env').read_bytes()
    with pytest.raises(SecretError):rollback.rollback()
    assert (root/'.env').read_bytes()==before and (root/'docker-compose.override.yml').exists()


def test_env_rewrite_preserves_literal_values_and_bom():
    raw=b"\xef\xbb\xbfSECRET='a # $ \\ b'\r\nCOOKIE_SECURE=false\r\n"
    changed=setup.update_env(raw,{'COOKIE_SECURE':'true'})
    assert changed.startswith(b"\xef\xbb\xbfSECRET='a # $ \\ b'\r\n")
    assert setup.parse_env(changed)['COOKIE_SECURE']=='true'
    with pytest.raises(SecretError):setup.update_env(raw,{'COOKIE_SECURE':"unsafe'\nKEY=x"})


def test_actual_nginx_tls_redirect_cookie_flags_and_http_exceptions(prepared,tmp_path):
    binary=ROOT.parent/'tmp/tls-assets/nginx-1.28.0/objs/nginx'
    if not binary.exists():pytest.skip('NGINX test binary not provisioned')
    # Fake upstream has NO business operations; it only echoes paths and cookies.
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):self.reply()
        def do_POST(self):self.reply()
        def reply(self):
            calls.append((self.command,self.path))
            self.send_response(200);self.send_header('X-Rearm-Inspection','active')
            if self.path=='/set-session':self.send_header('Set-Cookie','rc_session=fixture; Path=/')
            self.end_headers();self.wfile.write(b'[{"id":1}]')
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
    def port():
        with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
    http,tls=port(),port();prefix=tmp_path/'nginx';prefix.mkdir()
    log=prefix/'error.log';pid=prefix/'nginx.pid'
    proxy=(ROOT/'infra/proxy.conf').read_text()
    (prefix/'proxy.conf').write_text(proxy)
    text=(setup.tls_home()/'leaf/edge.conf').read_text()
    text=text.replace('listen 8080;',f'listen {http};').replace('listen 8443 ssl;',f'listen {tls} ssl;')
    text=text.replace('http://waf:8080','http://127.0.0.1:'+str(upstream.server_port))
    text=text.replace('/etc/nginx/rearm-proxy.conf',str(prefix/'proxy.conf'))
    text=text.replace('/etc/nginx/tls/',str(setup.tls_home()/'leaf')+'/')
    main=f'user root;\npid {pid};\nerror_log {log};\nevents {{ worker_connections 64; }}\nhttp {{\n{text}\n}}\n'
    conf=prefix/'nginx.conf';conf.write_text(main)
    (prefix/'logs').mkdir()
    valid=subprocess.run([str(binary),'-p',str(prefix),'-c',str(conf),'-t'],capture_output=True,text=True)
    assert valid.returncode==0,valid.stderr
    process=subprocess.Popen([str(binary),'-p',str(prefix),'-c',str(conf),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        end=time.monotonic()+5
        while time.monotonic()<end:
            try:
                with socket.create_connection(('127.0.0.1',tls),timeout=.2):break
            except OSError:time.sleep(.05)
        ca=setup.tls_home()/'ca/rootCA.pem'
        ctx=ssl.create_default_context(cafile=ca)
        plain=build_opener(ProxyHandler({}),checker.NoRedirect())
        secure=build_opener(ProxyHandler({}),HTTPSHandler(context=ctx),checker.NoRedirect())
        checker.check(base='https://localhost:'+str(tls),http='http://localhost:'+str(http),verify_runtime=False)
        for path,method in [('/api/device/led','GET'),('/api/face-agent/next','GET'),
                            ('/api/face-agent/result/job','POST'),('/api/shop/payments/webhook','POST')]:
            req=Request('http://localhost:'+str(http)+path,data=b'{}' if method=='POST' else None,method=method)
            with plain.open(req) as r:assert r.status==200
        for path in ['/api/customer/login','/api/auth/login','/api/shop/orders']:
            req=Request('http://localhost:'+str(http)+path,data=b'{}')
            with pytest.raises(HTTPError) as exc:plain.open(req)
            assert exc.value.code==308 and ('POST',path) not in calls
        with pytest.raises(HTTPError) as exc:
            plain.open(Request('http://localhost:'+str(http)+'/',headers={'Host':'attacker.invalid:3000'}))
        assert exc.value.headers['Location']=='https://localhost/'
        with secure.open('https://localhost:'+str(tls)+'/set-session') as r:
            cookie=r.headers['Set-Cookie'].lower()
            assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        # TLS 1.2 and 1.3 actually negotiate. The TLS config admits neither 1.0 nor 1.1.
        for version in [ssl.TLSVersion.TLSv1_2,ssl.TLSVersion.TLSv1_3]:
            context=ssl.create_default_context(cafile=ca);context.minimum_version=context.maximum_version=version
            with socket.create_connection(('127.0.0.1',tls),timeout=3) as raw:
                with context.wrap_socket(raw,server_hostname='localhost') as stream:
                    assert stream.version() in ('TLSv1.2','TLSv1.3')
        for version in [ssl.TLSVersion.TLSv1,ssl.TLSVersion.TLSv1_1]:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
            context.minimum_version=context.maximum_version=version;context.set_ciphers('ALL:@SECLEVEL=0')
            with socket.create_connection(('127.0.0.1',tls),timeout=3) as raw:
                with pytest.raises(ssl.SSLError):context.wrap_socket(raw,server_hostname='localhost')
        # An unrelated CA must not validate the live server.
        with pytest.raises(Exception):
            build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context())).open('https://localhost:'+str(tls))
    finally:
        process.terminate();process.wait(timeout=5);upstream.shutdown();upstream.server_close();thread.join()


def test_busy_port_refused_without_stopping_anything():
    with socket.socket() as listener:
        listener.bind(('0.0.0.0',0));listener.listen()
        with pytest.raises(SecretError,match='deja utilise'):setup.require_port_available(listener.getsockname()[1])


def test_overlay_only_adds_edge_tls_without_mounting_ca_or_expanding_privilege():
    import yaml
    data=yaml.safe_load(setup.overlay())
    assert set(data['services'])=={'edge'}
    edge=data['services']['edge']
    assert edge['ports']==['443:8443']
    assert 'networks' not in edge and 'user' not in edge and 'privileged' not in edge
    assert all(v['read_only'] is True and v['bind']['create_host_path'] is False for v in edge['volumes'])
    assert {v['target'] for v in edge['volumes']}=={'/etc/nginx/tls','/etc/nginx/conf.d/default.conf'}
    assert all('rootCA' not in v['source'] and 'ca/' not in v['source'] for v in edge['volumes'])
