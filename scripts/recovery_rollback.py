from pathlib import Path
import hashlib,json,shutil
root=Path(__file__).resolve().parents[1]
backups=sorted(root.glob('.rearm-backup-reprise-*'))
if not backups:raise SystemExit('Aucune sauvegarde de ce correctif trouvée.')
backup=backups[-1];manifest=json.loads((backup/'installed-hashes.json').read_text())
for name,expected in manifest.items():
 p=root/name
 if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
  raise SystemExit('Fichier modifié depuis installation : '+name+'. Aucun changement.')
for name in manifest:
 saved=backup/name;target=root/name
 if saved.exists():shutil.copy2(saved,target)
 else:target.unlink()
print('Fichiers précédents restaurés. Aucune table, preuve, clé ou volume supprimé.')
print('Appliquez : docker compose up -d --build --no-deps backend remediation ai-engine log-gateway')
