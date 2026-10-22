"""Explicit bounded backend outage; safety fallback is never counted as autonomous recovery."""
import json,subprocess,sys,time,urllib.request,urllib.error
from recovery_check import ROOT,private_status,observation

if '--stop-backend' not in sys.argv:
    raise SystemExit('Cette recette arrête temporairement le backend. Commande explicite : python scripts/recovery_demo.py --stop-backend')

def catalogue_ok():
    try:
        with urllib.request.urlopen('http://localhost:3000/api/shop/products',timeout=2) as response:
            data=json.load(response)
            return response.status==200 and isinstance(data,list) and bool(data)
    except (OSError,ValueError):return False

stopped=False;success=False
try:
    before=private_status();last=observation()
    running=subprocess.run(['docker','compose','ps','--status','running','-q','ai-engine','remediation','docker-guard'],cwd=ROOT,capture_output=True,text=True)
    if running.returncode or len(running.stdout.strip().splitlines())!=3:
        raise RuntimeError('Détecteur, remédiation et docker-guard doivent tous être démarrés.')
    if any(r['state'] in ('remediation','technical_recovered') for r in before['ledger']['incidents']):
        raise RuntimeError('Une reprise attend déjà sa validation : terminer sa preuve métier avant un nouveau test.')
    if last.get('healthy') is not True or last.get('ml_ready') is not True:
        raise RuntimeError('Attendre la calibration du détecteur (20 observations saines, environ 3 à 4 minutes après son démarrage).')
    if not catalogue_ok():raise RuntimeError('Catalogue déjà indisponible : ne pas provoquer une nouvelle panne.')
    prior={r['ref'] for r in before['ledger']['incidents']}
    print('TEST : arrêt temporaire du backend uniquement. Ne passez pas de commande pendant la panne.',flush=True)
    start=time.monotonic();stopped=True
    result=subprocess.run(['docker','compose','stop','--timeout','5','backend'],cwd=ROOT)
    if result.returncode:raise RuntimeError('Arrêt du backend non confirmé.')
    deadline=start+120;last_print=0
    while time.monotonic()<deadline:
        if catalogue_ok():
            try:rows=private_status()['ledger']['incidents']
            except (OSError,ValueError,KeyError,RuntimeError):rows=[]
            found=[r for r in rows if r['ref'] not in prior and r['state'] in ('technical_recovered','business_verified')]
            if found:
                elapsed=time.monotonic()-start;success=True
                print('OK : catalogue revenu et reprise technique enregistrée automatiquement.',flush=True)
                print('Incident :',found[0]['ref'],'; délai observé :',round(elapsed,1),'secondes.',flush=True)
                print('Objectif technique inférieur à 60 s :','respecté' if elapsed<60 else 'non respecté pour cette exécution',flush=True)
                print('ÉTAPE TECHNIQUE VALIDÉE. Créez maintenant une NOUVELLE commande Stripe de test et payez-la pour la preuve métier.',flush=True)
                print('Le registre doit ensuite passer à business_verified avec le numéro de cette nouvelle commande. Aucun paiement n’a été automatisé par cette recette.')
                break
        if time.monotonic()-last_print>=15:
            print('Attente de la récupération automatique...',flush=True);last_print=time.monotonic()
        time.sleep(3)
    if not success:raise RuntimeError('Pas de reprise technique confirmée dans les 120 secondes.')
except (OSError,ValueError,KeyError,RuntimeError,KeyboardInterrupt) as exc:
    print('RECETTE NON VALIDÉE :',str(exc),flush=True)
finally:
    if stopped and not success:
        print('SECOURS : remise en route commandée par le script. Ce secours ne compte PAS comme une récupération autonome.',flush=True)
        subprocess.run(['docker','compose','up','-d','--no-deps','backend'],cwd=ROOT)
if not success:raise SystemExit(1)
