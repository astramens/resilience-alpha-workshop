"""Idempotent migration and catalog seed. Never drops tables or overwrites stock."""
import json
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]

def run_sql(sql):
    settings={}
    for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);settings[key.strip()]=value.strip().strip('"').strip("'")
    result=subprocess.run(['docker','compose','exec','-T','db','psql','-v','ON_ERROR_STOP=1','-U',settings.get('POSTGRES_USER','resilience'),'-d',settings.get('POSTGRES_DB','resilience')],input=sql.encode(),cwd=root)
    if result.returncode:raise SystemExit('Migration interrompue. Ne reconstruisez pas encore les services.')

def seed_sql():
    products=json.loads((root/'db/catalog.json').read_text(encoding='utf-8'))
    def literal(value):
        if isinstance(value,int):return str(value)
        return "'"+str(value).replace("'","''")+"'"
    sql=['BEGIN;']
    for p in products:
        fields=('sku','name','category','description','grade','price_cents','stock','image','workshop_note')
        sql.append('INSERT INTO shop_products ('+','.join(fields)+') VALUES ('+','.join(literal(p[k]) for k in fields)+') ON CONFLICT(sku) DO NOTHING;')
    return '\n'.join(sql+['COMMIT;'])

if __name__=='__main__':
    run_sql((root/'db/init.sql').read_text(encoding='utf-8'))
    run_sql((root/'db/face-auth.sql').read_text(encoding='utf-8'))
    run_sql((root/'db/shop.sql').read_text(encoding='utf-8'))
    run_sql((root/'db/payments.sql').read_text(encoding='utf-8'))
    run_sql(seed_sql())
    print('REARM : tables et catalogue prêts. Comptes, visages et paiements conservés.')
