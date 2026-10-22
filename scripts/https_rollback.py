"""Restore only managed HTTPS settings from the encrypted pre-change snapshot."""
import json
from https_setup import ROOT, tls_home, load_state, parse_env, update_env, overlay, atomic_private, MANAGED
import secrets_vault as vault
from secret_permissions import SecretError, private


def rollback():
    state=load_state();path=ROOT/'.env';private(path)
    raw=path.read_bytes();current=parse_env(raw)
    if any(current.get(k)!=v for k,v in state['expected'].items()):
        raise SecretError('Un parametre gere HTTPS a ete modifie : retour automatique refuse.')
    target=ROOT/'docker-compose.override.yml'
    if target.read_bytes()!=overlay():raise SecretError('Surcharge Compose modifiee : aucun changement.')
    # Recover previous managed values from authenticated ciphertext, not state JSON.
    from pathlib import Path
    backup=Path(state['env_backup']);private(backup)
    previous=vault.decrypt(backup.read_bytes(),vault.recipient())
    old=parse_env(previous['.env']);values={k:old.get(k) for k in MANAGED}
    vault.seal()
    atomic_private(path,update_env(raw,values))
    target.unlink()
    atomic_private(tls_home()/'state-rolled-back.json',json.dumps(state).encode())
    (tls_home()/'state.json').unlink()
    print('Parametres HTTPS precedents restaures. Autres secrets, donnees, certificats et confiance conserves.')
    print('Appliquer : docker compose up -d --no-deps --force-recreate backend auth edge')
    print('Puis : python scripts/secrets_vault.py seal')


if __name__=='__main__':
    try:rollback()
    except (OSError,ValueError,KeyError,SecretError):
        raise SystemExit('ECHEC : retour HTTPS non applique ou incomplet. Ne pas supprimer de cle ou de donnees ; verifier localement la configuration.') from None
