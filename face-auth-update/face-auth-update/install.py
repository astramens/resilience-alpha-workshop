"""Run from the root of the existing project. Does not restart Docker or alter data."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

patch=Path(__file__).resolve().parent
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd().resolve()
if not (root/'docker-compose.yml').exists() or not (root/'backend/main.py').exists():
    raise SystemExit('Ouvrez PowerShell dans la racine du projet existant, puis relancez ce script.')
if "version='0.2.0'" not in (root/'backend/main.py').read_text(encoding='utf-8-sig'):
    raise SystemExit('Version du backend inattendue. Aucune modification effectuee.')
manifest=json.loads((patch/'manifest.json').read_text(encoding='utf-8'))
for rel,digest in manifest.items():
    src=(patch/'payload'/rel).resolve()
    dest=(root/rel).resolve()
    if not src.is_relative_to((patch/'payload').resolve()) or not dest.is_relative_to(root):
        raise SystemExit('Chemin de mise a jour invalide.')
    if '.env' in Path(rel).parts or 'ai-engine' in Path(rel).parts:
        raise SystemExit('Le correctif ne doit pas remplacer .env ou le detecteur.')
    if hashlib.sha256(src.read_bytes()).hexdigest()!=digest:
        raise SystemExit('Fichier incomplet ou modifie : '+rel)
backup=root/('.face-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(exist_ok=False)
existing=[];created=[]
try:
    for rel in manifest:
        dest=root/rel
        if dest.exists():
            saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved);existing.append(rel)
        else: created.append(rel)
    (backup/'restore.json').write_text(json.dumps({'existing':existing,'created':created},indent=2),encoding='utf-8')
    for rel in manifest:
        dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(patch/'payload'/rel,dest)
    for filename in ['.gitignore','.dockerignore']:
        path=root/filename
        if path.exists(): shutil.copy2(path,backup/filename)
        with path.open('a',encoding='utf-8') as f:
            f.write('\n# Camera USB du PC Hote\n.camera-agent.json\n.face-backup-*/\nhost-camera/models/\n.venv-camera/\n')
except Exception:
    for rel in existing: shutil.copy2(backup/rel,root/rel)
    for rel in created: (root/rel).unlink(missing_ok=True)
    raise
print('Fichiers installes et verifies. Sauvegarde : '+backup.name)
print('Aucun conteneur redemarre. .env, detecteur et donnees conserves.')
print('Prochaine etape : python scripts/face_setup.py')
