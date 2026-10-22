"""Read-only check through authenticated Grafana; no attack or remediation."""
import base64,getpass,json,time,urllib.parse,urllib.request,urllib.error,math
password=getpass.getpass('Mot de passe Grafana pour superviseur (saisie masquée) : ')
auth=base64.b64encode(('superviseur:'+password).encode()).decode()
def get(path):
    req=urllib.request.Request('http://localhost:3001'+path,headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
def query(expr):
    data=get('/api/datasources/proxy/uid/rearm-prometheus/api/v1/query?'+urllib.parse.urlencode({'query':expr}))
    if data.get('status')!='success':raise ValueError('Prometheus indisponible')
    return data['data']['result']
def number(expr):
    rows=query(expr)
    if len(rows)!=1:return None
    value=float(rows[0]['value'][1])
    return value if math.isfinite(value) else None
try:
    get('/api/dashboards/uid/rearm-incidents');deadline=time.monotonic()+75
    while True:
        up=number('up{job="rearm_incidents"}')
        age=number('time() - rearm_incident_engine_last_cycle_seconds')
        known=number('sum(rearm_incident_source_known)')
        if up==1 and age is not None and 0<=age<60 and known==10:break
        if time.monotonic()>=deadline:raise RuntimeError('Mesures incomplètes ou seuil intermédiaire : vérifier le tableau Incidents corrélés et les journaux incident-engine.')
        print('Attente des premières observations ou de données complètes...',flush=True);time.sleep(10)
    opened=number('sum(rearm_incident_active)')
    print('OK : tableau Grafana, moteur collecté et cycle récent')
    print('OK : dix règles avec une observation déterminée')
    print('Incidents ouverts :',int(opened) if opened is not None else 'mesure absente')
    print('RECETTE MOTEUR OK. Aucun test d’attaque ni réparation exécuté. La recette des transitions reste distincte.')
except urllib.error.HTTPError as exc:
    print('ÉCHEC : HTTP',exc.code,'— vérifier Grafana ou Prometheus.');raise SystemExit(1)
except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
    print('ÉCHEC :',str(exc));raise SystemExit(1)
