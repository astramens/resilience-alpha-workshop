"""Configure local Stripe TEST keys. Never prints secrets or changes other settings."""
import getpass,os,re
from pathlib import Path
from urllib.parse import urlsplit
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if not path.exists():raise SystemExit('Lancez ce script depuis le projet déjà configuré.')
text=path.read_text(encoding='utf-8-sig')
settings={}
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1);settings[k.strip()]=v.strip().strip('"').strip("'")
base=input('URL de retour [http://localhost:3000] : ').strip() or 'http://localhost:3000'
base=base.rstrip('/')
allowed=set(settings.get('ALLOWED_ORIGINS','http://localhost:3000,http://192.168.137.1:3000').split(','))
if base not in allowed:raise SystemExit('Cette URL doit déjà figurer dans ALLOWED_ORIGINS. Aucune modification effectuée.')
key=getpass.getpass('Clé secrète Stripe de TEST (sk_test_..., saisie masquée) : ').strip()
if not re.fullmatch(r'sk_test_[A-Za-z0-9]+',key):raise SystemExit('Seule une clé sk_test_ est acceptée. Aucune modification effectuée.')
secret=getpass.getpass('Secret du listener webhook (whsec_..., saisie masquée) : ').strip()
if not re.fullmatch(r'whsec_[A-Za-z0-9]+',secret):raise SystemExit('Secret webhook invalide. Aucune modification effectuée.')
values={'PAYMENT_MODE':'stripe_test','PAYMENT_PUBLIC_URL':base,'STRIPE_SECRET_KEY':key,'STRIPE_WEBHOOK_SECRET':secret}
lines=[line for line in text.splitlines() if line.partition('=')[0].strip() not in values]
lines+=['','# Stripe Checkout — TEST uniquement']+[k+'='+v for k,v in values.items()]
temporary=path.with_name('.env.payment-tmp')
try:
    with open(temporary,'x',encoding='utf-8',newline='\n') as stream:stream.write('\n'.join(lines)+'\n')
    os.chmod(temporary,0o600);os.replace(temporary,path)
finally:
    if temporary.exists():temporary.unlink()
print('Stripe test configuré. Identifiants caméra et LED conservés. Aucun service redémarré.')
print('Ne partagez pas .env. Prochaine étape : docker compose up -d --build backend frontend edge')
