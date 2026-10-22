"""Integration tests. Set REARM_TEST_DATABASE_URL to an isolated migrated PostgreSQL.
The delivery was also exercised against embedded PostgreSQL through a test adapter.
NEVER point this test at the workshop database: it truncates only shop tables.
"""
import os,sys
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('DATABASE_URL',os.getenv('REARM_TEST_DATABASE_URL','postgresql://unused'))
os.environ.setdefault('OPERATOR_PASSWORD','test-only-password-long')
os.environ.setdefault('ALLOWED_ORIGINS','http://localhost:3000')
os.environ.setdefault('CAMERA_AGENT_TOKEN','test-camera-'+'a'*40)
os.environ.setdefault('LED_DEVICE_TOKEN','test-device-'+'b'*40)
import main,auth_app,common
from security import hash_password,token_hash

pytestmark=pytest.mark.skipif(not os.getenv('REARM_TEST_DATABASE_URL') and not os.getenv('REARM_EMBEDDED_TEST'),reason='Requires an isolated PostgreSQL test database')
ORIGIN={'Origin':'http://localhost:3000'}
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module',autouse=True)
def schema():
    if os.getenv('REARM_EMBEDDED_TEST'):
        sys.path.insert(0,str(ROOT.parent/'tmp'))
        import rearm_bridge,psycopg2
        original=psycopg2.connect;psycopg2.connect=lambda *a,**k:rearm_bridge.Connection()
        for file in ['init.sql','face-auth.sql','shop.sql','payments.sql']:
            rearm_bridge.query((ROOT/'db'/file).read_text(),script=True)
        yield
        psycopg2.connect=original
    else:
        os.environ['DATABASE_URL']=os.environ['REARM_TEST_DATABASE_URL']
        with common.connection() as conn,conn.cursor() as cur:
            for file in ['init.sql','face-auth.sql','shop.sql','payments.sql']:cur.execute((ROOT/'db'/file).read_text())
        yield

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setenv("PAYMENT_MODE","demo")
    with common.connection() as conn,conn.cursor() as cur:
        cur.execute('TRUNCATE shop_audit,shop_order_items,shop_orders,shop_sessions,shop_customers,shop_products RESTART IDENTITY CASCADE')
        cur.execute('DELETE FROM login_attempts')
        cur.execute("INSERT INTO shop_products(sku,name,category,description,grade,price_cents,stock,image,workshop_note) VALUES ('TEST-01','Pièce factice','pistolets','Accessoire de cinéma sans fonction de tir.','A',8900,5,'prop-1.svg','Inspection')")

def client(name='studio'):
    c=TestClient(auth_app.app)
    r=c.post('/api/customer/register',headers=ORIGIN,json={'username':name,'display_name':'Studio test','password':'test-client-password-123'})
    assert r.status_code==201,r.text
    api=TestClient(main.app);api.cookies.update(c.cookies)
    return c,api

def payload(quantity=1,key=None):return {'request_id':str(key or uuid4()),'recipient':'Plateau fictif','items':[{'product_id':1,'quantity':quantity}],'accept_demo':True}

def row(sql):
    with common.connection() as conn,conn.cursor() as cur:cur.execute(sql);return cur.fetchone()

def staff(role='admin'):
    with common.connection() as conn,conn.cursor() as cur:
        name='test-'+role
        cur.execute('INSERT INTO operators(username,password_hash,role,enabled,face_features) VALUES (%s,%s,%s,TRUE,%s) ON CONFLICT(username) DO UPDATE SET role=EXCLUDED.role,enabled=TRUE,face_features=EXCLUDED.face_features RETURNING id',(name,hash_password('staff-test-password'),role,Json([[1.0]+[0.0]*127])))
        uid=cur.fetchone()[0];token=str(uuid4())
        cur.execute("INSERT INTO sessions(token_hash,operator_id,expires_at,face_verified) VALUES (%s,%s,NOW()+INTERVAL '1 hour',TRUE)",(token_hash(token),uid))
    c=TestClient(main.app);c.cookies.set('ra_session',token);return c

def test_catalogue_and_separate_authentication():
    auth,c=client()
    assert c.get('/api/shop/products').json()[0]['price_cents']==8900
    assert c.get('/api/shop/admin/products').status_code==401
    assert c.get('/api/auth/me').status_code==401
    assert auth.get('/api/customer/me').json()['username']=='studio'
    cookie=auth.headers if False else auth.cookies.get('rc_session')
    assert cookie and row('SELECT COUNT(*) FROM shop_sessions')[0]==1
    assert auth.post('/api/customer/logout',headers=ORIGIN,json={}).status_code==200
    assert auth.get('/api/customer/me').status_code==401

def test_order_replay_and_mismatched_replay():
    _,c=client();body=payload(2)
    first=c.post('/api/shop/orders',headers=ORIGIN,json=body)
    assert first.status_code==201,first.text
    assert first.json()['total_cents']==17800
    second=c.post('/api/shop/orders',headers=ORIGIN,json=body)
    assert second.json()['id']==first.json()['id']
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==3
    assert row('SELECT COUNT(*) FROM shop_orders')[0]==1
    body['items'][0]['quantity']=1
    assert c.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==409

def test_stock_rollback_and_no_client_price_override():
    _,c=client()
    assert c.post('/api/shop/orders',headers=ORIGIN,json=payload(6)).status_code==409
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==5
    assert row('SELECT COUNT(*) FROM shop_orders')[0]==0
    body=payload();body['price_cents']=1
    assert c.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==422
    body=payload();body['items'][0]['quantity']=-2
    assert c.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==422
    body=payload();body['items']*=2
    assert c.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==422

def test_customer_isolation_and_idempotent_cancellation():
    _,a=client('alpha');_,b=client('bravo')
    oid=a.post('/api/shop/orders',headers=ORIGIN,json=payload()).json()['id']
    assert b.get('/api/shop/orders').json()==[]
    assert b.post(f'/api/shop/orders/{oid}/cancel',headers=ORIGIN,json={}).status_code==404
    for _ in range(2):assert a.post(f'/api/shop/orders/{oid}/cancel',headers=ORIGIN,json={}).status_code==200
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==5

def test_order_state_machine_and_roles():
    _,c=client();oid=c.post('/api/shop/orders',headers=ORIGIN,json=payload()).json()['id']
    viewer=staff('viewer');operator=staff('operator')
    assert viewer.get('/api/shop/admin/orders').status_code==200
    assert viewer.post(f'/api/shop/admin/orders/{oid}/status',headers=ORIGIN,json={'status':'preparing'}).status_code==403
    assert operator.post(f'/api/shop/admin/orders/{oid}/status',headers=ORIGIN,json={'status':'collected'}).status_code==409
    for status in ('preparing','ready','collected'):
        result=operator.post(f'/api/shop/admin/orders/{oid}/status',headers=ORIGIN,json={'status':status})
        assert result.status_code==200,result.text
    assert operator.post(f'/api/shop/admin/orders/{oid}/status',headers=ORIGIN,json={'status':'cancelled'}).status_code==409
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==4

def test_catalogue_update_conflict_and_archive():
    admin=staff();p=admin.get('/api/shop/admin/products').json()[0]
    body={k:p[k] for k in ('sku','name','category','description','grade','price_cents','stock','active','image','workshop_note','version')}
    body['active']=False
    assert admin.post('/api/shop/admin/products/1',headers=ORIGIN,json=body).status_code==200
    assert admin.post('/api/shop/admin/products/1',headers=ORIGIN,json=body).status_code==409
    assert TestClient(main.app).get('/api/shop/products').json()==[]
    assert TestClient(main.app).get('/api/shop/products/1').status_code==404
    _,c=client()
    assert c.post('/api/shop/orders',headers=ORIGIN,json=payload()).status_code==409

def test_customer_disable_revokes_session():
    auth,c=client();admin=staff();uid=auth.get('/api/customer/me').json()['id']
    assert admin.post(f'/api/shop/admin/customers/{uid}/access',headers=ORIGIN,json={'enabled':False}).status_code==200
    assert c.get('/api/shop/orders').status_code==401
    assert row('SELECT COUNT(*) FROM shop_sessions')[0]==0

def test_lockout_persists_between_client_instances():
    client();c=TestClient(auth_app.app)
    body={'username':'studio','password':'wrong-password-12345'}
    for _ in range(5):assert c.post('/api/customer/login',headers=ORIGIN,json=body).status_code==401
    assert TestClient(auth_app.app).post('/api/customer/login',headers=ORIGIN,json=body).status_code==429

def test_auth_origin_and_cookies():
    c=TestClient(auth_app.app)
    body={'username':'evil','display_name':'Fictif','password':'test-password-12345'}
    assert c.post('/api/customer/register',json=body,headers={'Origin':'http://evil.invalid'}).status_code==403
    result=c.post('/api/customer/register',json=body,headers=ORIGIN)
    cookie=result.headers.get('set-cookie','')
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie

def test_multiple_items_rollback():
    _,c=client();body=payload();body['items'].append({'product_id':999,'quantity':1})
    assert c.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==409
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==5
    assert row('SELECT COUNT(*) FROM shop_orders')[0]==0

def test_no_oversell_under_simultaneous_checkout():
    _,a=client('alpha');_,b=client('bravo')
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda c:c.post('/api/shop/orders',headers=ORIGIN,json=payload(4)).status_code,[a,b]))
    assert sorted(results)==[201,409]
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==1

def test_migration_replay_preserves_orders_stock_faces_and_verified_sessions():
    _,c=client();c.post('/api/shop/orders',headers=ORIGIN,json=payload())
    admin=staff()
    with common.connection() as conn,conn.cursor() as cur:
        cur.execute("INSERT INTO transactions(account_id,beneficiary_iban,amount,reference,status,request_id) SELECT id,'DEMO-CLIENT01',0.01,'migration-test','completed',%s FROM accounts WHERE account_number='4821'",('migration-'+str(uuid4()),))
    before=(row('SELECT COUNT(*) FROM transactions')[0],row('SELECT COUNT(*) FROM sessions WHERE face_verified=TRUE')[0])
    if os.getenv('REARM_EMBEDDED_TEST'):
        import rearm_bridge
        for file in ['init.sql','face-auth.sql','shop.sql','payments.sql']:rearm_bridge.query((ROOT/'db'/file).read_text(),script=True)
    else:
        with common.connection() as conn,conn.cursor() as cur:
            for file in ['init.sql','face-auth.sql','shop.sql','payments.sql']:cur.execute((ROOT/'db'/file).read_text())
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==4
    assert len(c.get('/api/shop/orders').json())==1
    assert admin.get('/api/shop/admin/products').status_code==200
    assert before==(row('SELECT COUNT(*) FROM transactions')[0],row('SELECT COUNT(*) FROM sessions WHERE face_verified=TRUE')[0])

@pytest.fixture
def stripe_gateway(monkeypatch):
    import payments,copy
    monkeypatch.setenv('PAYMENT_MODE','stripe_test')
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_fixture')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_fixture')
    monkeypatch.setenv('PAYMENT_PUBLIC_URL','http://localhost:3000')
    state={'sessions':{},'keys':{},'creates':0,'refunds':0,'expires':0,'timeout_once':False}
    def call(path,data=None,idempotency_key=None):
        if path=='checkout/sessions':
            if idempotency_key not in state['keys']:
                state['creates']+=1;sid='cs_test_'+str(state['creates'])
                session={'id':sid,'url':'https://checkout.stripe.com/c/pay/'+sid,'livemode':False,'currency':'eur','amount_total':data['line_items[0][price_data][unit_amount]'],'client_reference_id':data['client_reference_id'],'metadata':{'rearm_order_id':data['metadata[rearm_order_id]'],'rearm_attempt':data['metadata[rearm_attempt]']},'status':'open','payment_status':'unpaid','payment_intent':None}
                state['sessions'][sid]=session;state['keys'][idempotency_key]=sid
            result=copy.deepcopy(state['sessions'][state['keys'][idempotency_key]])
            if state['timeout_once']:
                state['timeout_once']=False;raise __import__('fastapi').HTTPException(503,'Provider response lost')
            return result
        if path=='refunds':state['refunds']+=1;return {'status':'succeeded','livemode':False}
        sid=path.split('/')[2]
        if path.endswith('/expire'):
            state['expires']+=1;state['sessions'][sid]['status']='expired'
        return copy.deepcopy(state['sessions'][sid])
    monkeypatch.setattr(payments,'stripe_call',call)
    return state

def paid(gateway):
    session=next(iter(gateway['sessions'].values()));session.update(status='complete',payment_status='paid',payment_intent='pi_fixture');return session

def webhook(api,session,kind='checkout.session.completed',signature=True,timestamp=None):
    import json,time,hmac,hashlib
    event={'id':'evt_fixture','livemode':False,'type':kind,'data':{'object':session}}
    raw=json.dumps(event).encode();stamp=str(timestamp or int(time.time()));digest=hmac.new(b'whsec_fixture',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return api.post('/api/shop/payments/webhook',content=raw,headers={'Content-Type':'application/json','stripe-signature':f't={stamp},v1={digest}' if signature else 't=1,v1=forged'})

def test_stripe_order_is_pending_until_server_confirmation(stripe_gateway):
    _,api=client();body=payload();first=api.post('/api/shop/orders',headers=ORIGIN,json=body)
    assert first.status_code==201,first.text
    assert first.json()['status']=='awaiting_payment' and first.json()['payment_status']=='pending'
    assert first.json()['checkout_url'].startswith('https://checkout.stripe.com/')
    again=api.post('/api/shop/orders',headers=ORIGIN,json=body)
    assert again.json()['id']==first.json()['id'] and stripe_gateway['creates']==1
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==4
    verified=api.post(f"/api/shop/orders/{first.json()['id']}/verify-payment",headers=ORIGIN,json={})
    assert verified.json()['status']=='awaiting_payment'
    paid(stripe_gateway)
    verified=api.post(f"/api/shop/orders/{first.json()['id']}/verify-payment",headers=ORIGIN,json={})
    assert verified.json()['status']=='confirmed' and verified.json()['payment_status']=='paid'

def test_stripe_timeout_replay_reserves_and_creates_once(stripe_gateway):
    _,api=client();body=payload();stripe_gateway['timeout_once']=True
    assert api.post('/api/shop/orders',headers=ORIGIN,json=body).status_code==503
    assert row('SELECT COUNT(*) FROM shop_orders')[0]==1 and row('SELECT stock FROM shop_products WHERE id=1')[0]==4
    response=api.post('/api/shop/orders',headers=ORIGIN,json=body)
    assert response.status_code==201 and stripe_gateway['creates']==1
    assert row('SELECT stock FROM shop_products WHERE id=1')[0]==4

def test_stripe_webhook_signature_and_duplicate_notification(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json();session=paid(stripe_gateway)
    assert webhook(api,session,signature=False).status_code==400
    assert webhook(api,session,timestamp=1).status_code==400
    assert row('SELECT status FROM shop_orders')[0]=='awaiting_payment'
    for _ in range(2):assert webhook(api,session).status_code==200
    assert row("SELECT COUNT(*) FROM shop_audit WHERE action='payment_confirmed'")[0]==1
    assert row('SELECT stock FROM shop_products')[0]==4

def test_stripe_rejects_amount_mismatch(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json();session=paid(stripe_gateway);session['amount_total']=1
    response=api.post(f"/api/shop/orders/{o['id']}/verify-payment",headers=ORIGIN,json={})
    assert response.status_code==409 and row('SELECT status FROM shop_orders')[0]=='awaiting_payment'

def test_stripe_pending_cancel_closes_session_then_restock_once(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json()
    for _ in range(2):assert api.post(f"/api/shop/orders/{o['id']}/cancel",headers=ORIGIN,json={}).status_code==200
    assert stripe_gateway['expires']==1 and row('SELECT stock FROM shop_products')[0]==5
    assert row('SELECT state FROM shop_order_payments')[0]=='cancelled'

def test_stripe_paid_cancellation_refunds_once(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json();session=paid(stripe_gateway)
    assert webhook(api,session).status_code==200
    for _ in range(2):assert api.post(f"/api/shop/orders/{o['id']}/cancel",headers=ORIGIN,json={}).status_code==200
    assert stripe_gateway['refunds']==1 and row('SELECT stock FROM shop_products')[0]==5
    assert row('SELECT state FROM shop_order_payments')[0]=='refunded'
    assert webhook(api,session).status_code==200
    assert row('SELECT state FROM shop_order_payments')[0]=='refunded'

def test_stripe_expired_webhook_restocks_once(stripe_gateway):
    _,api=client();api.post('/api/shop/orders',headers=ORIGIN,json=payload())
    session=next(iter(stripe_gateway['sessions'].values()));session['status']='expired'
    for _ in range(2):assert webhook(api,session,'checkout.session.expired').status_code==200
    assert row('SELECT status FROM shop_orders')[0]=='cancelled'
    assert row('SELECT stock FROM shop_products')[0]==5

def test_stripe_wrong_owner_and_staff_cannot_prepare_unpaid(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json();_,other=client('another')
    assert other.post(f"/api/shop/orders/{o['id']}/verify-payment",headers=ORIGIN,json={}).status_code==404
    admin=staff()
    assert admin.post(f"/api/shop/admin/orders/{o['id']}/status",headers=ORIGIN,json={'status':'preparing'}).status_code==409
    assert row('SELECT status FROM shop_orders')[0]=='awaiting_payment'

def test_stripe_live_key_blocked_before_reservation(stripe_gateway,monkeypatch):
    _,api=client();monkeypatch.setenv('STRIPE_SECRET_KEY','sk_live_refused')
    assert api.get('/api/shop/payment-config').json()['ready'] is False
    assert api.post('/api/shop/orders',headers=ORIGIN,json=payload()).status_code==503
    assert row('SELECT COUNT(*) FROM shop_orders')[0]==0 and row('SELECT stock FROM shop_products')[0]==5

def test_stripe_bad_currency_and_live_response_refused(stripe_gateway):
    _,api=client();o=api.post('/api/shop/orders',headers=ORIGIN,json=payload()).json();session=paid(stripe_gateway)
    session['currency']='usd'
    assert webhook(api,session).status_code==409
    session['currency']='eur';session['livemode']=True
    assert webhook(api,session).status_code==409
    assert row('SELECT status FROM shop_orders')[0]=='awaiting_payment'

def test_stripe_timeout_before_session_persist_webhook_recovers(stripe_gateway):
    _,api=client();stripe_gateway['timeout_once']=True
    assert api.post('/api/shop/orders',headers=ORIGIN,json=payload()).status_code==503
    assert row('SELECT session_id FROM shop_order_payments')[0] is None
    session=paid(stripe_gateway)
    assert webhook(api,session).status_code==200
    assert row('SELECT status FROM shop_orders')[0]=='confirmed'
    assert row('SELECT session_id FROM shop_order_payments')[0]==session['id']
