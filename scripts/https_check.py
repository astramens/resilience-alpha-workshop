"""Read-only HTTPS, redirect and runtime configuration checks. No payment/login."""
import json
import os
import ssl
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
from https_setup import ROOT, tls_home, load_state, certificate_self_check
from secret_permissions import SecretError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def check(base='https://localhost',http='http://localhost:3000',verify_runtime=True):
    state=load_state();certificate_self_check(state['lan'])
    ca=tls_home()/'ca/rootCA.pem'
    context=ssl.create_default_context(cafile=ca)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    with opener.open(base+'/api/shop/products',timeout=8) as r:
        data=json.load(r)
        if r.status!=200 or not isinstance(data,list) or not data or r.headers.get('X-Rearm-Inspection')!='active':
            raise SecretError('Catalogue HTTPS ou passage par WAF non confirme.')
    print('OK : catalogue HTTPS, certificat et nom verifies ; passage par le WAF observe')
    for path in ('/','/admin','/api/auth/me','/api/shop/orders'):
        try:opener.open(http+path,timeout=8)
        except HTTPError as exc:
            location=exc.headers.get('Location','')
            if exc.code!=308 or not location.startswith('https://localhost'+path):
                raise SecretError('Redirection HTTP vers HTTPS incoherente.')
        else:raise SecretError('Acces navigateur HTTP encore servi sans redirection.')
    with opener.open(http+'/api/shop/products',timeout=8) as r:
        if r.status!=200 or not isinstance(json.load(r),list):
            raise SecretError('Sonde HTTP de compatibilite indisponible.')
    print('OK : navigation HTTP redirigee vers HTTPS ; sonde catalogue historique conservee')
    if os.name=='nt':
        # Independently use Windows/default trust, rather than merely the explicit CA.
        native=build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
        with native.open(base+'/api/shop/products',timeout=8) as r:
            if r.status!=200:raise SecretError('Confiance Windows non confirmee.')
        print('OK : autorite locale reconnue par la verification TLS Windows/Python')
    if verify_runtime:
        for service in ('backend','auth'):
            r=subprocess.run(['docker','compose','exec','-T',service,'python','-c',
                              "import os;print(os.environ.get('COOKIE_SECURE','false').lower())"],
                             cwd=ROOT,capture_output=True,text=True,timeout=15)
            if r.returncode or r.stdout.strip()!='true':
                raise SecretError('COOKIE_SECURE non applique a backend/auth. Reprendre activation.')
        print('OK : COOKIE_SECURE actif pour les deux services ; reconnectez les sessions navigateur')
    print('RECETTE HTTPS OK. Paiement Stripe test et connexion visage restent a verifier dans le navigateur.')
    print('Les flux HTTP de compatibilite et les flux internes Docker ne sont pas chiffres par cette etape.')


if __name__=='__main__':
    try:check()
    except (OSError,ValueError,KeyError,SecretError,subprocess.TimeoutExpired) as exc:
        message=str(exc) if isinstance(exc,SecretError) else 'Verifier certificat, confiance locale et services sans desactiver la verification TLS.'
        raise SystemExit('ECHEC : '+message) from None
