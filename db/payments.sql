BEGIN;
ALTER TABLE shop_orders DROP CONSTRAINT IF EXISTS shop_orders_status_check;
ALTER TABLE shop_orders ADD CONSTRAINT shop_orders_status_check CHECK(status IN ('awaiting_payment','confirmed','preparing','ready','collected','cancelled'));
CREATE TABLE IF NOT EXISTS shop_order_payments (
 order_id BIGINT PRIMARY KEY REFERENCES shop_orders(id),
 attempt UUID NOT NULL UNIQUE,
 session_id TEXT UNIQUE,
 checkout_url TEXT,
 payment_intent TEXT,
 state VARCHAR(24) NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','paid','expired','cancelled','refunded')),
 expires_at BIGINT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMIT;
