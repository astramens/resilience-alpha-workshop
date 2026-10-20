import copy
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'payload/backend' if (ROOT/'payload/backend').exists() else ROOT/'backend'
sys.path.insert(0,str(BACKEND))
os.environ['CAMERA_AGENT_TOKEN']='camera-test-token-'+'c'*40
os.environ['LED_DEVICE_TOKEN']='led-test-token-'+'d'*40
from face_auth import make_router
from face_rules import advance, face_matches, face_rejected, normalise
from security import hash_password, token_hash


def feature(i=0):
    v=[0.0]*128;v[i]=1.0;return v


class Database:
    def __init__(self):
        self.now=1000
        self.state={'agent_seen':1000}
        self.users={1:{'id':1,'username':'operateur','role':'admin','enabled':True,'face_features':[feature()]*3,'password_hash':hash_password('correct-password')}}
        self.sessions=set()
        self.attempts=[]
    def connection(self): return Connection(self)


class Connection:
    def __init__(self,db): self.db=db
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self,**kwargs): return Cursor(self.db)
    def commit(self): pass


class Cursor:
    def __init__(self,db): self.db=db;self.result=None
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params=None):
        d=self.db
        if sql.startswith('SELECT data,'): self.result={'data':copy.deepcopy(d.state),'now':d.now}
        elif sql.startswith('UPDATE face_auth_state'): d.state=copy.deepcopy(params[0].adapted)
        elif sql.startswith('SELECT id FROM operators WHERE username='):
            self.result=next(({'id':u['id']} for u in d.users.values() if u['username']==params[0] and u['enabled']),None)
        elif sql.startswith('SELECT * FROM operators WHERE id=') or sql.startswith('SELECT username,role,enabled,face_features'):
            self.result=d.users.get(params[0])
        elif sql.startswith('SELECT * FROM operators WHERE username='):
            self.result=next((u for u in d.users.values() if u['username']==params[0]),None)
        elif sql.startswith('SELECT COUNT(*) AS n FROM login_attempts'):
            self.result={'n':d.attempts.count(params[0])}
        elif sql.startswith('SELECT COUNT(*) AS n FROM operators'):
            self.result={'n':sum(bool(u['face_features'] and u['enabled'] and u['role']=='admin') for u in d.users.values())}
        elif sql.startswith('INSERT INTO login_attempts'): d.attempts.append(params[0])
        elif sql.startswith('DELETE FROM login_attempts WHERE bucket='): d.attempts=[x for x in d.attempts if x!=params[0]]
        elif sql.startswith('DELETE FROM login_attempts WHERE created_at'): pass
        elif sql.startswith('DELETE FROM sessions WHERE expires_at'): pass
        elif sql.startswith('INSERT INTO sessions'): d.sessions.add(params[0])
        elif sql.startswith('UPDATE operators SET face_features='): d.users[params[1]]['face_features']=params[0].adapted
        elif sql.startswith("UPDATE operators SET role='admin'"): d.users[params[0]]['role']='admin'
        elif sql.startswith('DELETE FROM sessions WHERE operator_id='): d.sessions.clear()
        elif sql.startswith('SELECT id,username FROM operators WHERE id='):
            self.result=d.users.get(params[0])
        else: raise AssertionError('Unhandled SQL in test double: '+sql)
    def fetchone(self): return copy.deepcopy(self.result)


@pytest.fixture
def appdb():
    d=Database();app=FastAPI()
    def current_user(): return d.users[1]
    app.include_router(make_router(d.connection,current_user,False))
    return TestClient(app),d


AGENT={'Authorization':'Bearer '+os.environ['CAMERA_AGENT_TOKEN']}
LED={'Authorization':'Bearer '+os.environ['LED_DEVICE_TOKEN']}


def begin(c,d):
    assert c.post('/api/auth/identify',json={'username':'operateur'}).status_code==200
    return d.state['flow']['id']


def result(c,job,features):
    return c.post('/api/face-agent/result/'+job,json={'features':features},headers=AGENT)


def test_matching_requires_three_frames_and_correct_identity():
    assert face_matches([feature()]*3,[feature()]*3,.45)
    assert not face_matches([feature(1)]*3,[feature()]*3,.45)
    assert not face_matches([feature()]*2,[feature()]*3,.45)
    with pytest.raises(ValueError): normalise([float('nan')]*128)


def test_password_alone_and_finish_before_recognition_rejected(appdb):
    c,d=appdb
    assert c.post('/api/auth/login',json={'username':'operateur','password':'correct-password'}).status_code==401
    begin(c,d)
    assert c.post('/api/auth/login',json={'password':'correct-password'}).status_code==409
    assert c.post('/api/auth/finish',json={}).status_code==409
    assert not d.sessions


def test_untrusted_browser_cannot_submit_face(appdb):
    c,d=appdb;job=begin(c,d)
    assert c.post('/api/face-agent/result/'+job,json={'features':[feature()]*3}).status_code==401
    assert c.post('/api/face-agent/result/'+job,json={'features':[feature()]*3},headers=LED).status_code==401
    assert not d.sessions


def test_camera_is_serialised_and_proof_bound_to_cookie(appdb):
    c,d=appdb;job=begin(c,d)
    other=TestClient(c.app)
    assert other.get('/api/auth/face-status').status_code==401
    assert other.post('/api/auth/identify',json={'username':'operateur'}).status_code==409
    assert begin(c,d)==job


def test_success_delay_single_use_and_replay_rejection(appdb):
    c,d=appdb;job=begin(c,d)
    assert result(c,job,[feature()]*3).json()['stage']=='face_ok'
    assert result(c,job,[feature()]*3).status_code==409
    assert c.post('/api/auth/login',json={'password':'correct-password'}).json()['stage']=='success_wait'
    assert c.post('/api/auth/finish',json={}).status_code==409
    d.now+=30
    r=c.post('/api/auth/finish',json={})
    assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie']
    assert len(d.sessions)==1
    assert c.post('/api/auth/finish',json={}).status_code==401


def test_wrong_password_consumes_face_proof(appdb):
    c,d=appdb;job=begin(c,d);result(c,job,[feature()]*3)
    assert c.post('/api/auth/login',json={'password':'wrong'}).json()['stage']=='password_rejected'
    assert c.post('/api/auth/login',json={'password':'correct-password'}).status_code==409
    assert d.state['led']['mode']=='red_blink_10'
    assert not d.sessions


def test_two_face_failures_block_even_without_browser_cookie(appdb):
    c,d=appdb
    for i in range(2):
        d.state['agent_seen']=d.now
        job=begin(c,d)
        r=result(c,job,[feature(1)]*3)
        assert r.json()['stage']=='face_rejected'
        assert d.state['led']['mode']=='red_fixed'
        d.now+=31
    other=TestClient(c.app)
    assert other.post('/api/auth/identify',json={'username':'operateur'}).status_code==429
    d.now+=301;d.state['agent_seen']=d.now
    assert other.post('/api/auth/identify',json={'username':'operateur'}).status_code==200


def test_camera_error_does_not_count_as_wrong_face(appdb):
    c,d=appdb;job=begin(c,d)
    r=c.post('/api/face-agent/result/'+job,json={'error':'camera_unavailable'},headers=AGENT)
    assert r.json()['stage']=='camera_error'
    assert not d.state.get('failures')


def test_face_revocation_between_password_and_finish_blocks_session(appdb):
    c,d=appdb;job=begin(c,d);result(c,job,[feature()]*3)
    c.post('/api/auth/login',json={'password':'correct-password'})
    d.users[1]['face_features']=None;d.now+=30
    assert c.post('/api/auth/finish',json={}).status_code==403
    assert not d.sessions


def test_own_role_cannot_be_changed_and_viewer_not_admin(appdb):
    c,d=appdb
    assert c.post('/api/admin/users/1/access',json={'role':'viewer','enabled':False}).status_code==409
    d.users[1]['role']='viewer'
    assert c.post('/api/admin/users/2/access',json={'role':'admin','enabled':True}).status_code==403


def test_bootstrap_closed_when_admin_enrolled(appdb):
    c,d=appdb
    assert c.post('/api/face-agent/bootstrap',json={'username':'operateur','password':'correct-password'},headers=AGENT).status_code==403


def test_led_endpoint_needs_separate_device_secret(appdb):
    c,d=appdb
    assert c.get('/api/device/led').status_code==401
    assert c.get('/api/device/led',headers=AGENT).status_code==401
    assert c.get('/api/device/led',headers=LED).json()['mode']=='off'


def test_missing_camera_does_not_allow_password_fallback(appdb):
    c,d=appdb;d.now+=20
    assert c.post('/api/auth/identify',json={'username':'operateur'}).status_code==503
    assert c.post('/api/auth/login',json={'password':'correct-password'}).status_code==401
