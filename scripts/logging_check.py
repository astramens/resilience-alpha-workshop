"""Read-only Grafana/Loki check with a real benign HTTP request through the WAF."""
import base64,getpass,json,time,urllib.request,urllib.parse,urllib.error
password=getpass.getpass('Mot de passe Grafana pour superviseur (saisie masquée) : ')
auth=base64.b64encode(('superviseur:'+password).encode()).decode()
base='http://localhost:3001'
def get(path):
    req=urllib.request.Request(base+path,headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def query(expression):
    args=urllib.parse.urlencode({'query':expression,'start':str(time.time_ns()-120_000_000_000),'end':str(time.time_ns()),'limit':100,'direction':'backward'})
    return get('/api/datasources/proxy/uid/rearm-loki/loki/api/v1/query_range?'+args)['data']['result']
try:
    get('/api/dashboards/uid/rearm-security-logs')
    print('OK : tableau de bord des journaux')
    # Do not create orders or intentionally trigger an attack.
    with urllib.request.urlopen('http://localhost:3000/api/shop/products',timeout=15) as response:
        if response.status!=200:raise RuntimeError('Catalogue indisponible')
    started=time.time_ns();deadline=time.monotonic()+75
    while True:
        heartbeat=query('{job="rearm_logs",event="collection_status"}')
        waf=query('{job="rearm_logs",service="waf",event="http_request"} | json | route="/api/shop/products" | status=200')
        fresh=[json.loads(line) for stream in heartbeat for stamp,line in stream['values'] if int(stamp)>=started-20_000_000_000]
        success=any(not x['missing'] and not x['failed'] and len(x['observed'])==8 for x in fresh)
        catalogue=any(int(stamp)>=started-5_000_000_000 for stream in waf for stamp,line in stream['values'])
        if success and catalogue:break
        if time.monotonic()>=deadline:raise RuntimeError('Collecte incomplète : vérifier les journaux du collecteur et la disponibilité des 8 services.')
        time.sleep(5)
    print('OK : Loki interrogé via Grafana ; battement récent et 8 sources lisibles')
    print('OK : requête réelle au catalogue retrouvée dans les événements WAF filtrés')
    print('RECETTE JOURNAUX OK. Aucune commande ni réparation exécutée.')
except urllib.error.HTTPError as exc:
    print('ÉCHEC : HTTP',exc.code,'— vérifier le mot de passe Grafana ou le démarrage de Loki.');raise SystemExit(1)
except (urllib.error.URLError,TimeoutError,RuntimeError,ValueError,KeyError) as exc:
    print('ÉCHEC :',str(exc));raise SystemExit(1)
