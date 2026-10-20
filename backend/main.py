import os
import secrets
import time
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from contextlib import asynccontextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from security import hash_password, check_password, token_hash, valid_amount

DATABASE_URL = os.environ['DATABASE_URL']
metrics = deque(maxlen=500)
# Development on HTTP only. Set COOKIE_SECURE=true behind HTTPS.
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
ALLOWED_ORIGINS = set(os.environ['ALLOWED_ORIGINS'].split(','))


def connection():
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


@asynccontextmanager
async def lifespan(app):
    password = os.environ['OPERATOR_PASSWORD']
    if len(password) < 12:
        raise RuntimeError('OPERATOR_PASSWORD must contain at least 12 characters')
    with connection() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO operators (username, password_hash) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                    (os.getenv('OPERATOR_USERNAME', 'operateur'), hash_password(password)))
    yield


app = FastAPI(title='ResiliencePay API', version='0.2.0', lifespan=lifespan)


@app.middleware('http')
async def observe(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path != '/internal/metrics':
        if request.headers.get('origin') not in ALLOWED_ORIGINS:
            return Response('Origin not allowed', status_code=403)
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        metrics.append({'timestamp': datetime.now(timezone.utc).isoformat(), 'status': response.status_code,
                        'latency_ms': round((time.perf_counter() - started) * 1000, 2)})
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def current_user(request: Request):
    token = request.cookies.get('ra_session', '')
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT o.id, o.username, o.role FROM sessions s JOIN operators o ON o.id=s.operator_id WHERE s.token_hash=%s AND s.expires_at>NOW() AND o.enabled=TRUE AND o.face_features IS NOT NULL AND s.face_verified=TRUE', (token_hash(token),))
        user = cur.fetchone()
    if not user:
        raise HTTPException(401, 'Connexion requise ou session expirée.')
    return user


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return {'username': user['username'], 'role': user['role']}


@app.post('/api/auth/logout')
def logout(request: Request, response: Response):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM sessions WHERE token_hash=%s', (token_hash(request.cookies.get('ra_session', '')),))
    response.delete_cookie('ra_session', path='/')
    return {'status': 'disconnected'}


class Payment(BaseModel):
    beneficiary_iban: str = Field(min_length=8, max_length=64)
    amount: Decimal = Field(gt=0, le=1000000)
    reference: str = Field(default='', max_length=255)
    request_id: str = Field(min_length=16, max_length=80)

    @field_validator('amount')
    @classmethod
    def cents(cls, value):
        if not valid_amount(value):
            raise ValueError('Le montant doit avoir au plus deux décimales.')
        return value

    @field_validator('beneficiary_iban')
    @classmethod
    def beneficiary(cls, value):
        value = value.replace(' ', '').upper()
        # Explicit fictional account IDs, never imply real banking validation.
        if not value.startswith('DEMO-') or not value[5:].isalnum() or len(value) < 8:
            raise ValueError('Utilisez un bénéficiaire fictif de forme DEMO-CLIENT01.')
        return value


@app.get('/health')
def health():
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1')
        return {'status': 'ok', 'database': 'ok'}
    except psycopg2.Error:
        raise HTTPException(503, 'Base de données indisponible')


@app.get('/api/account')
def account(user=Depends(current_user)):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT account_number,owner_name,balance FROM accounts WHERE account_number='4821'")
        return cur.fetchone()


@app.post('/api/pay', status_code=201)
def pay(payment: Payment, user=Depends(current_user)):
    if user['role'] not in ('operator','admin'):
        raise HTTPException(403, 'Votre role ne permet pas les paiements.')
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id,balance FROM accounts WHERE account_number='4821' FOR UPDATE")
        account = cur.fetchone()
        cur.execute('SELECT id,status,created_at,beneficiary_iban,amount,reference FROM transactions WHERE request_id=%s', (payment.request_id,))
        previous = cur.fetchone()
        if previous:
            if (previous['beneficiary_iban'], previous['amount'], previous['reference']) != (payment.beneficiary_iban, payment.amount, payment.reference):
                raise HTTPException(409, 'Identifiant déjà utilisé pour un autre paiement.')
            return previous
        if not account or account['balance'] < payment.amount:
            raise HTTPException(400, 'Solde insuffisant.')
        cur.execute('UPDATE accounts SET balance=balance-%s WHERE id=%s', (payment.amount, account['id']))
        cur.execute("INSERT INTO transactions(account_id,beneficiary_iban,amount,reference,status,request_id) VALUES (%s,%s,%s,%s,'completed',%s) RETURNING id,status,created_at", (account['id'], payment.beneficiary_iban,payment.amount,payment.reference,payment.request_id))
        return cur.fetchone()


@app.get('/api/transactions')
def transactions(limit: int = 25, user=Depends(current_user)):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT id,beneficiary_iban,amount,reference,status,created_at FROM transactions ORDER BY created_at DESC,id DESC LIMIT %s', (max(1,min(limit,100)),))
        return cur.fetchall()


def metric_summary():
    recent = list(metrics)[-100:]
    errors = sum(x['status'] >= 500 for x in recent)
    return {'sample_count': len(recent), 'error_count': errors, 'error_rate': errors / len(recent) if recent else 0,
            'latency_ms': round(sum(x['latency_ms'] for x in recent)/len(recent),2) if recent else None, 'recent': recent}


@app.get('/metrics', response_class=PlainTextResponse)
def prometheus():
    summary = metric_summary()
    return f"# TYPE resilience_api_requests_window gauge\nresilience_api_requests_window {summary['sample_count']}\n# TYPE resilience_api_error_rate gauge\nresilience_api_error_rate {summary['error_rate']}\n"


@app.get('/internal/metrics')
def internal_metrics():
    return metric_summary()


@app.get('/api/monitor')
def monitor(user=Depends(current_user)):
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'health': health(), 'metrics': metric_summary(),
            'missing': ['WAF', 'Service authentification séparé', 'Prometheus / Grafana / Loki', 'Assistant RAG', 'Ansible', 'Vault ou SOPS'],
            'note': 'Le détecteur et la remédiation ne sont pas encore supervisés par cette interface.'}


from face_auth import make_router
app.include_router(make_router(connection, current_user, COOKIE_SECURE))
