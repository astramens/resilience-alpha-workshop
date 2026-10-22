"""Restore the changed configuration and backend files; preserve databases and secrets."""
from pathlib import Path
import hashlib,json,shutil
root=Path(__file__).resolve().parents[1];backups=sorted(root.glob('.rearm-backup-supervision-*'))
if not backups:raise SystemExit('Aucune sauvegarde de supervision trouvée. Aucun fichier modifié.')
backup=backups[-1];manifest=json.loads((backup/'installed-hashes.json').read_text());files=['docker-compose.yml','backend/main.py','backend/Dockerfile','tests/test_waf_boundary.py']
for name in files:
    if not (backup/name).exists():raise SystemExit('Sauvegarde incomplète : '+name)
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=manifest[name]:raise SystemExit('Fichier modifié depuis l’installation : '+name+'. Aucun fichier restauré.')
for name in files:shutil.copy2(backup/name,root/name)
print('Configuration et code précédents restaurés. Secrets, base et volumes de supervision conservés.')
print('Appliquer : docker compose up -d --build backend auth edge')
print('Arrêter ensuite les anciens conteneurs prometheus, blackbox et grafana depuis Docker Desktop.')
