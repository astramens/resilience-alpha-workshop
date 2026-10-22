import importlib.util,json,os,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest,requests
from fastapi import HTTPException
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
os.environ.setdefault('REMEDIATION_TOKEN','test-only-recovery-token-'+'a'*40);os.environ.setdefault('COMPOSE_PROJECT','test')
sys.path.insert(0,str(ROOT/'remediation'))
det=load('recovery_detector','ai-engine/detector.py');rem=load('recovery_remediator','remediation/remediator.py')
class Response:
 def __init__(self,data=None,status=200):self.data=data or {};self.status_code=status;self.ok=status<400
 def json(self):return self.data
 def raise_for_status(self):
  if not self.ok:raise requests.HTTPError('test response error')
class Session:
 def __init__(self,result=None,offline=False,reject=0):self.calls=[];self.result=result or {};self.offline=offline;self.reject=reject
 def post(self,url,**kw):
  self.calls.append((url,kw))
  if url.endswith('/internal/incidents'):
   if self.offline:raise requests.ConnectionError()
   return Response(status=self.reject or 200)
  if url.endswith('/internal/recovery/reconcile'):return Response(self.result)
  return Response(self.result)

def observation():return {'recovery_reason':'ml_anomaly_with_confirmed_health_failure','healthy':False,'health_failures':3}

def test_legacy_business_claim_from_remediator_is_never_accepted():
 d=det.Detector();s=Session({'business_recovery_verified':True,'status':'business_restored'})
 assert d.dispatch(observation(),s,'PRIVATE_TOKEN',now=200) is False
 reports=[kw['json'] for url,kw in s.calls if url.endswith('/internal/incidents')]
 assert reports[-1]['status']=='echec' and reports[-1]['business_verified'] is False

def test_technical_restoration_waits_for_real_business_proof():
 d=det.Detector();s=Session({'technical_recovery_verified':True,'business_recovery_verified':False})
 assert d.dispatch(observation(),s,'PRIVATE_TOKEN',now=200) is True
 reports=[kw['json'] for url,kw in s.calls if url.endswith('/internal/incidents')]
 assert reports[-1]['status']=='attente_metier' and reports[-1]['business_verified'] is False
 assert len([url for url,kw in s.calls if url.endswith('/alerts')])==1
 assert d.dispatch(observation(),s,'PRIVATE_TOKEN',now=210) is False
 assert len([url for url,kw in s.calls if url.endswith('/alerts')])==1

def test_pending_reports_survive_restart_without_storing_token(tmp_path):
 p=tmp_path/'pending.json';d=det.Detector(p);s=Session(offline=True)
 incident={'ref':'INC-0123456789ab','status':'remediation','reason':'ml_anomaly_with_confirmed_health_failure'}
 d.report(s,'PRIVATE_TOKEN',incident)
 assert 'PRIVATE_TOKEN' not in p.read_text()
 restarted=det.Detector(p);assert restarted.pending[incident['ref']]==incident
 restarted.flush(Session(),'NEW_PRIVATE_TOKEN');assert json.loads(p.read_text())=={}

def test_rejected_report_is_not_silently_discarded(tmp_path):
 d=det.Detector(tmp_path/'p.json');incident={'ref':'INC-0123456789ab','status':'remediation'}
 d.report(Session(reject=401),'PRIVATE',incident)
 assert d.pending[incident['ref']]==incident

def test_only_server_confirmed_business_status_is_logged(monkeypatch):
 records=[];monkeypatch.setattr(det,'log',lambda event,**fields:records.append((event,fields)))
 d=det.Detector();s=Session({'incidents':[{'ref':'INC-0123456789ab','state':'technical_recovered','business_recovery_verified':False}]})
 d.reconcile(s,'PRIVATE');assert not records
 s.result={'incidents':[{'ref':'INC-0123456789ab','state':'business_verified','business_recovery_verified':True}]}
 d.reconcile(s,'PRIVATE');d.reconcile(s,'PRIVATE')
 assert len(records)==1 and records[0][0]=='recovery_business_verified'

def test_healthy_ml_anomaly_is_observation_only():
 d=det.Detector();d.ready=True;d.model=SimpleNamespace(predict=lambda sample:[-1])
 assert d.observe(True,40,0)['recovery_reason'] is None
 for i in range(2):assert d.observe(False,5000,None)['recovery_reason'] is None
 assert d.observe(False,5000,None)['recovery_reason']=='ml_anomaly_with_confirmed_health_failure'
 assert d.observe(True,40,0)['health_failures']==0

def test_availability_fallback_requires_six_failed_probes():
 d=det.Detector();d.ready=True;d.model=SimpleNamespace(predict=lambda sample:[1])
 for i in range(5):assert d.observe(False,20,None)['recovery_reason'] is None
 assert d.observe(False,20,None)['recovery_reason']=='availability_fallback_six_failed_health_probes'

def setup_remediator(monkeypatch,probe):
 container=Mock();monkeypatch.setattr(rem,'TOKEN','PRIVATE');monkeypatch.setattr(rem,'last_restart',0)
 counter=[200]
 def clock():counter[0]+=5;return counter[0]
 monkeypatch.setattr(rem,'time',SimpleNamespace(monotonic=clock,time=clock,sleep=lambda _:None))
 monkeypatch.setattr(rem,'run_playbook',container.restart)
 container.restart.return_value={'executor':'ansible','check_mode':False,'playbook_success':True}
 calls=[]
 def get(url,**kw):
  calls.append((url,kw));return Response(probe if url.endswith('/internal/business-probe') else {})
 monkeypatch.setattr(rem.requests,'get',get)
 return container,calls

def test_remediator_probe_200_is_insufficient(monkeypatch):
 container,calls=setup_remediator(monkeypatch,{'status':'ok'})
 result=rem.remediate(rem.Alert(reason='test'),authorization='Bearer PRIVATE')
 assert result['status']=='health_restored' and result['technical_recovery_verified'] is False and result['business_recovery_verified'] is False
 assert container.restart.call_count==1

def test_remediator_authenticated_readiness_only_confirms_technical(monkeypatch):
 probe={'scope':'catalogue_and_rollback_write','transactional_readiness_verified':True,'writes_rolled_back':True,'business_recovery_verified':False}
 container,calls=setup_remediator(monkeypatch,probe)
 result=rem.remediate(rem.Alert(reason='test'),authorization='Bearer PRIVATE')
 assert result['technical_recovery_verified'] is True and result['business_recovery_verified'] is False
 assert any(url.endswith('/internal/business-probe') and kw.get('headers',{}).get('Authorization')=='Bearer PRIVATE' for url,kw in calls)

def test_remediator_rejects_wrong_token_before_docker(monkeypatch):
 container,calls=setup_remediator(monkeypatch,{})
 with pytest.raises(HTTPException) as e:rem.remediate(rem.Alert(reason='test'),authorization='wrong')
 assert e.value.status_code==401 and not container.restart.called and not calls

def test_invalid_offline_state_stops_without_overwriting(tmp_path):
 p=tmp_path/'pending.json';p.write_text('not json')
 with pytest.raises(RuntimeError):det.Detector(p)
 assert p.read_text()=='not json'
