"""Authenticated recovery ledger. HTTP health and DB readiness never prove payment."""
import math,os,secrets
from datetime import datetime,timezone,timedelta
from typing import Literal
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict,field_validator

INTERNAL_POSTS=frozenset(('/internal/incidents','/internal/recovery/reconcile'))

def authorize(request:Request):
    expected=os.getenv('REMEDIATION_TOKEN','')
    if not expected or not secrets.compare_digest(request.headers.get('authorization','').encode(),('Bearer '+expected).encode()):
        raise HTTPException(401,'Internal authorization required')

class Report(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ref:str=Field(pattern=r'^INC-[a-f0-9]{12}$')
    status:Literal['remediation','echec','attente_metier']
    reason:Literal['ml_anomaly_with_confirmed_health_failure','availability_fallback_six_failed_health_probes']
    action:Literal['redemarrage_api_boutique']
    opened_at:datetime
    closed_at:datetime|None=None
    detail:dict=Field(default_factory=dict,max_length=32)
    result:dict=Field(default_factory=dict,max_length=32)
    business_verified:Literal[False]|None=None
    @field_validator('opened_at')
    @classmethod
    def valid_time(cls,value):
        now=datetime.now(timezone.utc)
        if value.tzinfo is None or value>now+timedelta(minutes=2) or value<now-timedelta(days=7):
            raise ValueError('Incident timestamp outside accepted window')
        return value

def readiness(connection):
    # A dedicated rollback-only marker proves DB writeability without touching
    # stock, customers, orders, sequence counters or external payment APIs.
    marker=secrets.token_hex(16)
    with connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='1500ms'")
                cur.execute("SET LOCAL lock_timeout='500ms'")
                cur.execute('SELECT COUNT(*) FROM shop_products WHERE active=TRUE')
                if cur.fetchone()[0]<1:raise HTTPException(503,'Catalogue unavailable')
                cur.execute('UPDATE rearm_recovery_probe SET marker=%s WHERE id=1 RETURNING marker',(marker,))
                row=cur.fetchone()
                if not row or row[0]!=marker:raise HTTPException(503,'Database readiness unavailable')
        finally:conn.rollback()
    return {'scope':'catalogue_and_rollback_write','transactional_readiness_verified':True,
            'business_recovery_verified':False,'payment_verified':False,'writes_rolled_back':True}

def reconcile(connection):
    # Only the shop's existing provider-validated settlement path writes paid.
    # Never trust a browser return parameter, the detector, or a dry-run probe.
    if os.getenv('PAYMENT_MODE','stripe_test')!='stripe_test':return
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL statement_timeout='2000ms'")
        cur.execute("SET LOCAL lock_timeout='500ms'")
        cur.execute("""SELECT ref,technical_at FROM rearm_recovery_incidents
          WHERE state='technical_recovered' AND technical_at>NOW()-INTERVAL '24 hours'
          ORDER BY ref FOR UPDATE""")
        incidents=cur.fetchall()
        for incident in incidents:
            cur.execute("""SELECT o.id FROM shop_orders o JOIN shop_order_payments p ON p.order_id=o.id
              WHERE o.created_at>=%s AND p.updated_at>=%s
                AND o.status IN ('confirmed','preparing','ready','collected') AND o.total_cents>0
                AND p.state='paid' AND p.payment_intent IS NOT NULL AND LEFT(p.session_id,8)='cs_test_'
              ORDER BY o.created_at,o.id LIMIT 1""",(incident['technical_at'],incident['technical_at']))
            order=cur.fetchone()
            if not order:continue
            cur.execute("""UPDATE rearm_recovery_incidents SET state='business_verified',proof_order_id=%s,
              closed_at=NOW(),updated_at=NOW() WHERE ref=%s AND state='technical_recovered'""",(order['id'],incident['ref']))

def states(connection):
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT ref,state,opened_at,technical_at,closed_at,proof_order_id FROM rearm_recovery_incidents ORDER BY recorded_at DESC LIMIT 50')
        rows=cur.fetchall()
    for row in rows:
        row['technical_recovery_verified']=row['technical_at'] is not None
        row['business_recovery_verified']=row['state']=='business_verified' and row['proof_order_id'] is not None
    return rows

def metrics(connection):
    try:
        with connection() as conn,conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='1000ms'")
            cur.execute('SELECT state,COUNT(*) FROM rearm_recovery_incidents GROUP BY state')
            counts=dict(cur.fetchall())
        lines=['# TYPE rearm_recovery_ledger_available gauge','rearm_recovery_ledger_available 1',
               '# TYPE rearm_recovery_incidents gauge']
        for state in ('remediation','technical_recovered','failed','business_verified'):
            lines.append(f'rearm_recovery_incidents{{state="{state}"}} {counts.get(state,0)}')
        return '\n'.join(lines)+'\n'
    except psycopg2.Error:
        # No fabricated zero incident counts when the database/ledger is unavailable.
        return '# TYPE rearm_recovery_ledger_available gauge\nrearm_recovery_ledger_available 0\n'

def make_router(connection):
    router=APIRouter(dependencies=[Depends(authorize)])
    @router.get('/internal/business-probe',include_in_schema=False)
    def probe():
        try:return readiness(connection)
        except psycopg2.Error:raise HTTPException(503,'Database readiness unavailable') from None

    @router.post('/internal/incidents',include_in_schema=False)
    def report(data:Report):
        if data.status=='attente_metier':
            if data.result.get('technical_recovery_verified') is not True:
                raise HTTPException(422,'Technical confirmation required')
            try:readiness(connection)
            except psycopg2.Error:raise HTTPException(503,'Readiness verification failed') from None
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='1000ms'")
            cur.execute("""INSERT INTO rearm_recovery_incidents(ref,reason,state,opened_at)
              VALUES (%s,%s,'remediation',%s) ON CONFLICT(ref) DO NOTHING""",(data.ref,data.reason,data.opened_at))
            cur.execute('SELECT state,reason FROM rearm_recovery_incidents WHERE ref=%s FOR UPDATE',(data.ref,))
            previous=cur.fetchone()
            if previous['reason']!=data.reason:raise HTTPException(409,'Incident reference already used')
            if previous['state']=='business_verified':return {'ref':data.ref,'state':'business_verified'}
            state={'remediation':'remediation','echec':'failed','attente_metier':'technical_recovered'}[data.status]
            # A delayed initial message cannot erase a later confirmed technical state.
            if state=='remediation' and previous['state']!='remediation':state=previous['state']
            cur.execute("""UPDATE rearm_recovery_incidents SET state=%s,updated_at=NOW(),
              technical_at=CASE WHEN %s='technical_recovered' THEN COALESCE(technical_at,NOW()) ELSE technical_at END
              WHERE ref=%s""",(state,state,data.ref))
        return {'ref':data.ref,'state':state,'business_recovery_verified':False}

    @router.get('/internal/recovery-status',include_in_schema=False)
    def status():return {'incidents':states(connection)}

    @router.post('/internal/recovery/reconcile',include_in_schema=False)
    def verify():
        reconcile(connection)
        return {'incidents':states(connection)}
    return router
