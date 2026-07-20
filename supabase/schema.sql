-- Run once in Supabase: SQL Editor → New query → paste → Run

create table if not exists specialty_tools_store (
    store_key text primary key,
    data jsonb not null,
    updated_at timestamptz default now()
);
