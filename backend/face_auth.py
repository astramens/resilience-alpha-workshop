"""USB host camera authentication. This module never accepts browser face evidence."""
import json
import os
import secrets
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from psycopg2.extras import Json, RealDictCursor
from security import hash_password, check_password, token_hash
from face_rules import (advance, face_matches, face_rejected, led, normalise,
                        public_state, FLOW_LIFETIME, PASSWORD_COOLDOWN, SUCCESS_DELAY)


def make_router(connection, current_user, cookie_secure):
    router = APIRouter()
    agent_token = os.environ['CAMERA_AGENT_TOKEN']
    device_token = os.environ['LED_DEVICE_TOKEN']
    threshold = float(os.getenv('FACE_COSINE_THRESHOLD','0.45'))
    if len(agent_token)<32 or len(device_token)<32 or not 0<threshold<1:
        raise RuntimeError('Invalid facial authentication configuration')
    bootstrap_username = os.getenv('OPERATOR_USERNAME','operateur')

    @contextmanager
    def transaction():
        with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT data,EXTRACT(EPOCH FROM NOW()) AS now FROM face_auth_state WHERE id=1 FOR UPDATE')
            row = cur.fetchone()
            if not row:
                raise HTTPException(503,'Migration de la base requise.')
            data, now = row['data'], float(row['now'])
            advance(data,now)
            try:
                yield cur, data, now
            except HTTPException:
                # Failed attempts and consumed proofs MUST survive the error response.
                cur.execute('UPDATE face_auth_state SET data=%s WHERE id=1',(Json(data),))
                conn.commit()
                raise
            else:
                cur.execute('UPDATE face_auth_state SET data=%s WHERE id=1',(Json(data),))

    def agent(authorization: str=Header(default='')):
        if not secrets.compare_digest(authorization,'Bearer '+agent_token):
            raise HTTPException(401,'Agent non autorise.')

    def admin(user=Depends(current_user)):
        if user['role']!='admin':
            raise HTTPException(403,'Droit administrateur requis.')
        return user

    def audit(action, username):
        print(json.dumps({'event':action,'username':username}, ensure_ascii=True),flush=True)

    def owned(request,data):
        flow=data.get('flow')
        if not flow or flow['kind']!='login' or not secrets.compare_digest(
                flow['proof_hash'],token_hash(request.cookies.get('ra_pre_auth',''))):
            raise HTTPException(401,'Identification expiree. Recommencez.')
        return flow

    def reserve(data,now):
        f=data.get('flow')
        if f and (f['stage'] in ('camera','face_ok','success_wait') or now<f.get('ready_at',0)):
            raise HTTPException(409,'La camera du PC Hote est deja utilisee. Patientez.')

    def new_flow(data,now,username,kind,user_id=None,proof=None):
        reserve(data,now)
        f={'id':secrets.token_urlsafe(24),'username':username,'user_id':user_id,
           'kind':kind,'stage':'camera','claimed':False,'expires_at':now+FLOW_LIFETIME,
           'proof_hash':token_hash(proof or secrets.token_urlsafe(32))}
        data['flow']=f
        led(data,'off',now,0)
        return f

    @router.get('/api/auth/config')
    def config():
        with transaction() as (cur,data,now):
            return {'face_required':True,'camera_agent_online':now-data.get('agent_seen',0)<10,
                    'led_online':now-data.get('device_seen',0)<10}

    class Identity(BaseModel):
        username:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9._-]+$')

    @router.post('/api/auth/identify')
    def identify(body:Identity,request:Request,response:Response):
        proof=secrets.token_urlsafe(32)
        with transaction() as (cur,data,now):
            # A refresh or second request cannot replace an active proof/attempt.
            f=data.get('flow')
            if f and f['kind']=='login' and secrets.compare_digest(f['proof_hash'],token_hash(request.cookies.get('ra_pre_auth',''))):
                if f['stage'] in ('camera','face_ok','success_wait'):
                    return public_state(f,now)
            fail=data.get('failures',{}).get(body.username,{})
            if fail.get('blocked_until',0)>now:
                raise HTTPException(429,'Deux echecs de reconnaissance. Patientez cinq minutes.')
            if now-data.get('agent_seen',0)>=10:
                raise HTTPException(503,'Agent camera du PC Hote hors ligne. Lancez-le sur ce PC.')
            cur.execute('SELECT id FROM operators WHERE username=%s AND enabled=TRUE',(body.username,))
            user=cur.fetchone()
            if fail.get('blocked_until',0) and fail['blocked_until']<=now:
                data['failures'].pop(body.username,None)
            f=new_flow(data,now,body.username,'login',user['id'] if user else None,proof)
            response.set_cookie('ra_pre_auth',proof,httponly=True,secure=cookie_secure,
                                samesite='strict',max_age=360,path='/')
            audit('face_identification_started',body.username)
            return public_state(f,now)

    @router.get('/api/auth/face-status')
    def status(request:Request):
        with transaction() as (cur,data,now):
            return public_state(owned(request,data),now)

    @router.post('/api/auth/cancel')
    def cancel(request:Request,response:Response):
        with transaction() as (cur,data,now):
            f=owned(request,data)
            if now<f.get('ready_at',0):
                raise HTTPException(409,'Patientez jusqu a la fin du signal lumineux.')
            data['flow']=None
            led(data,'off',now,0)
        response.delete_cookie('ra_pre_auth',path='/')
        return {'status':'cancelled'}

    class Password(BaseModel):
        password:str=Field(min_length=1,max_length=256)
        username:str|None=Field(default=None,max_length=80)

    @router.post('/api/auth/login')
    def login(body:Password,request:Request):
        with transaction() as (cur,data,now):
            f=owned(request,data)
            if f['stage']!='face_ok':
                raise HTTPException(409,'La reconnaissance du visage doit preceder le mot de passe.')
            # This proof is consumed exactly once, even for a wrong password.
            f['stage']='password_rejected'
            cur.execute('SELECT * FROM operators WHERE id=%s FOR UPDATE',(f['user_id'],))
            user=cur.fetchone()
            cur.execute("DELETE FROM login_attempts WHERE created_at<NOW()-INTERVAL '5 minutes'")
            bucket=token_hash('face-password:'+f['username'])
            cur.execute('SELECT COUNT(*) AS n FROM login_attempts WHERE bucket=%s',(bucket,))
            blocked=cur.fetchone()['n']>=5
            if not user or not user['enabled'] or not user['face_features'] or blocked or not check_password(body.password,user['password_hash']):
                cur.execute('INSERT INTO login_attempts(bucket) VALUES(%s)',(bucket,))
                f['ready_at']=now+PASSWORD_COOLDOWN
                f['expires_at']=now+PASSWORD_COOLDOWN+30
                led(data,'red_blink_10',now,PASSWORD_COOLDOWN)
                audit('face_password_rejected',f['username'])
                return {**public_state(f,now),'message':'Mot de passe refuse. Reprenez toute l identification.'}
            cur.execute('DELETE FROM login_attempts WHERE bucket=%s',(bucket,))
            f.update(stage='success_wait',ready_at=now+SUCCESS_DELAY,expires_at=now+SUCCESS_DELAY+60)
            data.setdefault('failures',{}).pop(f['username'],None)
            led(data,'green_fixed',now,SUCCESS_DELAY)
            return public_state(f,now)

    @router.post('/api/auth/finish')
    def finish(request:Request,response:Response):
        token=secrets.token_urlsafe(32)
        with transaction() as (cur,data,now):
            f=owned(request,data)
            if f['stage']!='success_wait' or now<f['ready_at']:
                raise HTTPException(409,'Authentification non terminee.')
            cur.execute('SELECT username,role,enabled,face_features FROM operators WHERE id=%s',(f['user_id'],))
            user=cur.fetchone()
            if not user or not user['enabled'] or not user['face_features']:
                raise HTTPException(403,'Compte desactive ou visage revoque.')
            cur.execute("DELETE FROM sessions WHERE expires_at<=NOW()")
            cur.execute("INSERT INTO sessions(token_hash,operator_id,expires_at,face_verified) VALUES(%s,%s,NOW()+INTERVAL '8 hours',TRUE)",(token_hash(token),f['user_id']))
            data['flow']=None
            led(data,'off',now,0)
        response.set_cookie('ra_session',token,httponly=True,secure=cookie_secure,samesite='strict',max_age=28800,path='/')
        response.delete_cookie('ra_pre_auth',path='/')
        audit('face_login_succeeded',user['username'])
        return {'username':user['username'],'role':user['role']}

    class Bootstrap(Identity):
        password:str=Field(min_length=1,max_length=256)

    @router.post('/api/face-agent/bootstrap',dependencies=[Depends(agent)])
    def bootstrap(body:Bootstrap):
        with transaction() as (cur,data,now):
            cur.execute("SELECT COUNT(*) AS n FROM operators WHERE face_features IS NOT NULL AND role='admin' AND enabled=TRUE")
            if cur.fetchone()['n']:
                raise HTTPException(403,'Initialisation fermee. Utilisez le panneau utilisateurs.')
            if body.username!=bootstrap_username:
                raise HTTPException(403,'Utilisez le compte operateur initial.')
            cur.execute('SELECT * FROM operators WHERE username=%s AND enabled=TRUE FOR UPDATE',(body.username,))
            user=cur.fetchone()
            if not user or not check_password(body.password,user['password_hash']):
                raise HTTPException(401,'Identifiants incorrects.')
            f=new_flow(data,now,body.username,'bootstrap',user['id'])
            return {'id':f['id'],'username':f['username'],'kind':f['kind']}

    @router.get('/api/face-agent/next',dependencies=[Depends(agent)])
    def next_job():
        with transaction() as (cur,data,now):
            data['agent_seen']=now
            f=data.get('flow')
            if f and f['stage']=='camera' and not f['claimed']:
                f['claimed']=True
                return {'job':{'id':f['id'],'kind':f['kind'],'username':f['username']}}
            return {'job':None}

    @router.get('/api/face-agent/job/{job_id}',dependencies=[Depends(agent)])
    def job_state(job_id:str):
        with transaction() as (cur,data,now):
            data['agent_seen']=now
            f=data.get('flow')
            if not f or f['id']!=job_id:
                return {'stage':'cancelled','camera_on':False}
            return public_state(f,now)

    class Evidence(BaseModel):
        features:list[list[float]]=Field(default_factory=list,max_length=5)
        error:str|None=Field(default=None,max_length=80)

    @router.post('/api/face-agent/result/{job_id}',dependencies=[Depends(agent)])
    def evidence(job_id:str,body:Evidence):
        for feature in body.features:
            try: normalise(feature)
            except ValueError: raise HTTPException(422,'Empreinte faciale invalide.')
        with transaction() as (cur,data,now):
            data['agent_seen']=now
            f=data.get('flow')
            if not f or f['id']!=job_id or f['stage']!='camera':
                raise HTTPException(409,'Capture deja consommee ou expiree.')
            if body.error:
                f.update(stage='camera_error',expires_at=now+30)
                led(data,'off',now,0)
                return public_state(f,now)
            cur.execute('SELECT * FROM operators WHERE id=%s FOR UPDATE',(f['user_id'],))
            user=cur.fetchone()
            if f['kind'] in ('enroll','bootstrap'):
                if not user or not user['enabled'] or len(body.features)<3:
                    f.update(stage='camera_error',expires_at=now+30)
                    return public_state(f,now)
                cur.execute('UPDATE operators SET face_features=%s WHERE id=%s',(Json(body.features),user['id']))
                if f['kind']=='bootstrap':
                    cur.execute("UPDATE operators SET role='admin' WHERE id=%s",(user['id'],))
                cur.execute('DELETE FROM sessions WHERE operator_id=%s',(user['id'],))
                f.update(stage='enrolled',expires_at=now+30)
                led(data,'off',now,0)
                return public_state(f,now)
            matched=bool(user and user['enabled'] and face_matches(body.features,user['face_features'] or [],threshold))
            audit('face_recognized' if matched else 'face_rejected',f['username'])
            if matched:
                f.update(stage='face_ok',expires_at=now+120)
                led(data,'green_blink',now,120)
            else:
                face_rejected(data,f,now)
                data['failures'][f['username']]['updated_at']=now
                f['expires_at']=now+60
            return public_state(f,now)

    @router.get('/api/device/led')
    def device(authorization:str=Header(default='')):
        if not secrets.compare_digest(authorization,'Bearer '+device_token):
            raise HTTPException(401,'Module non autorise.')
        with transaction() as (cur,data,now):
            data['device_seen']=now
            command=data.get('led',{'mode':'off','started':now,'ends':now})
            return {'mode':command['mode'],'command_id':str(command['started']),
                    'elapsed_ms':max(0,int((now-command['started'])*1000)),
                    'remaining_ms':max(0,int((command['ends']-now)*1000))}

    @router.get('/api/admin/users')
    def users(user=Depends(admin)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,username,role,enabled,(face_features IS NOT NULL) AS face_enrolled FROM operators ORDER BY id')
            return cur.fetchall()

    class UserCreate(Identity):
        password:str=Field(min_length=12,max_length=256)
        role:str=Field(default='operator',pattern='^(admin|operator|viewer)$')

    @router.post('/api/admin/users',status_code=201)
    def create_user(body:UserCreate,user=Depends(admin)):
        with transaction() as (cur,data,now):
            cur.execute('SELECT id FROM operators WHERE username=%s',(body.username,))
            if cur.fetchone(): raise HTTPException(409,'Cet identifiant existe deja.')
            cur.execute('INSERT INTO operators(username,password_hash,role) VALUES(%s,%s,%s) RETURNING id',(body.username,hash_password(body.password),body.role))
            return {'id':cur.fetchone()['id']}

    class UserUpdate(BaseModel):
        role:str=Field(pattern='^(admin|operator|viewer)$')
        enabled:bool

    @router.post('/api/admin/users/{target}/access')
    def update_access(target:int,body:UserUpdate,user=Depends(admin)):
        if target==user['id']:
            raise HTTPException(409,'Modifiez vos droits avec un autre administrateur.')
        with transaction() as (cur,data,now):
            cur.execute('UPDATE operators SET role=%s,enabled=%s WHERE id=%s RETURNING id',(body.role,body.enabled,target))
            if not cur.fetchone(): raise HTTPException(404,'Compte introuvable.')
            cur.execute('DELETE FROM sessions WHERE operator_id=%s',(target,))
            if (data.get('flow') or {}).get('user_id')==target:
                data['flow']=None
                led(data,'off',now,0)
        return {'status':'updated'}

    @router.post('/api/admin/users/{target}/enroll')
    def enroll(target:int,user=Depends(admin)):
        with transaction() as (cur,data,now):
            cur.execute('SELECT id,username FROM operators WHERE id=%s AND enabled=TRUE',(target,))
            target_user=cur.fetchone()
            if not target_user: raise HTTPException(404,'Compte introuvable ou desactive.')
            if now-data.get('agent_seen',0)>=10:
                raise HTTPException(503,'Agent camera hors ligne.')
            f=new_flow(data,now,target_user['username'],'enroll',target)
            return {'status':'camera','username':f['username']}

    @router.post('/api/admin/users/{target}/revoke-face')
    def revoke_face(target:int,user=Depends(admin)):
        if target==user['id']: raise HTTPException(409,'Utilisez un autre administrateur pour revoquer votre visage.')
        with transaction() as (cur,data,now):
            cur.execute('UPDATE operators SET face_features=NULL WHERE id=%s RETURNING id',(target,))
            if not cur.fetchone(): raise HTTPException(404,'Compte introuvable.')
            cur.execute('DELETE FROM sessions WHERE operator_id=%s',(target,))
            if (data.get('flow') or {}).get('user_id')==target:
                data['flow']=None
                led(data,'off',now,0)
        return {'status':'revoked'}

    return router
