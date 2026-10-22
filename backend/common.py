"""Shared database access and identity checks for the API and auth service."""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException, Request
from security import token_hash


def connection():
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=3)


def operator(request: Request):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT o.id,o.username,o.role FROM sessions s JOIN operators o ON o.id=s.operator_id WHERE s.token_hash=%s AND s.expires_at>NOW() AND o.enabled=TRUE AND o.face_features IS NOT NULL AND s.face_verified=TRUE', (token_hash(request.cookies.get('ra_session','')),))
        user=cur.fetchone()
    if not user:
        raise HTTPException(401,'Connexion du personnel requise.')
    return user


def customer(request: Request):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT c.id,c.username,c.display_name FROM shop_sessions s JOIN shop_customers c ON c.id=s.customer_id WHERE s.token_hash=%s AND s.expires_at>NOW() AND c.enabled=TRUE',(token_hash(request.cookies.get('rc_session','')),))
        user=cur.fetchone()
    if not user:
        raise HTTPException(401,'Connectez-vous à votre compte client.')
    return user
