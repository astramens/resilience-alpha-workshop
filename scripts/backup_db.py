"""Local PostgreSQL backup, never uploaded or included in the delivery archive."""
import os,subprocess
from datetime import datetime
from pathlib import Path
root=Path(__file__).resolve().parents[1]
settings={}
for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1);settings[key.strip()]=value.strip().strip('"').strip("'")
folder=root/'backups';folder.mkdir(exist_ok=True)
path=folder/('rearm-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.dump')
try:
    with path.open('xb') as out:
        result=subprocess.run(['docker','compose','exec','-T','db','pg_dump','-U',settings.get('POSTGRES_USER','resilience'),'-d',settings.get('POSTGRES_DB','resilience'),'-Fc'],stdout=out,cwd=root)
    if result.returncode or path.stat().st_size<100:
        path.unlink(missing_ok=True);raise SystemExit('Sauvegarde échouée : arrêtez la mise à jour.')
    os.chmod(path,0o600)
    print('Sauvegarde créée :',path)
    print('Contient des données sensibles, dont les empreintes faciales. Conservez-la localement.')
except Exception:
    path.unlink(missing_ok=True)
    raise
