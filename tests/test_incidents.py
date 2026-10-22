import importlib.util,json,math,sys,time,threading,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('incident_engine',ROOT/'incident-engine/engine.py');eng=importlib.util.module_from_spec(spec);spec.loader.exec_module(eng)

def test_two_confirmations_and_no_repeated_incidents(tmp_path):
 s=eng.Store(tmp_path/'state.db')
 s.transition('waf_burst',True,{'waf_burst':6},100);assert s.active('waf_burst') is None
 s.transition('waf_burst',True,{'waf_burst':6},115);assert s.active('waf_burst') is not None
 s.transition('waf_burst',True,{},130);assert s.db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]==1
 s.transition('waf_burst',False,{},145);assert s.active('waf_burst') is not None
 s.transition('waf_burst',False,{},160);assert s.active('waf_burst') is None
 assert s.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==2

def test_unknown_never_resolves_and_breaks_streak(tmp_path):
 s=eng.Store(tmp_path/'state.db')
 for t in (100,115):s.transition('backend_down',True,{},t)
 s.transition('backend_down',False,{},130);s.transition('backend_down',None,{},145)
 s.transition('backend_down',False,{},160);assert s.active('backend_down') is not None
 s.transition('backend_down',False,{},175);assert s.active('backend_down') is None

def test_persistence_after_restart_and_reopen(tmp_path):
 p=tmp_path/'state.db';s=eng.Store(p)
 for t in (100,115):s.transition('auth_down',True,{},t)
 ident=s.active('auth_down')[0];s.db.close();s=eng.Store(p)
 assert s.active('auth_down')[0]==ident
 for t in (130,145):s.transition('auth_down',False,{},t)
 for t in (160,175):s.transition('auth_down',True,{},t)
 assert s.active('auth_down')[0]!=ident
 assert s.db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]==2

def test_probe_scrape_failure_is_unknown_not_service_failure():
 key=next(iter(eng.PROBES));labels={'job':key[0],'instance':key[1]}
 rows=[{'metric':dict(labels,__name__='up'),'value':[1,'0']},{'metric':dict(labels,__name__='probe_success'),'value':[1,'0']}]
 assert eng.probe_values(rows)['backend_down'] is None
 rows[0]['value'][1]='1'
 assert eng.probe_values(rows)['backend_down'] is True
 rows[1]['value'][1]='1'
 assert eng.probe_values(rows)['backend_down'] is False

def heartbeat(now,**changes):
 d={'event':'collection_status','observed':sorted(eng.SERVICES),'failed':[],'missing':[]};d.update(changes)
 return {'resultType':'streams','result':[{'values':[[str(int(now*1e9)),json.dumps(d)]]}]}

def test_heartbeat_requires_fresh_complete_eight_sources():
 assert eng.logs_complete(heartbeat(100),120)
 assert not eng.logs_complete(heartbeat(100),146)
 assert not eng.logs_complete(heartbeat(100),99)
 assert not eng.logs_complete(heartbeat(100,failed=['auth']),120)
 assert not eng.logs_complete(heartbeat(100,observed=['auth']),120)

def test_counts_empty_is_zero_but_malformed_is_not_zero():
 assert eng.scalar_count({'resultType':'vector','result':[]})==0
 for value in ['NaN','Infinity','-1']:
  with pytest.raises(ValueError):eng.scalar_count({'resultType':'vector','result':[{'value':[1,value]}]})
 with pytest.raises(ValueError):eng.scalar_count({'resultType':'streams','result':[]})

def test_observe_no_complete_logs_keeps_security_unknown():
 with patch.object(eng,'prom',return_value=[]),patch.object(eng,'loki',side_effect=OSError):v,e=eng.observe()
 assert v['monitoring_gap'] is True and v['logging_gap'] is True
 assert all(v[x] is None for x in eng.COUNTS)

def test_threshold_hysteresis_no_double_count_across_services():
 for number,expected in ((6,True),(3,None),(1,False)):
  expressions=[]
  def loki(expr,range_query=False):
   expressions.append(expr)
   if range_query:return heartbeat(time.time())
   return {'resultType':'vector','result':[{'value':[time.time(),str(number)]}]}
  with patch.object(eng,'prom',return_value=[]),patch.object(eng,'loki',loki):v,e=eng.observe()
  assert v['waf_burst'] is expected
  assert all('service="waf"' in x for x in expressions[1:])

def test_failed_loki_keeps_outbox(tmp_path):
 s=eng.Store(tmp_path/'s.db');now=time.time()
 for t in (now-15,now):s.transition('logging_gap',True,{},t)
 with patch.object(eng,'fetch',side_effect=OSError):
  with pytest.raises(OSError):s.flush()
 assert s.db.execute('SELECT sent FROM outbox').fetchone()[0]==0
 with patch.object(eng,'fetch',return_value=None):s.flush()
 assert s.db.execute('SELECT sent FROM outbox').fetchone()[0]==1

def test_old_outbox_explicitly_expired_and_open_state_preserved(tmp_path):
 s=eng.Store(tmp_path/'s.db')
 for t in (time.time()-8000,time.time()-7985):s.transition('logging_gap',True,{},t)
 with patch.object(eng,'fetch') as call:s.flush();call.assert_not_called()
 assert s.db.execute('SELECT sent FROM outbox').fetchone()[0]==2
 assert s.active('logging_gap') is not None

def test_metrics_fixed_labels_and_no_repair(tmp_path):
 s=eng.Store(tmp_path/'s.db');s.cycle({rule:False for rule in eng.RULES},{},time.time())
 text=s.metrics();assert text.count('rearm_incident_active{')==10
 assert 'rearm_incident_engine_last_cycle_seconds' in text
 with pytest.raises(ValueError):s.transition('SECRET',True,{},100)
 source=(ROOT/'incident-engine/engine.py').read_text()
 assert 'docker.sock' not in source and '/alerts' not in source and 'subprocess' not in source
 assert 'repair_executed' in source

def test_network_and_no_secrets():
 c=yaml.safe_load((ROOT/'docker-compose.yml').read_text());s=c['services']['incident-engine']
 assert set(s['networks'])=={'observability','log_store'}
 assert s['cap_drop']==['ALL'] and s['read_only'] is True
 assert 'ports' not in s and 'environment' not in s
 assert all('docker.sock' not in v for v in s['volumes'])
 assert c['services']['grafana']['ports']==['127.0.0.1:3001:3000']
 assert 'grafana_access' in c['services']['grafana']['networks']
 assert 'rearm_incidents_v1' in c['volumes']

def test_prom_query_keeps_probe_and_scrape_series_distinct():
 captured=[]
 def fetch(url,data=None):
  captured.append(url);return {'status':'success','data':{'resultType':'vector','result':[]}}
 with patch.object(eng,'fetch',fetch):assert eng.prom()==[]
 from urllib.parse import parse_qs,urlsplit
 expr=parse_qs(urlsplit(captured[0]).query)['query'][0]
 assert 'or on(__name__,job,instance)' in expr
 assert expr.count('time()-45')==2
