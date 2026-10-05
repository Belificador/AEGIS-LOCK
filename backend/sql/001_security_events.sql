create table if not exists public.security_events (
    event_id uuid primary key,
    source_id text not null,
    event jsonb not null,
    alerts jsonb not null default '[]'::jsonb,
    received_at timestamptz not null default now()
);

create index if not exists security_events_received_at_idx
    on public.security_events (received_at desc);

create index if not exists security_events_source_id_idx
    on public.security_events (source_id);

alter table public.security_events enable row level security;

-- The API writes with its server-side service role key. No public/anon policies
-- are created, so browsers cannot read or write this table directly.
