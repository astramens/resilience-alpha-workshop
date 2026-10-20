"""Real host acceptance test. Creates ONE fictional payment of EUR 0.01."""
import getpass
import http.cookiejar
import json
import secrets
from decimal import Decimal
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError

base = input('URL [http://localhost:3000] : ').strip().rstrip('/') or 'http://localhost:3000'
username = input('Identifiant [operateur] : ').strip() or 'operateur'
password = getpass.getpass('Mot de passe : ')
opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

def call(path, body=None):
    req = Request(base+'/api/'+path, data=None if body is None else json.dumps(body).encode(),
                  headers={'Content-Type':'application/json','Origin':base})
    with opener.open(req, timeout=20) as response:
        return json.load(response, parse_float=Decimal)

call('auth/login', {'username':username,'password':password})
before = Decimal(str(call('account')['balance']))
body = {'beneficiary_iban':'DEMO-RECETTE01','amount':'0.01','reference':'Recette réelle + rejeu','request_id':secrets.token_hex(24)}
first = call('pay',body)
second = call('pay',body)
after = Decimal(str(call('account')['balance']))
assert first['id'] == second['id'], 'Le rejeu a créé une autre transaction'
assert before-after == Decimal('.01'), 'Débit incorrect'
assert any(t['id']==first['id'] for t in call('transactions')), 'Transaction absente'
call('auth/logout',{})
try:
    call('account')
except HTTPError as e:
    assert e.code == 401
else:
    raise AssertionError('La session reste utilisable après déconnexion')
print('RECETTE OK : connexion, débit de 0,01 EUR, rejeu sans double débit, historique, déconnexion.')
