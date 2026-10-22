BEGIN;
CREATE TABLE IF NOT EXISTS rearm_recovery_probe (
 id INTEGER PRIMARY KEY CHECK(id=1), marker TEXT NOT NULL
);
INSERT INTO rearm_recovery_probe(id,marker) VALUES (1,'initial') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS rearm_recovery_incidents (
 ref VARCHAR(32) PRIMARY KEY,
 reason VARCHAR(80) NOT NULL CHECK(reason IN ('ml_anomaly_with_confirmed_health_failure','availability_fallback_six_failed_health_probes')),
 state VARCHAR(32) NOT NULL CHECK(state IN ('remediation','technical_recovered','failed','business_verified')),
 opened_at TIMESTAMPTZ NOT NULL,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 technical_at TIMESTAMPTZ,
 closed_at TIMESTAMPTZ,
 proof_order_id BIGINT REFERENCES shop_orders(id),
 CHECK((state='business_verified')=(proof_order_id IS NOT NULL AND closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS rearm_recovery_state_idx ON rearm_recovery_incidents(state,technical_at);
COMMIT;
