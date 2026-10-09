CREATE TABLE IF NOT EXISTS telegram_webhook_updates (
    update_id bigint PRIMARY KEY,
    received_at timestamptz NOT NULL DEFAULT now()
);
