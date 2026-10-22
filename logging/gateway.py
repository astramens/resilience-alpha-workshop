"""Trusted socket boundary: fixed read operations only; no transparent Docker proxy."""
import hashlib, http.client, json, os, socket, struct, time, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode
from datetime import datetime
from sanitize import SERVICES, sanitize
PROJECT=os.environ['COMPOSE_PROJECT']
MAX_BYTES=2*1024*1024
class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect('/var/run/docker.sock')
def docker_get(path):
    conn=UnixConnection('localhost',timeout=3)
    try:
        conn.request('GET',path)
        response=conn.getresponse();body=response.read(MAX_BYTES+1)
        if response.status!=200 or len(body)>MAX_BYTES: raise ValueError('Docker read failed or exceeded bound')
        return body
    finally: conn.close()
def frames(body):
    # Non-TTY Docker multiplex framing. TTY streams are intentionally unsupported.
    while body:
        if len(body)<8 or body[0] not in (1,2) or body[1:4]!=b'\0\0\0': raise ValueError('Invalid stream')
        size=struct.unpack('>I',body[4:8])[0]
        if len(body)<8+size: raise ValueError('Truncated stream')
        yield body[8:8+size];body=body[8+size:]
def timestamp_ns(value):
    match=re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z',value)
    if not match: raise ValueError('Invalid timestamp')
    epoch=int(datetime.fromisoformat(match[1]+'+00:00').timestamp())
    return str(epoch*1_000_000_000+int((match[2] or '').ljust(9,'0')))
def snapshot():
    filters=json.dumps({'label':['com.docker.compose.project='+PROJECT]})
    containers=json.loads(docker_get('/containers/json?'+urlencode({'all':'1','filters':filters})))
    events=[];observed=set();failed=[];now=int(time.time())
    for container in containers[:100]:
        labels=container.get('Labels') or {};service=labels.get('com.docker.compose.service')
        cid=container.get('Id','')
        if labels.get('com.docker.compose.project')!=PROJECT or service not in SERVICES or not re.fullmatch('[a-f0-9]{64}',cid):continue
        try:
            body=docker_get('/containers/'+cid+'/logs?'+urlencode({'stdout':'1','stderr':'1','timestamps':'1','since':str(now-60),'tail':'1000','follow':'0'}))
            # Join frames before splitting: a frame need not be a complete log line.
            for line in b''.join(frames(body)).decode('utf-8','replace').splitlines():
                stamp,sep,message=line.partition(' ')
                if not sep: continue
                try: ns=timestamp_ns(stamp)
                except ValueError: continue
                safe=sanitize(service,message)
                if safe is None:continue
                payload=json.dumps(safe,sort_keys=True,separators=(',',':'))
                ident=hashlib.sha256((cid+stamp+payload).encode()).hexdigest()
                events.append({'id':ident,'service':service,'timestamp':ns,'data':safe})
            observed.add(service)
        except (OSError,ValueError,http.client.HTTPException):failed.append(service)
    return {'events':events,'observed':sorted(observed),'failed':sorted(set(failed)),
            'missing':sorted(SERVICES-observed-set(failed)),'window_seconds':60,'tail_limit':1000}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,body):
        data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/health':return self.reply(200,{'status':'ok'})
        if self.path!='/snapshot':return self.reply(403,{'error':'denied'})
        try:self.reply(200,snapshot())
        except (OSError,ValueError,http.client.HTTPException):self.reply(503,{'error':'log source unavailable'})
    def do_POST(self):self.reply(403,{'error':'denied'})
    do_PUT=do_POST;do_DELETE=do_POST;do_PATCH=do_POST
if __name__=='__main__':HTTPServer(('0.0.0.0',9080),Handler).serve_forever()
