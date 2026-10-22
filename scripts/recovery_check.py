"""Read-only private-route checks; the rollback readiness probe leaves no writes."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=r'''
import json,os,urllib.request,urllib.error
base='http://127.0.0.1:8000'
headers={'Authorization':'Bearer '+os.environ['REMEDIATION_TOKEN']}
def get(path,authorized=True):
 with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers if authorized else {}),timeout=5) as r:return json.load(r)
try:
 get('/internal/business-probe',False)
 raise SystemExit('ECHEC : route interne accessible sans autorisation.')
except urllib.error.HTTPError as e:
 if e.code!=401:raise SystemExit('ECHEC : route interne absente ou indisponible (HTTP '+str(e.code)+').')
probe=get('/internal/business-probe')
if probe.get('transactional_readiness_verified') is not True or probe.get('business_recovery_verified') is not False:
 raise SystemExit('ECHEC : preuve technique incoherente.')
print(json.dumps({'probe':probe,'ledger':get('/internal/recovery-status')}))
'''

def private_status():
    result=subprocess.run(['docker','compose','exec','-T','backend','python','-c',PRIVATE],cwd=ROOT,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Contrôle interne impossible. Vérifier migration et reconstruction backend/remediation/ai-engine. Aucun secret à partager.')
    return json.loads(result.stdout)

def observation():
    result=subprocess.run(['docker','compose','logs','--no-log-prefix','--since=1m','--tail=30','ai-engine'],cwd=ROOT,capture_output=True,text=True)
    values=[]
    for line in result.stdout.splitlines():
        try:value=json.loads(line[line.find('{'):])
        except (ValueError,TypeError):continue
        if isinstance(value,dict) and value.get('event')=='observation':values.append(value)
    return values[-1] if values else {}

if __name__=='__main__':
    try:
        data=private_status();last=observation()
        print('OK : route interne protégée ; catalogue lisible ; écriture de contrôle annulée')
        print('OK : registre de reprise accessible')
        print('Détecteur :', 'calibré et backend sain' if last.get('ml_ready') is True and last.get('healthy') is True else 'attendre la calibration et vérifier les dernières observations')
        rows=data['ledger']['incidents']
        for row in rows[:10]:
            proof='RA-'+str(row['proof_order_id']).zfill(5) if row.get('proof_order_id') else 'aucune commande payée de preuve'
            print(row['ref'],':',row['state'],'—',proof)
        if not rows:print('Aucune tentative de reprise enregistrée : normal avant la recette de panne.')
        print('CONTRÔLE RACCORDÉ. Ce contrôle ne prouve pas à lui seul une reprise après panne ni un paiement.')
    except (OSError,ValueError,KeyError,RuntimeError):
        print('ÉCHEC du contrôle : vérifier les services et les tables de reprise.');sys.exit(1)
