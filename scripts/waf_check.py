"""Small, read-only lab checks. Does not send card data or modify orders."""
import json,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlsplit

def request(base,path,body=None):
    headers={'User-Agent':'REARM-WAF-RECIPE/1.0','Accept':'application/json'}
    if body is not None:headers.update({'Content-Type':'application/json','stripe-signature':'t=1,v1=invalid-recipe-signature'})
    req=Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    try:
        with urlopen(req,timeout=20) as response:return response.status,response.headers,response.read(4096)
    except HTTPError as exc:return exc.code,exc.headers,exc.read(4096)

def run(base):
    endpoint='/api/shop/products'
    ok=True
    cases=[('Catalogue normal','atelier',200),('Charge XSS inerte','<script>alert(1)</script>',403),('Charge SQLi inerte',"1' OR '1'='1'-- -",403),('Catalogue après contrôles','atelier',200)]
    for label,payload,expected in cases:
        code,headers,_=request(base,endpoint+'?'+urlencode({'waf_probe':payload}))
        passed=code==expected and headers.get('X-Rearm-Inspection')=='active'
        print(('OK' if passed else 'ECHEC')+' : '+label+' — HTTP '+str(code))
        ok=ok and passed
    # Must reach the backend signature validator, not be rejected by CRS or Origin middleware.
    code,headers,raw=request(base,'/api/shop/payments/webhook',{'type':'checkout.session.completed','livemode':False,'data':{'object':{'id':'cs_test_readonlyprobe','metadata':{'note':'Recette innocente, aucun paiement'}}}})
    try:detail=json.loads(raw).get('detail','')
    except (ValueError,AttributeError):detail=''
    passed=code==400 and detail=='Signature de notification invalide.' and headers.get('X-Rearm-Inspection')=='active'
    print(('OK' if passed else 'ECHEC')+' : webhook atteint le contrôle de signature — HTTP '+str(code))
    return ok and passed

if __name__=='__main__':
    base=(input('URL [http://localhost:3000] : ').strip() or 'http://localhost:3000').rstrip('/')
    parsed=urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.path != '' or parsed.query or parsed.fragment:raise SystemExit('Indiquez uniquement l’origine du laboratoire, sans chemin ni identifiant.')
    try:ok=run(base)
    except (URLError,TimeoutError,OSError) as exc:raise SystemExit('Laboratoire inaccessible : '+type(exc).__name__)
    if not ok:raise SystemExit('Recette incomplète : garder les résultats pour le diagnostic. Aucun réglage modifié.')
    print('RECETTE WAF OK : catalogue accessible, XSS/SQLi bloquées, webhook transmis au validateur. Caméra et paiement de test restent à vérifier dans leur parcours normal.')
