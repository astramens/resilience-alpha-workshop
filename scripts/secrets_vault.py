"""SOPS/age snapshots of exact runtime bytes. Never prints secret content.

Runtime files remain available to existing Compose/camera/firmware workflows.
No Docker calls, credential rotation, automatic deletion or runtime overwrite.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from secret_permissions import SecretError, no_links, private, private_directory
from secrets_tools import check_tools, secure_home, tool_path

ROOT=Path(__file__).resolve().parents[1]
FILES=('.env','.camera-agent.json','esp8266-led/include/secrets.h')
LIMIT=1024*1024


def identity():
    path=no_links(secure_home()/'keys.txt')
    if path.is_relative_to(ROOT.absolute()):raise SecretError('La cle age doit rester hors du projet.')
    return path


def tool_environment():
    # No inherited SOPS/KMS/keyservice/proxy/SSH overrides, no secret arguments.
    env={k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA') if k in os.environ}
    env.update({'HOME':str(secure_home()),'PATH':str(secure_home()/'tools'),
                'SOPS_AGE_KEY_FILE':str(identity())})
    return env


def run_tool(name, args, data=None):
    try:
        result=subprocess.run([str(tool_path(name)),*args],input=data,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              cwd=secure_home(),env=tool_environment(),timeout=30)
    except (OSError,subprocess.TimeoutExpired):
        raise SecretError('Outil de chiffrement indisponible ou delai depasse.') from None
    if result.returncode or len(result.stdout)>10*LIMIT:
        raise SecretError('Operation cryptographique refusee. Aucun contenu affiche.')
    return result.stdout


def recipient():
    private(identity())
    value=run_tool('age-keygen',['-y',str(identity())]).decode('ascii').strip()
    if not re.fullmatch(r'age1[0-9a-z]{58}',value):
        raise SecretError('Cle age inattendue.')
    return value


def config():
    p=no_links(secure_home()/'empty.sops.yaml');expected=b'creation_rules:\n  - {}\n'
    if not p.exists():write_private(p,expected)
    private(p)
    if p.read_bytes()!=expected:raise SecretError('Configuration SOPS locale inattendue.')
    return p


def write_private(path, data):
    path=no_links(path)
    # Apply permissions to an EMPTY new file before any plaintext is written.
    with path.open('xb') as stream:
        try:
            private(path,apply=True)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        except Exception:
            stream.close();path.unlink(missing_ok=True)
            raise


def runtime(protect=False):
    result={}
    for name in FILES:
        path=no_links(ROOT/name)
        if not path.is_file() or not 0<path.stat().st_size<=LIMIT:
            raise SecretError('Un des trois fichiers de configuration est absent, vide ou trop grand.')
        private(path,apply=protect)
        result[name]=path.read_bytes()
    return result


def archive_directory():
    return no_links(ROOT/'secrets')


def latest():
    folder=archive_directory();private(folder)
    paths=sorted(p for p in folder.glob('runtime-*.sops.json')
                 if re.fullmatch(r'runtime-[0-9]{8}-[0-9]{6}-[0-9]{6}\.sops\.json',p.name))
    if not paths:raise SecretError('Aucune sauvegarde SOPS disponible. Executer seal.')
    return no_links(paths[-1])


def validate_cipher(raw, public):
    try:
        data=json.loads(raw)
        if set(data)!={'data','sops'} or not isinstance(data['data'],str) or not data['data'].startswith('ENC[AES256_GCM,'):
            raise ValueError()
        meta=data['sops']
        if any(meta.get(k) for k in ('kms','gcp_kms','azure_kv','hc_vault','pgp','hckms','key_groups')):
            raise ValueError()
        allowed={'kms','gcp_kms','azure_kv','hc_vault','pgp','hckms','age','lastmodified','mac','version','unencrypted_suffix'}
        if set(meta)-allowed:raise ValueError()
        if len(meta['age'])!=1 or meta['age'][0]['recipient']!=public:raise ValueError()
    except (ValueError,KeyError,TypeError,AttributeError):
        raise SecretError('Enveloppe SOPS inattendue ou destinataire incorrect.') from None


def decrypt(raw, public):
    if len(raw)>10*LIMIT:raise SecretError('Sauvegarde chiffree trop grande.')
    validate_cipher(raw,public)
    result=run_tool('sops',['--config',str(config()),'decrypt','--input-type','json',
                           '--output-type','binary','--filename-override','runtime.sops.json'],raw)
    try:
        bundle=json.loads(result)
        if set(bundle)!={'schema','created_at','files'} or (type(bundle['schema']) is not int or bundle['schema']!=1) or set(bundle['files'])!=set(FILES):
            raise ValueError()
        files={name:base64.b64decode(bundle['files'][name],validate=True) for name in FILES}
        if any(not 0<len(v)<=LIMIT for v in files.values()):raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise SecretError('Contenu de sauvegarde invalide. Aucun fichier restaure.') from None
    return files


def seal():
    check_tools();private(secure_home());public=recipient()
    files=runtime(protect=True)
    folder=private_directory(archive_directory())
    bundle={'schema':1,'created_at':datetime.now(timezone.utc).isoformat(),
            'files':{n:base64.b64encode(v).decode('ascii') for n,v in files.items()}}
    raw=run_tool('sops',['--config',str(config()),'encrypt','--age',public,
                         '--input-type','binary','--output-type','json',
                         '--filename-override','runtime.bin'],json.dumps(bundle).encode())
    if decrypt(raw,public)!=files:raise SecretError('Verification apres chiffrement echouee.')
    if runtime()!=files:raise SecretError('Configuration modifiee pendant la sauvegarde : recommencer seal.')
    path=folder/('runtime-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.sops.json')
    write_private(path,raw)
    # Read/decrypt the durable ciphertext, not just the in-memory encryption result.
    if decrypt(path.read_bytes(),public)!=files:
        raise SecretError('Verification de la sauvegarde sur disque echouee.')
    print('SAUVEGARDE SOPS OK : trois fichiers chiffres, dechiffrement et egalite exacte verifies.')
    print('Droits locaux limites au compte courant'+(' et SYSTEM.' if os.name=='nt' else '.'))
    print('Les fichiers de fonctionnement restent en clair ; aucun identifiant ni service modifie.')


def setup():
    check_tools();home=private_directory(secure_home());key=identity()
    if not key.exists():
        if list(archive_directory().glob('*.sops.json')):
            raise SecretError('Sauvegarde existante sans cle : restaurer la cle externe, ne pas en generer une autre.')
        raw=run_tool('age-keygen',[])
        if raw.count(b'AGE-SECRET-KEY-1')!=1:raise SecretError('Generation de cle age invalide.')
        write_private(key,raw)
    else:private(key,apply=True)
    recipient();config()
    print('Cle age prete hors du projet. Cle existante conservee le cas echeant.')
    seal()
    print('Cle privee a sauvegarder SEPAREMENT sur un support protege :',key)
    print('Ne partagez ni cette cle, ni .env, ni .camera-agent.json, ni secrets.h.')


def check():
    check_tools();private(secure_home());private(identity())
    path=latest();private(path)
    saved=decrypt(path.read_bytes(),recipient())
    if runtime()!=saved:
        raise SecretError('Configuration locale differente de la derniere sauvegarde. Executer seal apres verification de vos changements.')
    print('RECETTE SECRETS OK : chiffrement SOPS/age, integrite, droits prives et trois fichiers identiques.')
    print('Aucun secret affiche, aucun fichier de fonctionnement remplace, aucun service redemarre.')
    return saved


def restore_files(saved, output):
    output=no_links(output)
    if output.is_relative_to(ROOT.absolute()) or ROOT.absolute().is_relative_to(output):
        raise SecretError('La restauration doit viser un nouveau dossier hors du projet.')
    # Never overwrite an existing directory, not even an empty one.
    output.mkdir(mode=0o700);private(output,apply=True)
    for name in FILES:
        p=output/name
        # All names have already been validated against the fixed three-file set.
        for parent in reversed(p.parent.relative_to(output).parents):
            if str(parent)!='.':private_directory(output/parent)
        private_directory(p.parent)
        write_private(p,saved[name])
    for name in FILES:
        if (output/name).read_bytes()!=saved[name]:raise SecretError('Egalite de restauration non confirmee.')


def restore_test():
    saved=check()
    output=secure_home()/('restore-test-'+uuid.uuid4().hex)
    try:
        restore_files(saved,output)
        print('Restauration des trois fichiers dans un dossier prive : identique octet par octet.')
    finally:
        if output.exists():shutil.rmtree(output)
    print('RECETTE RESTAURATION CONFIGURATION OK : dossier temporaire supprime. Projet actif inchange.')


def main():
    parser=argparse.ArgumentParser(description='Sauvegardes chiffrees locales REARM, sans affichage de secrets.')
    parser.add_argument('action',choices=['setup','seal','check','restore-test','restore'])
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='restore':
            if args.output_dir is None:raise SecretError('restore exige --output-dir vers un NOUVEAU dossier hors du projet.')
            check_tools();saved=decrypt(latest().read_bytes(),recipient())
            restore_files(saved,args.output_dir)
            print('Configuration restauree hors du projet. Ces copies sont sensibles et restent en clair.')
            print('Aucun fichier actif remplace, aucun service redemarre.')
        else:
            if args.output_dir is not None:raise SecretError('--output-dir concerne uniquement restore.')
            {'setup':setup,'seal':seal,'check':check,'restore-test':restore_test}[args.action]()
    except SecretError as exc:
        raise SystemExit('ECHEC : '+str(exc)) from None
    except (OSError,ValueError,KeyError,TypeError):
        raise SystemExit('ECHEC : verifier chemins, droits, outils et cle externe. Aucun contenu sensible affiche.') from None


if __name__=='__main__':main()
