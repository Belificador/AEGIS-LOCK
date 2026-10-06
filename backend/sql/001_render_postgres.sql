CREATE TABLE IF NOT EXISTS aegis_users (
    username text PRIMARY KEY,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('operator', 'admin')),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aegis_refresh_tokens (
    token_hash text PRIMARY KEY,
    username text NOT NULL REFERENCES aegis_users(username) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS aegis_refresh_tokens_expiry_idx
    ON aegis_refresh_tokens (expires_at);

CREATE TABLE IF NOT EXISTS security_events (
    event_id uuid PRIMARY KEY,
    source_id text NOT NULL,
    event jsonb NOT NULL,
    alerts jsonb NOT NULL DEFAULT '[]'::jsonb,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS security_events_received_at_idx
    ON security_events (received_at DESC);

CREATE INDEX IF NOT EXISTS security_events_source_id_idx
    ON security_events (source_id);

CREATE TABLE IF NOT EXISTS latest_telemetry (
    source_id text NOT NULL,
    event_type text NOT NULL,
    zone text NOT NULL,
    event jsonb NOT NULL,
    alerts jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, event_type, zone)
);
