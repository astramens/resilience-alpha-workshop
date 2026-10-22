"""Restore routing from the latest WAF patch backup. Does not run Docker or touch data."""
import hashlib,json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
backups=sorted(root.glob('.rearm-backup-waf-*'))
if not backups:raise SystemExit('Aucune sauvegarde WAF trouvée. Aucun fichier modifié.')
backup=backups[-1];installed=json.loads((backup/'installed-hashes.json').read_text())
files=['docker-compose.yml','infra/nginx.conf','infra/proxy.conf']
for name in files:
    current=root/name;previous=backup/name
    if not previous.is_file():raise SystemExit('Sauvegarde incomplète : '+name)
    if hashlib.sha256(current.read_bytes()).hexdigest()!=installed[name]:raise SystemExit('Fichier modifié depuis la pose du WAF : '+name+'. Aucun fichier restauré.')
for name in files:shutil.copy2(backup/name,root/name)
print('Routage précédent restauré. Aucune donnée modifiée. Aucun conteneur redémarré.')
print('Appliquer : docker compose up -d frontend edge')
print('Puis arrêter seulement l’ancien conteneur WAF depuis Docker Desktop, s’il reste actif.')
