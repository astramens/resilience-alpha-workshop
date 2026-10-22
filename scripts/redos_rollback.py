"""Restore only this patch's source files; never secrets, data or certificates."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path(__file__).resolve().parents[1]
backups = sorted(root.glob('.rearm-backup-redteam-*'))
if not backups: raise SystemExit('Sauvegarde Red Team introuvable.')
backup = backups[-1]
installed = json.loads((backup / 'installed-hashes.json').read_text())
for name, digest in installed.items():
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or name.startswith('.'):
        raise SystemExit('Sauvegarde invalide.')
    target = root / path
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise SystemExit('Un fichier a change depuis cette mise a jour : retour automatique refuse.')
for name in installed:
    saved = backup / name
    if saved.exists(): shutil.copy2(saved, root / name)
    else: (root / name).unlink()
print('Sources precedentes restaurees. Secrets, donnees et certificats conserves.')
print('Reconstruire : docker compose up -d --build --no-deps backend log-gateway')
