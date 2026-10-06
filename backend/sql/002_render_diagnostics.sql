CREATE TABLE IF NOT EXISTS temporary_pins (
    id uuid PRIMARY KEY,
    door_name text NOT NULL,
    pin_code text NOT NULL,
    pin_hash text NOT NULL,
    target_user text NOT NULL,
    created_by text NOT NULL REFERENCES aegis_users(username),
    expires_at timestamptz NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS temporary_pins_active_door_expiry_idx
    ON temporary_pins (door_name, expires_at DESC)
    WHERE is_active;

CREATE INDEX IF NOT EXISTS temporary_pins_hash_lookup_idx
    ON temporary_pins (door_name, pin_hash)
    WHERE is_active;

CREATE TABLE IF NOT EXISTS error_logs (
    id bigserial PRIMARY KEY,
    error_type text NOT NULL,
    description text NOT NULL,
    timestamp timestamptz NOT NULL DEFAULT now(),
    duration_ms bigint CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS error_logs_timestamp_idx
    ON error_logs (timestamp DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id bigserial PRIMARY KEY,
    action text NOT NULL,
    performed_by text NOT NULL,
    timestamp timestamptz NOT NULL DEFAULT now(),
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_logs_timestamp_idx
    ON audit_logs (timestamp DESC);

CREATE INDEX IF NOT EXISTS audit_logs_action_idx
    ON audit_logs (action, timestamp DESC);

CREATE TABLE IF NOT EXISTS energy_state (
    source_id text NOT NULL,
    zone text NOT NULL,
    energy_kwh double precision NOT NULL DEFAULT 0 CHECK (energy_kwh >= 0),
    last_power_kw double precision NOT NULL DEFAULT 0 CHECK (last_power_kw >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, zone)
);
