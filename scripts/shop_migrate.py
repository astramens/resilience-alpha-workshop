"""Ajoute les tables REARM (catalogue, atelier, clients, commandes, incidents) a une base existante."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
values={}
for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k,v=line.split('=',1);values[k.strip()]=v.strip().strip('\"\'')
command=['docker','compose','exec','-T','db','psql','-v','ON_ERROR_STOP=1','-U',values.get('POSTGRES_USER','resilience'),'-d',values.get('POSTGRES_DB','resilience')]
subprocess.run(command,cwd=root,input=(root/'db/shop.sql').read_bytes(),check=True)
print('Migration REARM terminee. Le catalogue de demonstration est charge au demarrage de l API.')
