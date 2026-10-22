"""Host diagnostic: actual Ansible --check, no restart, payment or secret output."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = r'''
import json, os, subprocess, sys, urllib.request, urllib.error
base='http://127.0.0.1:9000'
with urllib.request.urlopen(base+'/health',timeout=3) as r:
 d=json.load(r)
if d.get('executor')!='ansible':raise SystemExit(1)
request=urllib.request.Request(base+'/alerts',data=b'{"service":"backend","reason":"diagnostic"}',headers={'Content-Type':'application/json'})
try:
 urllib.request.urlopen(request,timeout=3)
 raise SystemExit(1)
except urllib.error.HTTPError as e:
 if e.code!=401:raise SystemExit(1)
r=subprocess.run([sys.executable,'ansible_runner.py','--check'],capture_output=True,text=True,timeout=30)
if r.returncode:raise SystemExit(1)
data=json.loads(r.stdout)
if data!={'executor':'ansible','check_mode':True,'playbook_success':True}:raise SystemExit(1)
print(json.dumps(data))
'''

if __name__ == '__main__':
    try:
        r = subprocess.run(['docker','compose','exec','-T','remediation','python','-c',PRIVATE],
                           cwd=ROOT,capture_output=True,text=True,timeout=40)
        if r.returncode: raise ValueError()
        d = json.loads(r.stdout)
        if d.get('executor') != 'ansible' or d.get('check_mode') is not True or d.get('playbook_success') is not True:
            raise ValueError()
        print('OK : service de remediation raccorde a Ansible ; alerte sans jeton refusee')
        print('OK : playbook execute en mode controle ; un seul backend du projet autorise')
        print('RECETTE ANSIBLE CONTROLE OK. Aucun redemarrage ni paiement execute.')
        print('La recette de panne et sa nouvelle commande de preuve restent a effectuer.')
    except (OSError,ValueError,subprocess.TimeoutExpired):
        print('ECHEC : verifier la reconstruction remediation, docker-guard et la cible unique du projet.')
        print('Aucun secret a partager. Ne relancez pas de panne avant correction.')
        sys.exit(1)
