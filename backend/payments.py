"""Stripe hosted Checkout, test keys only. No card data enters this application."""
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError
from fastapi import HTTPException

API_BASE='https://api.stripe.com/v1/'

def configuration():
    mode=os.getenv('PAYMENT_MODE','stripe_test')
    key=os.getenv('STRIPE_SECRET_KEY','')
    secret=os.getenv('STRIPE_WEBHOOK_SECRET','')
    base=os.getenv('PAYMENT_PUBLIC_URL','http://localhost:3000').rstrip('/')
    parsed=urlsplit(base)
    allowed=set(os.getenv('ALLOWED_ORIGINS','http://localhost:3000').split(','))
    valid_url=base in allowed and parsed.scheme in ('http','https') and not parsed.username and not parsed.query and not parsed.fragment and parsed.path in ('','/')
    ready=mode=='stripe_test' and key.startswith('sk_test_') and secret.startswith('whsec_') and valid_url
    return {'mode':mode,'ready':ready,'test_only':True},key,secret,base

def require_ready():
    config,*_=configuration()
    if config['mode']=='demo':return
    if not config['ready']:raise HTTPException(503,'Paiement Stripe de test non configuré. Contactez l’équipe du workshop.')

def stripe_call(path,data=None,idempotency_key=None):
    config,key,_,_=configuration()
    if not config['ready']:raise HTTPException(503,'Configuration Stripe de test incomplète.')
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/x-www-form-urlencoded','Stripe-Version':'2024-06-20'}
    if idempotency_key:headers['Idempotency-Key']=idempotency_key
    request=Request(API_BASE+path,data=None if data is None else urlencode(data).encode(),headers=headers,method='GET' if data is None else 'POST')
    try:
        with urlopen(request,timeout=8) as response:result=json.load(response)
    except (URLError,TimeoutError,ValueError,OSError):
        # Never log provider messages/keys/PII; a retry uses the same idempotency key.
        raise HTTPException(503,'Stripe est momentanément inaccessible. Réessayez la même commande.') from None
    if not isinstance(result,dict) or result.get('livemode') is True:
        raise HTTPException(502,'Réponse de paiement incompatible avec le mode test.')
    return result

def checkout_session(row):
    _,_,_,base=configuration()
    result=stripe_call('checkout/sessions',{
        'mode':'payment','payment_method_types[0]':'card','locale':'fr',
        'client_reference_id':str(row['order_id']),
        'metadata[rearm_order_id]':str(row['order_id']),
        'metadata[rearm_attempt]':str(row['attempt']),
        'line_items[0][price_data][currency]':'eur',
        'line_items[0][price_data][unit_amount]':row['total_cents'],
        'line_items[0][price_data][product_data][name]':f"Commande REARM RA-{row['order_id']:05d} — démonstration",
        'line_items[0][quantity]':1,
        'success_url':base+'/?payment_return='+str(row['order_id']),
        'cancel_url':base+'/?payment_cancel='+str(row['order_id']),
        'expires_at':row['expires_at'],
    },'rearm-checkout-'+str(row['attempt']))
    if not re.fullmatch(r'cs_test_[A-Za-z0-9]+',str(result.get('id',''))):raise HTTPException(502,'Session Stripe de test invalide.')
    verify_session(result,row)
    url=urlsplit(result.get('url',''))
    if url.scheme!='https' or url.hostname!='checkout.stripe.com' or url.username:raise HTTPException(502,'Adresse de paiement invalide.')
    return result

def retrieve(session_id):
    if not re.fullmatch(r'cs_test_[A-Za-z0-9]+',session_id):raise HTTPException(400,'Session de test invalide.')
    return stripe_call('checkout/sessions/'+session_id)

def verify_session(session,payment):
    meta=session.get('metadata') or {}
    if (session.get('livemode') is not False or session.get('currency')!='eur'
        or session.get('amount_total')!=payment['total_cents']
        or session.get('client_reference_id')!=str(payment['order_id'])
        or meta.get('rearm_order_id')!=str(payment['order_id'])
        or meta.get('rearm_attempt')!=str(payment['attempt'])
        or (payment.get('session_id') and payment['session_id']!=session.get('id'))):
        raise HTTPException(409,'Le paiement ne correspond pas à la commande.')

def expire(session_id):
    result=stripe_call('checkout/sessions/'+session_id+'/expire',{},'rearm-expire-'+session_id)
    if result.get('status')!='expired':raise HTTPException(409,'Le paiement est en cours ; vérifiez son statut avant d’annuler.')
    return result

def refund(payment):
    intent=payment.get('payment_intent')
    if not intent or not re.fullmatch(r'pi_[A-Za-z0-9]+',intent):raise HTTPException(409,'Paiement à vérifier avant remboursement.')
    result=stripe_call('refunds',{'payment_intent':intent},'rearm-refund-'+str(payment['attempt']))
    if result.get('status')!='succeeded':raise HTTPException(503,'Remboursement en cours ; réessayez pour vérifier sa confirmation.')
    return result

def verify_webhook(payload,signature):
    _,_,secret,_=configuration()
    if not secret.startswith('whsec_'):raise HTTPException(503,'Notification de paiement non configurée.')
    try:
        parts=[p.split('=',1) for p in signature.split(',')]
        timestamp=int(next(v for k,v in parts if k=='t'))
        candidates=[v for k,v in parts if k=='v1']
        if abs(time.time()-timestamp)>300:raise ValueError()
        signed=str(timestamp).encode()+b'.'+payload
        expected=hmac.new(secret.encode(),signed,hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected,v) for v in candidates):raise ValueError()
        event=json.loads(payload)
        if event.get('livemode') is not False:raise ValueError()
        return event
    except (ValueError,StopIteration,TypeError,KeyError,AttributeError):
        raise HTTPException(400,'Signature de notification invalide.') from None
