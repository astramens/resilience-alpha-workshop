import importlib.util,os
from pathlib import Path
from fastapi.testclient import TestClient
os.environ['COMPOSE_PROJECT']='resilience-alpha'
spec=importlib.util.spec_from_file_location('docker_guard',Path(__file__).resolve().parents[1]/'docker-guard/guard.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
def test_denies_mutations_and_unrelated_paths():
    c=TestClient(guard.app)
    for method,path in [('POST','/containers/create'),('POST','/containers/'+('a'*64)+'/exec'),('DELETE','/containers/'+('a'*64)),('GET','/images/json'),('GET','/info')]:
        assert c.request(method,path).status_code==403

def test_restart_scope_and_secret_redaction(monkeypatch):
    calls=[]
    def docker(method,path):
        calls.append((method,path))
        if path.endswith('/json'):return 200,{'Config':{'Labels':{'com.docker.compose.project':'resilience-alpha','com.docker.compose.service':'backend'},'Env':['SECRET=hidden']}}
        return 204,None
    monkeypatch.setattr(guard,'docker',docker)
    c=TestClient(guard.app);cid='a'*64
    assert 'Env' not in c.get('/v1.50/containers/'+cid+'/json').json()['Config']
    assert c.post('/v1.50/containers/'+cid+'/restart?t=0').status_code==204
    assert calls[-1]==('POST','/containers/'+cid+'/restart?t=10')
    monkeypatch.setattr(guard,'docker',lambda *a:(200,{'Config':{'Labels':{'com.docker.compose.project':'other','com.docker.compose.service':'backend'}}}))
    assert c.post('/containers/'+cid+'/restart').status_code==403

def test_docker_sdk_can_list_and_restart_only_backend(monkeypatch):
    import docker,requests
    from urllib.parse import urlsplit
    cid='b'*64
    labels={'com.docker.compose.project':'resilience-alpha','com.docker.compose.service':'backend'}
    operations=[]
    def engine(method,path):
        operations.append((method,path))
        if path=='/version':return 200,{'ApiVersion':'1.50','Version':'29.1.3'}
        if path.startswith('/containers/json?'):return 200,[{'Id':cid,'Names':['/resilience-alpha-backend-1'],'Labels':labels}]
        if path.endswith('/json'):return 200,{'Id':cid,'Name':'/resilience-alpha-backend-1','Config':{'Labels':labels,'Env':['PRIVATE=value']},'State':{'Status':'running'}}
        if method=='POST' and path.endswith('/restart?t=10'):return 204,None
        raise AssertionError((method,path))
    monkeypatch.setattr(guard,'docker',engine)
    proxy=TestClient(guard.app)
    def send(adapter,prepared,**kwargs):
        url=urlsplit(prepared.url)
        upstream=proxy.request(prepared.method,url.path+('?' + url.query if url.query else ''),content=prepared.body or b'')
        response=requests.Response();response.status_code=upstream.status_code;response._content=upstream.content;response.headers.update(upstream.headers);response.url=prepared.url;response.request=prepared
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter,'send',send)
    client=docker.DockerClient(base_url='http://guard:2375',version='auto')
    containers=client.containers.list(all=True)
    assert len(containers)==1 and containers[0].name=='resilience-alpha-backend-1'
    containers[0].restart(timeout=10)
    assert operations[-1]==('POST','/containers/'+cid+'/restart?t=10')
