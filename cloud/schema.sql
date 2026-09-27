-- VEYRA cloud sync schema (run ONCE in the Supabase SQL editor).
--
-- The app keeps its SQLite database as the source of truth and mirrors a
-- single encrypted-at-rest JSON snapshot per shop into this table, so a new
-- install can recover the catalogue, the sales ledger and the business
-- profile. Access is scoped by an unguessable shop id that VEYRA generates
-- locally and shows under Settings > Cloud Sync.

create table if not exists public.veyra_sync (
    shop_id        text primary key,
    schema_version integer not null default 1,
    payload        jsonb not null,
    updated_by     text,
    updated_at     timestamptz not null default now()
);

alter table public.veyra_sync enable row level security;

drop policy if exists "veyra sync read" on public.veyra_sync;
create policy "veyra sync read"
    on public.veyra_sync for select
    to anon, authenticated
    using (true);

drop policy if exists "veyra sync write" on public.veyra_sync;
create policy "veyra sync write"
    on public.veyra_sync for insert
    to anon, authenticated
    with check (true);

drop policy if exists "veyra sync update" on public.veyra_sync;
create policy "veyra sync update"
    on public.veyra_sync for update
    to anon, authenticated
    using (true) with check (true);
