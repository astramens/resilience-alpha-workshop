"""Minimal Docker API allow-list for a single Compose project's backend.
Only this small trusted process mounts the Docker socket. Never expose its port.
"""
import http.client,json,os,re,socket
from urllib.parse import urlencode
from fastapi import FastAPI,HTTPException,Request,Response

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
PROJECT=os.environ['COMPOSE_PROJECT']
class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(45)
        self.sock.connect('/var/run/docker.sock')

def docker(method,path):
    conn=UnixConnection('localhost',timeout=45)
    try:
        conn.request(method,path,body=b'' if method=='POST' else None)
        r=conn.getresponse();body=r.read()
        if r.status>=400:raise HTTPException(503,'Docker operation failed')
        return r.status,json.loads(body) if body else None
    except (OSError,http.client.HTTPException,ValueError):
        raise HTTPException(503,'Docker unavailable')
    finally:conn.close()

def allowed(labels):
    return labels.get('com.docker.compose.project')==PROJECT and labels.get('com.docker.compose.service')=='backend'

def inspect(cid):
    _,data=docker('GET','/containers/'+cid+'/json')
    if not allowed(data.get('Config',{}).get('Labels') or {}):raise HTTPException(403,'Target is outside the recovery scope')
    data.get('Config',{}).pop('Env',None)
    return data

@app.api_route('/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
def proxy(path:str,request:Request):
    route=re.sub(r'^v[0-9.]+/','',path)
    if request.method=='GET' and route in ('version','_ping'):
        if route=='_ping':return Response('OK')
        _,data=docker('GET','/version');return data
    if request.method=='GET' and route=='containers/json':
        filters=json.dumps({'label':['com.docker.compose.project='+PROJECT,'com.docker.compose.service=backend']})
        _,data=docker('GET','/containers/json?'+urlencode({'all':'1','filters':filters}))
        return [c for c in data if allowed(c.get('Labels') or {})]
    match=re.fullmatch(r'containers/([a-f0-9]{12,64})/(json|restart)',route)
    if not match:raise HTTPException(403,'Docker API operation denied')
    cid,action=match.groups()
    if request.method=='GET' and action=='json':return inspect(cid)
    if request.method=='POST' and action=='restart':
        inspect(cid)
        docker('POST','/containers/'+cid+'/restart?t=10')
        print(json.dumps({'event':'scoped_backend_restart','container_id':cid}),flush=True)
        return Response(status_code=204)
    raise HTTPException(403,'Docker API operation denied')
