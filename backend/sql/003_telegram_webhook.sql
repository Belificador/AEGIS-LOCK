CREATE TABLE IF NOT EXISTS telegram_webhook_updates (
    update_id bigint PRIMARY KEY,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS telegram_webhook_updates_received_at_idx
    ON telegram_webhook_updates (received_at DESC);
