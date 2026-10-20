"""Authentication primitives. No external JWT dependency or browser token storage."""
import hashlib
import hmac
import secrets
from decimal import Decimal


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def check_password(password, stored):
    return hmac.compare_digest(hash_password(password, stored.split(':')[0]), stored)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def valid_amount(value):
    amount = Decimal(str(value))
    return amount.is_finite() and 0 < amount <= 1000000 and amount == amount.quantize(Decimal('.01'))
