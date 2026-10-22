"""Set only the initial Grafana password, without printing it or replacing other secrets."""
from pathlib import Path
import getpass,os,secrets
root=Path(__file__).resolve().parents[1];path=root/'.env'
if not path.exists():raise SystemExit('Placez ce script dans le projet déjà configuré.')
text=path.read_text(encoding='utf-8-sig');settings={}
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1);settings[key.strip()]=value.strip().strip('"').strip("'")
if settings.get('REARM_GRAFANA_PASSWORD'):
    print('Grafana est déjà configuré. Aucun secret modifié. Le mot de passe existant est conservé.')
    raise SystemExit(0)
password=getpass.getpass('Choisissez un mot de passe Grafana (12 caractères minimum ; saisie masquée) : ')
if len(password)<12 or any(ch in password for ch in "'\r\n\0"):
    raise SystemExit('Utilisez au moins 12 caractères, sans apostrophe ni retour à la ligne. Aucun fichier modifié.')
if password!=getpass.getpass('Confirmez ce mot de passe : '):raise SystemExit('Les deux saisies diffèrent. Aucun fichier modifié.')
# Single quoted dotenv values preserve #, $, backslashes, spaces and Unicode literally.
newtext=text.rstrip()+"\n\n# Supervision REARM — mot de passe initial Grafana\nREARM_GRAFANA_PASSWORD='"+password+"'\n"
# Grafana encrypts stored datasource secrets with this persistent separate key.
if not settings.get('REARM_GRAFANA_SECRET_KEY'):newtext+='REARM_GRAFANA_SECRET_KEY='+secrets.token_urlsafe(48)+'\n'
temp=path.with_name('.env.monitoring-tmp')
try:
    with open(temp,'x',encoding='utf-8',newline='\n') as stream:stream.write(newtext)
    os.chmod(temp,0o600);os.replace(temp,path)
finally:
    if temp.exists():temp.unlink()
print('Supervision configurée. Identifiant Grafana : superviseur')
print('Mot de passe : celui que vous venez de choisir. Aucun secret affiché.')
print('Stripe, caméra, LED et identifiants existants conservés. Aucun conteneur redémarré.')
print('Prochaine étape : docker compose config --quiet')
