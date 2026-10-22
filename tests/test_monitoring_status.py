from pathlib import Path
import importlib.util,json
from io import BytesIO
spec=importlib.util.spec_from_file_location('monitoring_status',Path(__file__).resolve().parents[1]/'backend/monitoring_status.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_absence_of_collector_is_never_green(monkeypatch):
    def unavailable(*a,**k):raise OSError('offline')
    monkeypatch.setattr(module,'urlopen',unavailable);data=module.snapshot()
    assert not data['available'] and not data['waf_observed']
    assert all(not s['healthy'] and not s['observed'] for s in data['services'])

def test_prometheus_values_drive_the_panel(monkeypatch):
    data={'status':'success','data':{'result':[{'metric':{'service':'Boutique via WAF'},'value':[1,'1']},{'metric':{'service':'Authentification'},'value':[1,'0']},{'metric':{'job':'prometheus'},'value':[1,'1']},{'metric':{'job':'grafana'},'value':[1,'1']}]}}
    monkeypatch.setattr(module,'urlopen',lambda *a,**k:BytesIO(json.dumps(data).encode()))
    result=module.snapshot();assert result['available'] and result['waf_observed'] and result['grafana_observed']
    auth=next(s for s in result['services'] if s['name']=='Authentification');assert auth['observed'] and not auth['healthy']
    unknown=next(s for s in result['services'] if s['name']=='API et base');assert not unknown['observed'] and not unknown['healthy']
