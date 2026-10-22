"""Local HTTPS preparation. Trust is a distinct, explicit current-user action."""
import hashlib
import ipaddress
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit
import secrets_vault as vault
from secret_permissions import SecretError, no_links, private, private_directory
from secrets_tools import secure_home

ROOT=Path(__file__).resolve().parents[1]
WIN_MKCERT_SHA256='d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398'
MANAGED=('ALLOWED_ORIGINS','COOKIE_SECURE','PAYMENT_PUBLIC_URL','REARM_TLS_CERT_DIR')


def tls_home():
    suffix=hashlib.sha256(os.path.normcase(str(ROOT)).encode()).hexdigest()[:16]
    return no_links(secure_home()/'tls'/suffix)


def find_mkcert():
    candidates=[]
    if os.name=='nt':
        for base in [Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/WinGet/Packages',
                     Path(os.environ.get('ProgramFiles','C:/Program Files'))/'WinGet/Packages']:
            candidates.extend(sorted(base.glob('FiloSottile.mkcert_*/mkcert.exe')))
    found=shutil.which('mkcert')
    if found:candidates.append(Path(found))
    for p in candidates:
        if p.is_file():
            path=p.resolve()
            if os.name=='nt':
                if platform.machine().lower() not in ('amd64','x86_64'):
                    raise SecretError('Cette preparation Windows correspond a mkcert x64.')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=WIN_MKCERT_SHA256:
                    raise SecretError('Empreinte mkcert inattendue. Ne pas ignorer ce controle.')
            return path
    raise SecretError('mkcert introuvable dans PATH ou les dossiers WinGet usuels.')


def run_mkcert(args):
    env={k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','PATH') if k in os.environ}
    env['CAROOT']=str(tls_home()/'ca')
    env['TRUST_STORES']='system'
    try:r=subprocess.run([str(find_mkcert()),*args],cwd=tls_home(),env=env,capture_output=True,timeout=40)
    except (OSError,subprocess.TimeoutExpired):raise SecretError('mkcert indisponible ou delai depasse.') from None
    if r.returncode:raise SecretError('Operation mkcert refusee. Aucun contenu prive affiche.')
    return r.stdout


def parse_env(raw):
    result={}
    for line in raw.decode('utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);result[key.strip()]=value.strip().strip('"').strip("'")
    return result


def update_env(raw, values):
    text=raw.decode('utf-8-sig')
    lines=[line for line in text.splitlines(keepends=True)
           if line.partition('=')[0].strip() not in values]
    text=''.join(lines)
    if text and not text.endswith(('\n','\r')):text+='\n'
    for key,value in values.items():
        if value is None:continue
        if any(x in value for x in "'\r\n\0"):
            raise SecretError('Valeur de configuration HTTPS invalide.')
        text+=key+"='"+value+"'\n"
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+text.encode()


def atomic_private(path, raw):
    path=no_links(path);temp=path.with_name(path.name+'.https-tmp')
    vault.write_private(temp,raw)
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def certificate_self_check(lan):
    home=tls_home();ca=home/'ca/rootCA.pem';leaf=home/'leaf'
    for p in [ca,home/'ca/rootCA-key.pem',leaf/'cert.pem',leaf/'key.pem']:
        private(p)
    server=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version=ssl.TLSVersion.TLSv1_2
    server.load_cert_chain(leaf/'cert.pem',leaf/'key.pem')
    errors=[]
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
    def serve():
        try:
            for _ in range(2):
                connection,_=listener.accept();connection.settimeout(5)
                with server.wrap_socket(connection,server_side=True) as stream:stream.sendall(b'OK')
        except (OSError,ssl.SSLError) as exc:errors.append(type(exc).__name__)
        finally:listener.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    port=listener.getsockname()[1]
    try:
        for host in ('localhost',lan):
            ctx=ssl.create_default_context(cafile=ca)
            with socket.create_connection(('127.0.0.1',port),timeout=5) as raw:
                with ctx.wrap_socket(raw,server_hostname=host) as stream:
                    if stream.recv(2)!=b'OK':raise SecretError('Certificat TLS non confirme.')
        thread.join(6)
        if thread.is_alive() or errors:raise SecretError('Validation locale du certificat echouee.')
    finally:listener.close()


def overlay():
    # Automatic Compose override; no need to remember extra -f flags afterward.
    return b'''services:
  edge:
    ports: ["443:8443"]
    volumes:
      - type: bind
        source: ${REARM_TLS_CERT_DIR:?Run python scripts/https_setup.py first}
        target: /etc/nginx/tls
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: ${REARM_TLS_CERT_DIR:?Run python scripts/https_setup.py first}/edge.conf
        target: /etc/nginx/conf.d/default.conf
        read_only: true
        bind:
          create_host_path: false
'''


def load_state():
    path=tls_home()/'state.json';private(path)
    state=json.loads(path.read_text())
    if state.get('root')!=str(ROOT) or state.get('schema')!=1:
        raise SecretError('Etat HTTPS ne correspondant pas a ce projet.')
    return state



def require_port_available(port=443):
    with socket.socket() as port_check:
        try:port_check.bind(('0.0.0.0',port))
        except OSError:raise SecretError('Le port 443 du PC est deja utilise ou reserve. Ne pas arreter un autre service sans diagnostic.') from None

def prepare(lan):
    address=ipaddress.ip_address(lan)
    if address.version!=4 or not any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise SecretError('Utiliser une adresse IPv4 privee du PC, par exemple 192.168.137.1.')
    private_directory(secure_home());private_directory(secure_home()/'tls')
    home=private_directory(tls_home())
    if (home/'state.json').exists():
        state=load_state()
        if state['lan']!=lan:raise SecretError('Adresse differente de la preparation existante.')
        certificate_self_check(lan)
        current=parse_env((ROOT/'.env').read_bytes())
        if any(current.get(k)!=v for k,v in state['expected'].items()):
            raise SecretError('Configuration HTTPS modifiee depuis preparation.')
        if (ROOT/'docker-compose.override.yml').read_bytes()!=overlay():
            raise SecretError('Surcharge Compose modifiee depuis preparation.')
        print('Preparation HTTPS deja presente et coherente. Aucun certificat remplace.')
        return
    require_port_available()
    for name in ('compose.override.yml','compose.override.yaml','docker-compose.override.yml','docker-compose.override.yaml'):
        if (ROOT/name).exists():raise SecretError('Une surcharge Compose existe deja. Ne pas la remplacer automatiquement.')
    ca=private_directory(home/'ca');leaf=private_directory(home/'leaf')
    if (ca/'rootCA.pem').exists() != (ca/'rootCA-key.pem').exists():
        raise SecretError('Autorite locale incomplete. La conserver pour diagnostic.')
    if (leaf/'cert.pem').exists() != (leaf/'key.pem').exists():
        raise SecretError('Certificat local incomplet. Aucun fichier remplace.')
    if run_mkcert(['-version']).strip()!=b'v1.4.4':raise SecretError('mkcert 1.4.4 requis pour cette preparation.')
    if not (leaf/'cert.pem').exists():
        run_mkcert(['-cert-file',str(leaf/'cert.pem'),'-key-file',str(leaf/'key.pem'),
                    'localhost','127.0.0.1','::1',lan])
    for folder in (ca,leaf):
        for p in folder.iterdir():
            if p.is_file():private(p,apply=True)
    certificate_self_check(lan)
    raw=(ROOT/'.env').read_bytes();before=parse_env(raw)
    oldurl=urlsplit(before.get('PAYMENT_PUBLIC_URL','http://localhost:3000'))
    if oldurl.hostname not in ('localhost','127.0.0.1',lan):
        raise SecretError('URL Stripe non locale inattendue. Adapter la preparation avant activation.')
    urls={'https://localhost','https://127.0.0.1','https://'+lan}
    origins=set(before.get('ALLOWED_ORIGINS','').split(','));origins.discard('');origins.update(urls)
    values={'ALLOWED_ORIGINS':','.join(sorted(origins)), 'COOKIE_SECURE':'true',
            'PAYMENT_PUBLIC_URL':'https://'+oldurl.hostname,'REARM_TLS_CERT_DIR':leaf.as_posix()}
    rendered=(ROOT/'infra/nginx-https.conf.template').read_text().replace('__LAN_IP__',lan).encode()
    if (leaf/'edge.conf').exists() and (leaf/'edge.conf').read_bytes()!=rendered:
        raise SecretError('Configuration nginx externe inattendue. Aucun remplacement automatique.')
    if not (leaf/'edge.conf').exists():vault.write_private(leaf/'edge.conf',rendered)
    # Encrypted rollback point. No additional plaintext .env backup.
    vault.seal();previous=vault.latest()
    state={'schema':1,'root':str(ROOT),'lan':lan,'expected':values,
           'env_backup':str(previous),'ca_sha256':hashlib.sha256(ssl.PEM_cert_to_DER_cert((ca/'rootCA.pem').read_text())).hexdigest()}
    override=ROOT/'docker-compose.override.yml'
    try:
        vault.write_private(override,overlay())
        atomic_private(ROOT/'.env',update_env(raw,values))
        vault.write_private(home/'state.json',json.dumps(state).encode())
    except Exception:
        atomic_private(ROOT/'.env',raw)
        if override.exists() and override.read_bytes()==overlay():override.unlink()
        raise
    print('HTTPS PREPARE : certificat localhost/IP valide, cle CA hors du projet et hors Docker.')
    print('Cookies Secure et retour Stripe HTTPS prepares. Aucun service redemarre.')
    print('URL apres activation : https://localhost ; acces reseau : https://'+lan)
    print('Empreinte publique CA SHA256 :',state['ca_sha256'])
    print('Prochaine etape : python scripts/https_setup.py trust')


def trust(remove=False):
    if os.name!='nt':raise SecretError('La confiance automatique de cette etape concerne le magasin Windows du compte courant.')
    if remove and not (tls_home()/'state.json').exists():
        old=tls_home()/'state-rolled-back.json';private(old);state=json.loads(old.read_text())
        if state.get('root')!=str(ROOT):raise SecretError('Autorite ne correspondant pas a ce projet.')
    else:state=load_state()
    ca=tls_home()/'ca/rootCA.pem';private(ca)
    der=ssl.PEM_cert_to_DER_cert(ca.read_text())
    if hashlib.sha256(der).hexdigest()!=state['ca_sha256']:
        raise SecretError('Autorite locale differente de celle preparee.')
    certutil=Path(os.environ['SystemRoot'])/'System32/certutil.exe'
    args=([str(certutil),'-user','-delstore','Root',hashlib.sha1(der).hexdigest()] if remove
          else [str(certutil),'-user','-addstore','Root',str(ca)])
    r=subprocess.run(args,capture_output=True,timeout=20)
    if r.returncode:raise SecretError('Modification du magasin de certificats refusee.')
    print('Confiance de cette autorite locale '+('retiree' if remove else 'ajoutee')+' pour ce compte Windows uniquement.')
    print('Aucune cle privee installee dans le navigateur. Fermer puis rouvrir le navigateur si necessaire.')


if __name__=='__main__':
    try:
        action=sys.argv[1:] or ['prepare']
        if action==['trust']:trust()
        elif action==['untrust']:trust(remove=True)
        elif action==['prepare']:
            lan=input('Adresse IPv4 du PC pour le reseau local [192.168.137.1] : ').strip() or '192.168.137.1'
            prepare(lan)
        else:raise SecretError('Usage : python scripts/https_setup.py [prepare|trust|untrust]')
    except (OSError,ValueError,KeyError,SecretError,ssl.SSLError) as exc:
        message=str(exc) if isinstance(exc,SecretError) else 'Preparation HTTPS non validee. Verifier outils, fichiers et droits sans afficher les secrets.'
        raise SystemExit('ECHEC : '+message) from None
