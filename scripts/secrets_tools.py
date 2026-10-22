"""Install pinned official SOPS/age binaries per user; verify SHA256 before use."""
import hashlib
import io
import json
import os
import platform
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlopen
from secret_permissions import SecretError, no_links, private, private_directory

SOPS_VERSION='3.12.2'
AGE_VERSION='1.3.2'
ASSETS={
    'windows': {
        'sops': ('https://github.com/getsops/sops/releases/download/v3.12.2/sops-v3.12.2.amd64.exe',
                 '5e777b1854ab2a6271d8f66375970e1fe3eea838251c309de151d16a2bdf13a2'),
        'age': ('https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-windows-amd64.zip',
                'f48d8f8f9ebe903ab5027ed067652f2cc1db94bc206976430133b905dcd8e8c7')},
    'linux': {
        'sops': ('https://github.com/getsops/sops/releases/download/v3.12.2/sops-v3.12.2.linux.amd64',
                 '14e2e1ba3bef31e74b70cf0b674f6443c80f6c5f3df15d05ffc57c34851b4998'),
        'age': ('https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz',
                'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10')},
}


def secure_home():
    if os.name=='nt':
        base=os.environ.get('LOCALAPPDATA')
        if not base:raise SecretError('LOCALAPPDATA introuvable.')
        return no_links(Path(base)/'REARM-secrets')
    return no_links(Path.home()/'.local/share/REARM-secrets')


def host_platform():
    if platform.machine().lower() not in ('amd64','x86_64'):
        raise SecretError('Cette installation prete a tester concerne Windows/Linux x64 uniquement.')
    name=platform.system().lower()
    if name not in ASSETS:raise SecretError('Plateforme non prise en charge.')
    return name


def tool_path(name):
    if name not in ('sops','age','age-keygen'):raise SecretError('Outil non autorise.')
    return secure_home()/'tools'/(name+('.exe' if os.name=='nt' else ''))


def download(url, expected):
    with urlopen(url,timeout=30) as response:
        data=response.read(100*1024*1024+1)
    if len(data)>100*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:
        raise SecretError('Empreinte du telechargement incorrecte : rien execute.')
    return data


def unpack(data, name, system):
    member='age/'+name+('.exe' if system=='windows' else '')
    if system=='windows':
        with zipfile.ZipFile(io.BytesIO(data)) as z:return z.read(member)
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as z:
        entry=z.getmember(member)
        if not entry.isfile() or entry.size>60*1024*1024:raise SecretError('Archive age invalide.')
        return z.extractfile(entry).read()


def check_tools():
    home=private(secure_home());folder=private(home/'tools')
    manifest_path=no_links(folder/'verified.json')
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('sops')!=SOPS_VERSION or manifest.get('age')!=AGE_VERSION:
        raise SecretError('Versions des outils inattendues.')
    for name in ('sops','age','age-keygen'):
        path=no_links(tool_path(name))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest.get('hashes',{}).get(name):
            raise SecretError('Outil absent ou modifie. Reinstaller les outils avant utilisation.')
    return True


def install():
    system=host_platform();home=private_directory(secure_home());folder=private_directory(home/'tools')
    try:
        check_tools()
        print('Outils SOPS et age deja installes et verifies. Aucun telechargement.')
        return
    except (OSError,ValueError,KeyError,SecretError):
        pass
    # Build all binaries before touching installed executables. Never extractall.
    payload={}
    for group in ('sops','age'):
        data=download(*ASSETS[system][group])
        if group=='sops':payload['sops']=data
        else:
            for name in ('age','age-keygen'):payload[name]=unpack(data,name,system)
    hashes={}
    for name,data in payload.items():
        path=no_links(tool_path(name));temporary=path.with_name(path.name+'.download')
        with temporary.open('xb') as stream:stream.write(data)
        try:
            if os.name=='nt':private(temporary,apply=True)
            else:temporary.chmod(0o700)
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
        hashes[name]=hashlib.sha256(data).hexdigest()
    manifest=folder/'verified.json'
    manifest.write_text(json.dumps({'sops':SOPS_VERSION,'age':AGE_VERSION,'hashes':hashes}))
    private(manifest,apply=True)
    check_tools()
    print('SOPS '+SOPS_VERSION+' et age '+AGE_VERSION+' installes pour ce compte ; empreintes verifiees.')
    print('Aucune cle creee, aucun secret lu, aucun conteneur redemarre.')


if __name__=='__main__':
    try:install()
    except (OSError,ValueError,KeyError,SecretError,tarfile.TarError,zipfile.BadZipFile):
        raise SystemExit('ECHEC : installation des outils non validee. Verifier reseau, droits et plateforme. Aucun detail sensible affiche.')
