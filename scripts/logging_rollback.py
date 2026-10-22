"""Restore only this patch after checking every installed hash. Never remove volumes."""
from pathlib import Path
import hashlib,json,shutil
root=Path(__file__).resolve().parents[1]
backups=sorted(root.glob('.rearm-backup-journaux-*'))
if not backups:raise SystemExit('Aucune sauvegarde de cette mise à jour.')
backup=backups[-1]
manifest=json.loads((backup/'installed-hashes.json').read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
for name,expected in manifest.items():
    if digest(root/name)!=expected:raise SystemExit('Fichier modifié depuis installation : '+name+'. Aucun changement.')
# This script may remove itself after it has been loaded, which is safe on Windows.
for name in manifest:
    saved=backup/name;target=root/name
    if saved.exists():shutil.copy2(saved,target)
    elif target.exists():target.unlink()
print('Fichiers précédents restaurés. Aucun conteneur, volume ou secret supprimé.')
print('Appliquez : docker compose up -d --no-deps --force-recreate grafana')
print('Arrêtez ensuite les 3 anciens conteneurs Loki/log-gateway/log-collector dans Docker Desktop sans supprimer leurs volumes.')
