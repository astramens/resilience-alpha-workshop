"""HTTP smoke: fictitious client, checkout, replay, isolation and cancellation.
Creates a test customer and two audit events. Does not use the operator password.
"""
import http.cookiejar,json,secrets,urllib.error,urllib.request
from uuid import uuid4
base=(input('URL [http://localhost:3000] : ').strip() or 'http://localhost:3000').rstrip('/')
from urllib.parse import urlsplit
origin=urlsplit(base).scheme+'://'+urlsplit(base).netloc
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(path,body=None):
    r=urllib.request.Request(base+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':origin})
    with opener.open(r,timeout=30) as response:return json.load(response)
config=call('shop/payment-config')
if config['mode']=='stripe_test':
    if not config['ready']:raise SystemExit('Stripe test non configuré : exécutez python scripts/payment_setup.py. Aucun paiement lancé.')
    print('Stripe test configuré. La validation du paiement se fait dans le navigateur avec une carte de test.')
    raise SystemExit('Ouvrez la boutique : compte client > panier > Payer avec Stripe > retour et vérification du statut payé. Voir PAIEMENT_STRIPE.md.')
name='recette.' +secrets.token_hex(4)
call('customer/register',{'username':name,'display_name':'Studio recette fictif','password':secrets.token_urlsafe(24)})
p=next((p for p in call('shop/products') if p['stock']>0),None)
if not p:raise SystemExit('Aucun article en stock pour la recette.')
body={'request_id':str(uuid4()),'recipient':'Plateau recette','items':[{'product_id':p['id'],'quantity':1}],'accept_demo':True}
first=call('shop/orders',body);replay=call('shop/orders',body)
assert first['id']==replay['id'] and first['total_cents']==p['price_cents']
assert call('shop/products/'+str(p['id']))['stock']==p['stock']-1
assert any(o['id']==first['id'] for o in call('shop/orders'))
for _ in range(2):assert call(f"shop/orders/{first['id']}/cancel",{})['status']=='cancelled'
assert call('shop/products/'+str(p['id']))['stock']==p['stock']
call('customer/logout',{})
try:call('shop/orders')
except urllib.error.HTTPError as exc:assert exc.code==401
else:raise AssertionError('Session non révoquée')
print('RECETTE REARM OK : compte client, catalogue, commande simulée, rejeu unique, stock, annulation sans double restock et déconnexion.')
print('Commande test conservée dans l’historique :',first['number'])
