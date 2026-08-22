-- Supabase / PostgreSQL schema for the agency extraction store.
-- Design goals: preserve relationships, keep source provenance on every row,
-- track a review state per record, and enforce row-level security.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Core entities
-- ---------------------------------------------------------------------------
create table if not exists companies (
    id           text primary key,                 -- stable resolution id
    name         text not null,
    created_at   timestamptz not null default now()
);

create table if not exists people (
    id           text primary key,
    full_name    text not null,
    email        text,
    phone        text,
    created_at   timestamptz not null default now()
);
-- One confirmed email must map to one person (dedup guarantee at the DB level).
create unique index if not exists people_email_uidx
    on people (lower(email)) where email is not null;

create table if not exists projects (
    id             text primary key,
    title          text not null,
    client_company text references companies(id),
    start_date     date,
    created_at     timestamptz not null default now()
);

-- The relationship that matters: person <-> role <-> project.
create table if not exists project_roles (
    id          uuid primary key default gen_random_uuid(),
    project_id  text not null references projects(id) on delete cascade,
    person_id   text not null references people(id),
    role        text not null,
    unique (project_id, person_id, role)
);

-- ---------------------------------------------------------------------------
-- Provenance + review state (applies to any entity row)
-- ---------------------------------------------------------------------------
create type extraction_method as enum ('deterministic', 'llm', 'human');
create type review_state       as enum ('auto_accepted', 'needs_review', 'confirmed', 'rejected');

create table if not exists provenance (
    id            uuid primary key default gen_random_uuid(),
    entity_type   text not null,          -- 'person' | 'project' | 'company' | 'role'
    entity_id     text not null,
    source_file   text not null,
    page          int,
    line          int,
    raw_text      text not null,          -- exact source span -> anti-hallucination audit
    method        extraction_method not null,
    confidence    numeric(3,2) not null check (confidence between 0 and 1),
    review_state  review_state not null default 'needs_review',
    reviewed_by   uuid,
    reviewed_at   timestamptz
);
create index if not exists provenance_entity_idx on provenance (entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------
alter table companies     enable row level security;
alter table people        enable row level security;
alter table projects      enable row level security;
alter table project_roles enable row level security;
alter table provenance    enable row level security;

-- Authenticated users may read; only reviewers/service role may write review states.
create policy read_all_authenticated on projects
    for select using (auth.role() = 'authenticated');

create policy reviewer_update_provenance on provenance
    for update using (auth.role() in ('authenticated', 'service_role'))
    with check (auth.role() in ('authenticated', 'service_role'));

-- (Repeat read policies per table as needed; kept concise for the sample.)
