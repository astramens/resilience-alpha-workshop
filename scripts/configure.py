"""Local-only secret generation. Never include the resulting .env in a submission."""
from pathlib import Path
import secrets
root = Path(__file__).resolve().parents[1]
p = root / '.env'
if p.exists():
    raise SystemExit('Un fichier .env existe déjà. Conservez-le ou renommez-le avant de configurer.')
password = secrets.token_urlsafe(20)
p.write_text('COMPOSE_PROJECT_NAME=resilience-alpha\nPOSTGRES_DB=resilience\nPOSTGRES_USER=resilience\nPOSTGRES_PASSWORD=' + secrets.token_urlsafe(32) + '\nOPERATOR_USERNAME=operateur\nOPERATOR_PASSWORD=' + password + '\nREMEDIATION_TOKEN=' + secrets.token_urlsafe(32) + '\nALLOWED_ORIGINS=http://localhost:3000,http://192.168.137.1:3000\nCOOKIE_SECURE=false\n')
p.chmod(0o600)
print('Configuration générée. Identifiant : operateur\nMot de passe : ' + password)
