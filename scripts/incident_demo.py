"""Six bounded inert WAF requests, then verify opening AND resolution. Lab only."""
import base64,getpass,json,time,urllib.parse,urllib.request,urllib.error
base=input('URL du laboratoire REARM [http://localhost:3000] : ').strip().rstrip('/') or 'http://localhost:3000'
if not base.startswith(('http://','https://')):raise SystemExit('URL HTTP(S) requise.')
password=getpass.getpass('Mot de passe Grafana superviseur (saisie masquée) : ')
auth=base64.b64encode(('superviseur:'+password).encode()).decode()
def active():
    expr='rearm_incident_active{rule="waf_burst"}'
    url='http://localhost:3001/api/datasources/proxy/uid/rearm-prometheus/api/v1/query?'+urllib.parse.urlencode({'query':expr})
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Basic '+auth}),timeout=15) as r:data=json.load(r)
    rows=data['data']['result']
    if len(rows)!=1:raise RuntimeError('Moteur non encore collecté.')
    return float(rows[0]['value'][1])
def wait_for(value,seconds,label):
    deadline=time.monotonic()+seconds;last=0
    while True:
        if active()==value:return
        if time.monotonic()>=deadline:raise RuntimeError('Délai dépassé : '+label+'. Consulter le tableau et ne pas relancer immédiatement les requêtes.')
        if time.monotonic()-last>=15:print(label+'...',flush=True);last=time.monotonic()
        time.sleep(3)
try:
    if active()!=0:raise RuntimeError('Un incident WAF est déjà ouvert. Attendre son retour à la normale avant cette recette.')
    with urllib.request.urlopen(base+'/api/shop/products',timeout=15) as r:
        if r.status!=200:raise RuntimeError('Catalogue indisponible.')
    payload=urllib.parse.urlencode({'rearm_probe':'<script>alert(1)</script>'})
    for _ in range(6):
        try:
            with urllib.request.urlopen(base+'/api/shop/products?'+payload,timeout=15) as r:status=r.status
        except urllib.error.HTTPError as exc:status=exc.code
        if status!=403:raise RuntimeError('La requête inerte n’a pas été bloquée par le WAF : HTTP '+str(status))
        time.sleep(0.2)
    print('OK : six requêtes inertes refusées ; aucune exécution de script ni commande métier.',flush=True)
    wait_for(1,90,'Attente de l’ouverture de l’incident WAF')
    print('OK : incident WAF ouvert après confirmation. Aucune réparation demandée.',flush=True)
    print('Ne relancez pas les requêtes : attente de la fin de la fenêtre d’une minute.',flush=True)
    wait_for(0,150,'Attente de la résolution observée')
    print('RECETTE CORRÉLATION OK : ouverture puis résolution du signal WAF. Aucune réparation ni transaction exécutée.')
except urllib.error.HTTPError as exc:
    print('ÉCHEC : HTTP',exc.code,'— vérifier Grafana ou le laboratoire.');raise SystemExit(1)
except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
    print('ÉCHEC :',str(exc));raise SystemExit(1)
