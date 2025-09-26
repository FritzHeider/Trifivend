-- Trifivend Voice Agent schema + indexes (idempotent)

-- Use pgcrypto for gen_random_uuid()
create extension if not exists pgcrypto;

-- ===========================
-- 1) LEADS
-- ===========================
create table if not exists public.leads (
  id              uuid primary key default gen_random_uuid(),
  phone           text not null,
  name            text default ''::text,
  property_type   text default ''::text,
  location_area   text default ''::text,
  callback_offer  text default ''::text,
  meta            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

-- If an old table existed without columns, patch it
do $$ begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='leads' and column_name='phone') then
    alter table public.leads add column phone text not null default '';
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='leads' and column_name='meta') then
    alter table public.leads add column meta jsonb not null default '{}'::jsonb;
  end if;
end $$;

create unique index if not exists ux_leads_phone         on public.leads (phone);
create index  if not exists idx_leads_created_at         on public.leads (created_at);

-- ===========================
-- 2) CALLS
-- ===========================
create table if not exists public.calls (
  id           uuid primary key default gen_random_uuid(),
  lead_id      uuid references public.leads (id) on delete set null,
  call_sid     text not null,
  from_number  text,
  to_number    text,
  status       text,
  started_at   timestamptz,
  ended_at     timestamptz,
  meta         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

-- Patch missing cols if table pre-existed
do $$ begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='calls' and column_name='call_sid') then
    alter table public.calls add column call_sid text;
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='calls' and column_name='meta') then
    alter table public.calls add column meta jsonb not null default '{}'::jsonb;
  end if;
end $$;

create unique index if not exists ux_calls_call_sid      on public.calls (call_sid);
create index  if not exists idx_calls_lead_id            on public.calls (lead_id);
create index  if not exists idx_calls_created_at         on public.calls (created_at);

-- ===========================
-- 3) CALL EVENTS
-- ===========================
create table if not exists public.call_events (
  id          uuid primary key default gen_random_uuid(),
  call_sid    text not null,
  event       text not null,
  created_at  timestamptz not null default now(),
  payload     jsonb not null default '{}'::jsonb
);

-- Patch missing cols if table pre-existed
do $$ begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='call_events' and column_name='call_sid') then
    alter table public.call_events add column call_sid text;
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='call_events' and column_name='payload') then
    alter table public.call_events add column payload jsonb not null default '{}'::jsonb;
  end if;
end $$;

create index if not exists idx_call_events_call_sid      on public.call_events (call_sid);
create index if not exists idx_call_events_created_at    on public.call_events (created_at);

-- Optional FK if you *always* insert calls before events:
-- alter table public.call_events
--   add constraint fk_call_events_call_sid
--   foreign key (call_sid) references public.calls (call_sid);

-- ===========================
-- 4) CONVERSATIONS
-- ===========================
create table if not exists public.conversations (
  id          uuid primary key default gen_random_uuid(),
  user_input  text not null,
  bot_reply   text not null,
  call_sid    text,
  lead_id     uuid references public.leads (id) on delete set null,
  meta        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

-- Patch missing cols
do $$ begin
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='conversations' and column_name='call_sid') then
    alter table public.conversations add column call_sid text;
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='conversations' and column_name='meta') then
    alter table public.conversations add column meta jsonb not null default '{}'::jsonb;
  end if;
end $$;

create index if not exists idx_conversations_call_sid    on public.conversations (call_sid);
create index if not exists idx_conversations_created_at  on public.conversations (created_at);

-- ===========================
-- 5) RLS switch (keep strict)
-- ===========================
alter table public.leads          enable row level security;
alter table public.calls          enable row level security;
alter table public.call_events    enable row level security;
alter table public.conversations  enable row level security;

-- No public read policies by default. Your backend uses the service role key and bypasses RLS.