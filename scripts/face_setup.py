"""Adds separate host/LED secrets. Does not overwrite existing credentials."""
from pathlib import Path
import json
import secrets
root=Path(__file__).resolve().parents[1]
env=root/'.env'
if not env.exists(): raise SystemExit('Le fichier .env existant est introuvable. Ne relancez pas configure.py.')
text=env.read_text(encoding='utf-8-sig')
values={}
for line in text.splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k,v=line.split('=',1);values[k.strip()]=v.strip().strip('\"\'')
addition=[]
for key in ['CAMERA_AGENT_TOKEN','LED_DEVICE_TOKEN']:
    if not values.get(key):
        values[key]=secrets.token_urlsafe(32)
        addition.append(key+'='+values[key])
if addition:
    with env.open('a',encoding='utf-8') as f: f.write('\n'+'\n'.join(addition)+'\n')
cfg_path=root/'.camera-agent.json'
cfg=json.loads(cfg_path.read_text(encoding='utf-8-sig')) if cfg_path.exists() else {'url':'http://localhost:3000','camera_index':0}
cfg['token']=values['CAMERA_AGENT_TOKEN']
cfg_path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
print('Configuration camera et LED preparee. Les identifiants existants sont conserves.')
print('Ne partagez pas .env ni .camera-agent.json.')
