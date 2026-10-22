"""Add only recovery ledger/probe tables. Does not replay the shop migrations."""
from pathlib import Path
from rearm_migrate import run_sql
root=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    run_sql((root/'db/recovery.sql').read_text(encoding='utf-8'))
    print('Tables de suivi de reprise ajoutées. Clients, commandes, stocks et paiements conservés.')
