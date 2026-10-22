"""Read internal Prometheus observations for the existing staff panel. No repair actions."""
import json
from urllib.parse import urlencode
from urllib.request import urlopen

def snapshot():
    expression='(probe_success{job=~"rearm_http|rearm_public"} and on(job,instance) (up{job=~"rearm_http|rearm_public"} == 1)) or up{job=~"prometheus|grafana"}'
    expected=['Boutique via WAF','API et base','Authentification','Service de remédiation','Prometheus','Grafana']
    try:
        url='http://prometheus:9090/api/v1/query?'+urlencode({'query':expression})
        with urlopen(url,timeout=1.5) as response:data=json.load(response)
        if data.get('status')!='success':raise ValueError()
        observations={}
        for row in data['data']['result']:
            metric=row['metric'];name=metric.get('service') or {'prometheus':'Prometheus','grafana':'Grafana'}.get(metric.get('job'))
            if name in expected:observations[name]=float(row['value'][1])==1.0
    except (OSError,ValueError,KeyError,TypeError,AttributeError):observations={}
    services=[{'name':name,'healthy':observations.get(name,False),'observed':name in observations} for name in expected]
    return {'services':services,'available':observations.get('Prometheus',False),'waf_observed':observations.get('Boutique via WAF',False),'grafana_observed':observations.get('Grafana',False)}
