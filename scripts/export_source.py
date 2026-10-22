"""Export sources only; no credentials, keys, ciphertext snapshots or copied backups."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import os
root=Path(__file__).resolve().parents[1]
excluded={'.git','node_modules','.next','.pio','.idea','.venv','.venv-camera','venv','__pycache__','models','face-auth-update','REARM-update','backups','secrets','REARM-secrets'}

def excluded_source(rel):
    if any(p in excluded or p.startswith(('.face-backup','.rearm-backup','secrets-restore','REARM-secrets-restore')) for p in rel.parts):return True
    name=rel.name.lower()
    if name.startswith(('.env','.camera-agent.json','secrets.h')):return True
    if '.bak-' in name or name.endswith('.sops.json'):return True
    if name in {'keys.txt','age-key.txt','age-keys.txt','identity.txt'}:return True
    return rel.suffix.lower() in {'.zip','.onnx','.log','.dump','.bak','.pyc','.tsbuildinfo','.age','.key','.pem','.p12','.pfx'}

def export():
    destination=root.parent/'REARM-source.zip'
    # Do not follow directory symlinks/junctions or include files outside the tree.
    temporary=destination.with_name(destination.name+'.partial')
    try:
        with ZipFile(temporary,'x',ZIP_DEFLATED) as archive:
            for current,dirs,files in os.walk(root,followlinks=False):
                current=Path(current)
                dirs[:]=[n for n in dirs if not excluded_source((current/n).relative_to(root))
                          and not (current/n).is_symlink()
                          and not (hasattr(current/n,'is_junction') and (current/n).is_junction())]
                for name in files:
                    file=current/name;rel=file.relative_to(root)
                    if file.is_symlink() or excluded_source(rel):continue
                    if file.is_file():archive.write(file,rel)
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    print('Sources exportées :',destination)

if __name__=='__main__':export()
