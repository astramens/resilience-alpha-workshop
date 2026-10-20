CREATE TABLE IF NOT EXISTS accounts (
  id SERIAL PRIMARY KEY,
  account_number VARCHAR(32) NOT NULL UNIQUE,
  owner_name VARCHAR(160) NOT NULL,
  balance NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
  id BIGSERIAL PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  beneficiary_iban VARCHAR(64) NOT NULL,
  amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
  reference VARCHAR(255),
  status VARCHAR(24) NOT NULL DEFAULT 'completed',
  latency_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO accounts (account_number, owner_name, balance)
VALUES ('4821', 'Compte principal', 48294.60)
ON CONFLICT (account_number) DO NOTHING;

CREATE INDEX IF NOT EXISTS transactions_created_at_idx ON transactions (created_at DESC);

CREATE TABLE IF NOT EXISTS operators (
  id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, operator_id INTEGER NOT NULL REFERENCES operators(id), expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
  bucket TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS request_id VARCHAR(80) UNIQUE;
