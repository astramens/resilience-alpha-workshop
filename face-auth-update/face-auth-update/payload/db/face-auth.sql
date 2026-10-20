BEGIN;
ALTER TABLE operators ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'operator';
ALTER TABLE operators ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE operators ADD COLUMN IF NOT EXISTS face_features JSONB;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS face_verified BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS face_auth_state (
  id INTEGER PRIMARY KEY CHECK(id=1), data JSONB NOT NULL DEFAULT '{}'::jsonb
);
INSERT INTO face_auth_state(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS face_auth_migrations (version INTEGER PRIMARY KEY);
-- Revoke password-only sessions once, when this migration is first installed.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM face_auth_migrations WHERE version=1) THEN
   DELETE FROM sessions;
   INSERT INTO face_auth_migrations(version) VALUES(1);
 END IF;
END $$;
COMMIT;
