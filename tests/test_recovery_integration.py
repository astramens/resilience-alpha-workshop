"""Isolated PostgreSQL tests only. Never use the workshop database for these tests."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('DATABASE_URL','postgresql://unused');os.environ.setdefault('OPERATOR_PASSWORD','test-only-password-long');os.environ.setdefault('ALLOWED_ORIGINS','http://localhost:3000')
import main,common,recovery
pytestmark=pytest.mark.skipif(not os.getenv('REARM_EMBEDDED_TEST'),reason='Requires isolated embedded PostgreSQL test harness')
TOKEN='test-recovery-'+'t'*48
HEADERS={'Authorization':'Bearer '+TOKEN}

@pytest.fixture(scope='module',autouse=True)
def schema():
 sys.path.insert(0,str(ROOT.parent/'tmp'));import rearm_bridge,psycopg2
 original=psycopg2.connect;psycopg2.connect=lambda *a,**kw:rearm_bridge.Connection()
 for name in ['init.sql','face-auth.sql','shop.sql','payments.sql','recovery.sql']:rearm_bridge.query((ROOT/'db'/name).read_text(),script=True)
 yield
 psycopg2.connect=original

@pytest.fixture(autouse=True)
def reset(monkeypatch):
 monkeypatch.setenv('REMEDIATION_TOKEN',TOKEN);monkeypatch.setenv('PAYMENT_MODE','stripe_test')
 with main.connection() as conn,conn.cursor() as cur:
  cur.execute('TRUNCATE rearm_recovery_incidents,shop_audit,shop_order_items,shop_order_payments,shop_orders,shop_customers,shop_products RESTART IDENTITY CASCADE')
  cur.execute("UPDATE rearm_recovery_probe SET marker='initial' WHERE id=1")
  cur.execute("INSERT INTO shop_products(sku,name,category,description,grade,price_cents,stock,image,workshop_note) VALUES ('TEST-PROBE','Prop','pistolets','A fictional inert cinema prop.','A',100,5,'prop-1.svg','Test')")

def sql(query,args=()):
 with main.connection() as conn,conn.cursor() as cur:cur.execute(query,args);return cur.fetchall()
def client():return TestClient(main.app)
def report(status='remediation'):
 return {'ref':'INC-0123456789ab','status':status,'reason':'ml_anomaly_with_confirmed_health_failure','action':'redemarrage_api_boutique','opened_at':datetime.now(timezone.utc).isoformat(),'detail':{'password':'DO_NOT_PERSIST'},'result':{'technical_recovery_verified':True}}
def register():
 c=client();r=c.post('/internal/incidents',headers=HEADERS,json=report('attente_metier'));assert r.status_code==200,r.text
 return c

def create_paid(before=False,mode='paid',session='cs_test_Example'):
 cid=sql("INSERT INTO shop_customers(username,display_name,password_hash) VALUES (%s,'Test','testhash') RETURNING id",('probe-'+uuid4().hex,))[0][0]
 oid=sql("""INSERT INTO shop_orders(customer_id,request_id,fingerprint,recipient,total_cents,status,created_at)
  VALUES (%s,%s,'digest','Test',100,'confirmed',NOW()+INTERVAL '1 second') RETURNING id""",(cid,str(uuid4())))[0][0]
 sql("INSERT INTO shop_order_payments(order_id,attempt,expires_at,state,session_id,payment_intent,updated_at) VALUES (%s,%s,9999999999,%s,%s,'pi_test',NOW()+INTERVAL '1 second') RETURNING order_id",(oid,str(uuid4()),mode,session))
 if before:sql("UPDATE shop_orders SET created_at=NOW()-INTERVAL '1 hour' WHERE id=%s RETURNING id",(oid,))
 return oid

def test_internal_routes_require_token_even_with_trusted_origin():
 c=client()
 for path in ['/internal/business-probe','/internal/recovery-status']:
  assert c.get(path).status_code==401
 for path in ['/internal/incidents','/internal/recovery/reconcile']:
  assert c.post(path,headers={'Origin':'http://localhost:3000'},json={}).status_code==401
 assert c.post('/internal/recovery/reconcile',headers=HEADERS).status_code==200
 assert c.post('/api/shop/orders',headers=HEADERS,json={}).status_code==403

def test_probe_rolls_back_without_touching_business_or_proving_payment():
 before=sql('SELECT stock,version FROM shop_products')
 r=client().get('/internal/business-probe',headers=HEADERS)
 assert r.status_code==200,r.text
 assert r.json()['transactional_readiness_verified'] is True and r.json()['business_recovery_verified'] is False
 assert sql('SELECT marker FROM rearm_recovery_probe')==[('initial',)]
 assert sql('SELECT stock,version FROM shop_products')==before
 assert sql('SELECT COUNT(*) FROM shop_orders')[0][0]==0

def test_register_is_idempotent_and_does_not_store_arbitrary_details():
 c=client()
 for _ in range(2):assert c.post('/internal/incidents',headers=HEADERS,json=report()).status_code==200
 assert sql('SELECT COUNT(*) FROM rearm_recovery_incidents')[0][0]==1
 r=c.get('/internal/recovery-status',headers=HEADERS);assert 'DO_NOT_PERSIST' not in r.text
 assert r.json()['incidents'][0]['state']=='remediation'

def test_client_cannot_self_assert_business_resolution():
 c=client();body=report();body['status']='resolu'
 assert c.post('/internal/incidents',headers=HEADERS,json=body).status_code==422
 body=report();body['business_verified']=True
 assert c.post('/internal/incidents',headers=HEADERS,json=body).status_code==422

def test_probe_does_not_close_technical_incident():
 c=register();c.get('/internal/business-probe',headers=HEADERS)
 assert c.post('/internal/recovery/reconcile',headers=HEADERS).json()['incidents'][0]['state']=='technical_recovered'

@pytest.mark.parametrize('before,mode,session',[(True,'paid','cs_test_old'),(False,'pending','cs_test_pending'),(False,'refunded','cs_test_refunded'),(False,'paid','cs_live_notallowed')])
def test_old_unpaid_refunded_or_live_order_not_accepted(before,mode,session):
 c=register();create_paid(before,mode,session)
 value=c.post('/internal/recovery/reconcile',headers=HEADERS).json()['incidents'][0]
 assert value['state']=='technical_recovered' and value['business_recovery_verified'] is False

def test_new_paid_test_order_is_server_derived_and_idempotent():
 c=register();oid=create_paid()
 for _ in range(2):
  r=c.post('/internal/recovery/reconcile',headers=HEADERS);assert r.status_code==200,r.text
  value=r.json()['incidents'][0];assert value['state']=='business_verified' and value['proof_order_id']==oid
  assert value['business_recovery_verified'] is True
 # A late failure/replay cannot erase the stored proof.
 assert c.post('/internal/incidents',headers=HEADERS,json=report('echec')).json()['state']=='business_verified'
 assert sql('SELECT COUNT(*) FROM rearm_recovery_incidents')[0][0]==1

def test_demo_mode_is_not_accepted_as_payment_proof(monkeypatch):
 c=register();create_paid();monkeypatch.setenv('PAYMENT_MODE','demo')
 assert c.post('/internal/recovery/reconcile',headers=HEADERS).json()['incidents'][0]['state']=='technical_recovered'

def test_empty_catalogue_does_not_pass_readiness():
 sql('DELETE FROM shop_products RETURNING id')
 assert client().get('/internal/business-probe',headers=HEADERS).status_code==503

def test_metrics_report_states_without_sensitive_labels():
 register();r=client().get('/metrics');assert r.status_code==200,r.text
 assert 'rearm_recovery_incidents{state="technical_recovered"} 1' in r.text
 assert 'DO_NOT_PERSIST' not in r.text and 'INC-012' not in r.text and TOKEN not in r.text

from test_shop_integration import stripe_gateway

def test_actual_shop_checkout_settlement_then_recovery_proof(stripe_gateway):
 import auth_app
 from test_shop_integration import paid
 c=register();auth=TestClient(auth_app.app)
 origin={'Origin':'http://localhost:3000'}
 result=auth.post('/api/customer/register',headers=origin,json={'username':'recovery-client','display_name':'Studio test','password':'recovery-client-password-123'})
 assert result.status_code==201,result.text
 api=client();api.cookies.update(auth.cookies)
 body={'request_id':str(uuid4()),'recipient':'Plateau de preuve','items':[{'product_id':1,'quantity':1}],'accept_demo':True}
 created=api.post('/api/shop/orders',headers=origin,json=body)
 assert created.status_code==201,created.text
 oid=created.json()['id']
 assert c.post('/internal/recovery/reconcile',headers=HEADERS).json()['incidents'][0]['state']=='technical_recovered'
 paid(stripe_gateway)
 settled=api.post(f'/api/shop/orders/{oid}/verify-payment',headers=origin,json={})
 assert settled.status_code==200 and settled.json()['payment_status']=='paid',settled.text
 status=c.post('/internal/recovery/reconcile',headers=HEADERS).json()['incidents'][0]
 assert status['state']=='business_verified' and status['proof_order_id']==oid
 assert sql('SELECT stock FROM shop_products')[0][0]==4
 # A migration replay must not reset stock, the probe marker or the recovery proof.
 import rearm_bridge
 rearm_bridge.query((ROOT/'db/recovery.sql').read_text(),script=True)
 assert sql('SELECT stock FROM shop_products')[0][0]==4
 assert c.get('/internal/recovery-status',headers=HEADERS).json()['incidents'][0]['proof_order_id']==oid

def test_detector_restart_readiness_payment_and_server_confirmation(monkeypatch,stripe_gateway,tmp_path):
 """Full Python contract with simulated outage/container start and Stripe provider only."""
 import importlib.util,requests,auth_app,sys
 sys.path.insert(0,str(ROOT/'remediation'))
 from types import SimpleNamespace
 from test_shop_integration import paid
 def load(name,path):
  spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 det=load('contract_detector','ai-engine/detector.py');rem=load('contract_remediator','remediation/remediator.py')
 c=client();online={'value':False};restarts=[]
 class R:
  def __init__(self,data=None,status=200):self.data=data or {};self.status_code=status;self.ok=status<400
  def json(self):return self.data
  def raise_for_status(self):
   if not self.ok:raise requests.HTTPError('contract failure')
 def wrap(response):return R(response.json(),response.status_code)
 class Session:
  def get(self,url,**kw):
   if not online['value']:raise requests.ConnectionError()
   path='/'+url.split('/',3)[3];return wrap(c.get(path,headers=kw.get('headers',{})))
  def post(self,url,**kw):
   if url.endswith('/alerts'):
    data=rem.remediate(rem.Alert(**kw['json']),authorization=kw['headers']['Authorization']);return R(data)
   if not online['value']:raise requests.ConnectionError()
   path='/'+url.split('/',3)[3];return wrap(c.post(path,headers=kw.get('headers',{}),json=kw.get('json')))
 session=Session()
 def restart():
  online['value']=True;restarts.append('ansible')
  return {'executor':'ansible','check_mode':False,'playbook_success':True}
 monkeypatch.setattr(rem,'TOKEN',TOKEN);monkeypatch.setattr(rem,'last_restart',0)
 monkeypatch.setattr(rem,'run_playbook',restart)
 monkeypatch.setattr(rem.requests,'get',session.get)
 detector=det.Detector(tmp_path/'pending.json');detector.ready=True;detector.model=SimpleNamespace(predict=lambda _:[-1])
 records=[];monkeypatch.setattr(det,'log',lambda event,**fields:records.append((event,fields)))
 for _ in range(3):det.poll(detector,session,TOKEN)
 assert restarts==['ansible'] and online['value'] is True
 ledger=c.get('/internal/recovery-status',headers=HEADERS).json()['incidents'];assert len(ledger)==1
 assert ledger[0]['state']=='technical_recovered' and ledger[0]['business_recovery_verified'] is False
 assert not any(event=='recovery_business_verified' for event,fields in records)
 assert json.loads((tmp_path/'pending.json').read_text())=={}
 # New real shop route invocation, provider response simulated in stripe_gateway.
 origin={'Origin':'http://localhost:3000'};auth=TestClient(auth_app.app)
 assert auth.post('/api/customer/register',headers=origin,json={'username':'flow-client','display_name':'Test','password':'flow-client-password-123'}).status_code==201
 api=client();api.cookies.update(auth.cookies)
 created=api.post('/api/shop/orders',headers=origin,json={'request_id':str(uuid4()),'recipient':'Test','items':[{'product_id':1,'quantity':1}],'accept_demo':True})
 assert created.status_code==201,created.text
 oid=created.json()['id'];paid(stripe_gateway)
 assert api.post(f'/api/shop/orders/{oid}/verify-payment',headers=origin,json={}).json()['payment_status']=='paid'
 det.poll(detector,session,TOKEN)
 ledger=c.get('/internal/recovery-status',headers=HEADERS).json()['incidents']
 assert ledger[0]['state']=='business_verified' and ledger[0]['proof_order_id']==oid
 assert sum(event=='recovery_business_verified' for event,fields in records)==1
 assert restarts==['ansible']
