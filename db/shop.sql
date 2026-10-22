BEGIN;
CREATE TABLE IF NOT EXISTS shop_customers (
 id BIGSERIAL PRIMARY KEY,
 username VARCHAR(80) NOT NULL UNIQUE,
 display_name VARCHAR(80) NOT NULL,
 password_hash TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS shop_sessions (
 token_hash TEXT PRIMARY KEY,
 customer_id BIGINT NOT NULL REFERENCES shop_customers(id),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_products (
 id BIGSERIAL PRIMARY KEY,
 sku VARCHAR(32) UNIQUE NOT NULL,
 name VARCHAR(100) NOT NULL,
 category VARCHAR(32) NOT NULL CHECK(category IN ('pistolets','fusils','arbaletes','lames','effets')),
 description VARCHAR(2000) NOT NULL,
 grade VARCHAR(16) NOT NULL CHECK(grade IN ('A','B','C')),
 price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 100 AND 1000000),
 stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 10000),
 active BOOLEAN NOT NULL DEFAULT TRUE,
 image VARCHAR(64) NOT NULL,
 workshop_note VARCHAR(1000) NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS shop_orders (
 id BIGSERIAL PRIMARY KEY,
 customer_id BIGINT NOT NULL REFERENCES shop_customers(id),
 request_id UUID NOT NULL,
 fingerprint TEXT NOT NULL,
 recipient VARCHAR(80) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'confirmed' CHECK(status IN ('confirmed','preparing','ready','collected','cancelled')),
 total_cents INTEGER NOT NULL CHECK(total_cents>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(customer_id,request_id)
);
CREATE TABLE IF NOT EXISTS shop_order_items (
 order_id BIGINT NOT NULL REFERENCES shop_orders(id),
 product_id BIGINT NOT NULL REFERENCES shop_products(id),
 name VARCHAR(100) NOT NULL,
 sku VARCHAR(32) NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 10),
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents>0),
 PRIMARY KEY(order_id,product_id)
);
CREATE TABLE IF NOT EXISTS shop_audit (
 id BIGSERIAL PRIMARY KEY,
 actor VARCHAR(100) NOT NULL,
 action VARCHAR(80) NOT NULL,
 target VARCHAR(100) NOT NULL,
 detail JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS shop_orders_customer_idx ON shop_orders(customer_id,created_at DESC);
CREATE INDEX IF NOT EXISTS shop_audit_date_idx ON shop_audit(created_at DESC);
COMMIT;
