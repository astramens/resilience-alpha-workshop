"""Read-only checks through Grafana's authenticated datasource proxy; no secret is printed."""
import base64,getpass,json,time
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError,URLError

BASE='http://localhost:3001'
def get(path,authorization):
    req=Request(BASE+path,headers={'Authorization':authorization})
    with urlopen(req,timeout=5) as r:return json.load(r)
def query(expression,authorization):
    result=get('/api/datasources/proxy/uid/rearm-prometheus/api/v1/query?'+urlencode({'query':expression}),authorization)
    if result.get('status')!='success':raise ValueError('Requête Prometheus refusée.')
    return result['data']['result']

def run():
    password=getpass.getpass('Mot de passe Grafana pour superviseur (saisie masquée) : ')
    authorization='Basic '+base64.b64encode(('superviseur:'+password).encode()).decode()
    deadline=time.monotonic()+60;last=''
    while True:
        try:
            health=get('/api/health',authorization)
            dashboard=get('/api/dashboards/uid/rearm-availability',authorization)
            results=query('probe_success{job=~"rearm_http|rearm_public"}',authorization)
            collects=query('up',authorization)
            expected={'API et base','Authentification','Service de remédiation','Boutique via WAF'}
            probes={item['metric'].get('service'):item['value'][1] for item in results}
            all_up=len(collects)>=8 and all(item['value'][1]=='1' for item in collects)
            if health.get('database')=='ok' and dashboard.get('dashboard',{}).get('uid')=='rearm-availability' and expected<=probes.keys() and all(probes[name]=='1' for name in expected) and all_up:
                for name in sorted(expected):print('OK : '+name+' — sonde HTTP réussie')
                print('OK : collecte Prometheus et tableau de bord Grafana')
                print('RECETTE SUPERVISION OK. Aucune réparation ni transaction exécutée.')
                return
            last='Sondes et collectes attendues encore incomplètes.'
        except HTTPError as exc:
            if exc.code==401:raise SystemExit('Identifiants Grafana refusés. Aucun secret affiché ; vérifiez le mot de passe choisi.')
            last='HTTP '+str(exc.code)
        except (URLError,TimeoutError,OSError,ValueError,KeyError) as exc:last=type(exc).__name__
        if time.monotonic()>=deadline:raise SystemExit('Supervision incomplète après attente : '+last+'. Consulter docker compose logs --tail=30 prometheus blackbox grafana.')
        print('Attente des premières mesures…',flush=True);time.sleep(3)
if __name__=='__main__':run()
