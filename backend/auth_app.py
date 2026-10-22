"""Authentication boundary: host camera, device, operators and customer sessions."""
import os
import psycopg2
from fastapi import FastAPI,Depends,Request,Response
from fastapi.responses import JSONResponse
from common import connection,operator
from face_auth import make_router
from customer_auth import router as customer_router
from security import token_hash

app=FastAPI(title='REARM Identity',docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware('http')
async def protection(request:Request,call_next):
    allowed=set(os.environ['ALLOWED_ORIGINS'].split(','))
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('origin') not in allowed:
        return Response('Origin not allowed',status_code=403)
    try:
        response=await call_next(request)
    except psycopg2.Error:
        print('{"event":"identity_database_unavailable"}',flush=True)
        response=JSONResponse({'detail':'Service d’identité momentanément indisponible.'},status_code=503)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.get('/health')
def health():
    with connection() as conn,conn.cursor() as cur:cur.execute('SELECT 1')
    return {'status':'ok','service':'auth'}

@app.get('/api/auth/me')
def me(user=Depends(operator)):
    return {'username':user['username'],'role':user['role']}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response):
    with connection() as conn,conn.cursor() as cur:
        cur.execute('DELETE FROM sessions WHERE token_hash=%s',(token_hash(request.cookies.get('ra_session','')),))
    response.delete_cookie('ra_session',path='/')
    return {'status':'disconnected'}

app.include_router(make_router(connection,operator,os.getenv('COOKIE_SECURE','false').lower()=='true'))
app.include_router(customer_router)
