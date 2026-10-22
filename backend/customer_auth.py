"""Separate client identity; never grants access to operator/back-office routes."""
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator
from psycopg2 import errors
from psycopg2.extras import RealDictCursor
from common import connection,customer
from security import hash_password,check_password,token_hash

router=APIRouter(prefix='/api/customer')
DUMMY_HASH=hash_password('invalid-user-placeholder-long')

class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=3,max_length=80,pattern=r'^[a-z0-9._-]+$')
    password:str=Field(min_length=12,max_length=128)

class Registration(Credentials):
    display_name:str=Field(min_length=2,max_length=80)
    @field_validator('display_name')
    @classmethod
    def clean_name(cls,value):
        if len(value.strip())<2:raise ValueError('Nom fictif trop court.')
        return value.strip()

def bucket(request,username):
    # Only our frontend proxy supplies x-rearm-client-ip; never trust a browser field.
    client=request.headers.get('x-rearm-client-ip',request.client.host if request.client else 'unknown')
    return token_hash('shop:'+username+':'+client)

def limit(cur,key):
    cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(key,))
    cur.execute("DELETE FROM login_attempts WHERE created_at<NOW()-INTERVAL '5 minutes'")
    cur.execute('SELECT COUNT(*) AS n FROM login_attempts WHERE bucket=%s',(key,))
    if cur.fetchone()['n']>=5:
        raise HTTPException(429,'Trop de tentatives. Patientez cinq minutes.')

def session(cur,user,response):
    token=secrets.token_urlsafe(32)
    cur.execute('DELETE FROM shop_sessions WHERE expires_at<=NOW()')
    cur.execute("INSERT INTO shop_sessions(token_hash,customer_id,expires_at) VALUES (%s,%s,NOW()+INTERVAL '8 hours')",(token_hash(token),user['id']))
    response.set_cookie('rc_session',token,httponly=True,secure=os.getenv('COOKIE_SECURE','false').lower()=='true',samesite='strict',max_age=28800,path='/')
    return {k:user[k] for k in ('id','username','display_name')}

@router.post('/register',status_code=201)
def register(body:Registration,request:Request,response:Response):
    key=bucket(request,'registration')
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        limit(cur,key)
        cur.execute('INSERT INTO login_attempts(bucket) VALUES (%s)',(key,))
        # Keep signup throttle even when a username is already in use.
        conn.commit()
    try:
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('INSERT INTO shop_customers(username,display_name,password_hash) VALUES (%s,%s,%s) RETURNING id,username,display_name',(body.username,body.display_name.strip(),hash_password(body.password)))
            return session(cur,cur.fetchone(),response)
    except errors.UniqueViolation:
        raise HTTPException(409,'Cet identifiant est déjà utilisé.')

@router.post('/login')
def login(body:Credentials,request:Request,response:Response):
    key=bucket(request,body.username)
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        limit(cur,key)
        cur.execute('SELECT * FROM shop_customers WHERE username=%s',(body.username,))
        user=cur.fetchone()
        stored=user['password_hash'] if user else DUMMY_HASH
        valid=check_password(body.password,stored)
        if not user or not user['enabled'] or not valid:
            cur.execute('INSERT INTO login_attempts(bucket) VALUES (%s)',(key,))
            result=None
        else:
            cur.execute('DELETE FROM login_attempts WHERE bucket=%s',(key,))
            result=session(cur,user,response)
    if result is None:
        raise HTTPException(401,'Identifiant ou mot de passe incorrect.')
    return result

@router.get('/me')
def me(user=Depends(customer)):
    return user

@router.post('/logout')
def logout(request:Request,response:Response):
    with connection() as conn,conn.cursor() as cur:
        cur.execute('DELETE FROM shop_sessions WHERE token_hash=%s',(token_hash(request.cookies.get('rc_session','')),))
    response.delete_cookie('rc_session',path='/')
    return {'status':'disconnected'}
