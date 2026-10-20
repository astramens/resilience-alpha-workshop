"""Contract/security tests. PostgreSQL integration must also be tested on the host."""
import os
import sys
from pathlib import Path
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
os.environ['CAMERA_AGENT_TOKEN'] = 'test-only-camera-' + 'c'*40
os.environ['LED_DEVICE_TOKEN'] = 'test-only-led-' + 'd'*40
os.environ['DATABASE_URL'] = 'postgresql://unused'
os.environ['ALLOWED_ORIGINS'] = 'http://localhost:3000'
os.environ['OPERATOR_PASSWORD'] = 'test-only-password-long'
import main
from security import hash_password, check_password


def test_password_is_salted_and_checked():
    first = hash_password('a-long-test-password')
    second = hash_password('a-long-test-password')
    assert first != second
    assert check_password('a-long-test-password', first)
    assert not check_password('wrong', first)


@pytest.mark.parametrize('amount', ['0', '-1', '1.001', '1000001', 'NaN', 'Infinity'])
def test_reject_invalid_amounts(amount):
    with pytest.raises(ValidationError):
        main.Payment(beneficiary_iban='DEMO-CLIENT01', amount=amount, request_id='test-request-0001')


def test_cents_and_fictional_beneficiary():
    p = main.Payment(beneficiary_iban='demo-client01', amount='0.01', request_id='test-request-0001')
    assert p.amount == Decimal('.01') and p.beneficiary_iban == 'DEMO-CLIENT01'
    with pytest.raises(ValidationError):
        main.Payment(beneficiary_iban='FR761234567890', amount='1', request_id='test-request-0001')


def test_cross_site_login_blocked_before_database():
    c = TestClient(main.app)
    r = c.post('/api/auth/login', json={'username': 'operator', 'password': 'anything'}, headers={'Origin': 'http://evil.invalid'})
    assert r.status_code == 403


def test_protected_routes_reject_missing_session(monkeypatch):
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return None
    class Connection(Cursor):
        def cursor(self, **kwargs): return Cursor()
    monkeypatch.setattr(main, 'connection', Connection)
    c = TestClient(main.app)
    for route in ['account', 'transactions', 'monitor', 'auth/me']:
        assert c.get('/api/' + route).status_code == 401


def test_replay_returns_original_without_second_debit(monkeypatch):
    commands = []
    previous = {'id': 1, 'status': 'completed', 'created_at': '2026-10-19', 'amount': Decimal('1.50'), 'beneficiary_iban': 'DEMO-CLIENT01', 'reference': 'test'}
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None): commands.append(sql)
        def fetchone(self):
            return {'id': 1, 'balance': Decimal('50')} if 'FOR UPDATE' in commands[-1] else previous
    class Connection(Cursor):
        def cursor(self, **kwargs): return Cursor()
    monkeypatch.setattr(main, 'connection', Connection)
    p = main.Payment(beneficiary_iban='DEMO-CLIENT01', amount='1.50', reference='test', request_id='test-request-0001')
    assert main.pay(p, user={'id': 1, 'role': 'operator'})['id'] == 1
    assert not any('UPDATE accounts SET' in sql for sql in commands)
    with pytest.raises(main.HTTPException) as exc:
        main.pay(p.model_copy(update={'amount': Decimal('2')}), user={'id': 1, 'role': 'operator'})
    assert exc.value.status_code == 409




def test_viewer_cannot_pay():
    p = main.Payment(beneficiary_iban='DEMO-CLIENT01', amount='1', request_id='test-request-0002')
    with pytest.raises(main.HTTPException) as exc:
        main.pay(p,user={'id':2,'role':'viewer'})
    assert exc.value.status_code == 403
