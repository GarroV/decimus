-- Language-specific PDFs and reproducible drafts; originals remain immutable.
alter table reports add column lang text check (lang ~ '^[a-z]{2}$');
create index reports_by_language on reports (inspection_id, lang, created_at desc);

create table inspection_document_cache (
    inspection_id uuid not null references inspections(id) on delete cascade,
    lang text not null check (lang ~ '^[a-z]{2}$'),
    kind text not null check (kind in ('translation', 'letter')),
    fingerprint text not null check (fingerprint ~ '^[0-9a-f]{64}$'),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    primary key (inspection_id, lang, kind, fingerprint)
);
alter table inspection_document_cache enable row level security;
alter table inspection_document_cache force row level security;
create policy document_cache_read on inspection_document_cache
    for select to dodo_audit_app, dodo_audit_admin
    using (exists (select 1 from inspections i where i.id = inspection_id));
create policy document_cache_add on inspection_document_cache
    for insert to dodo_audit_app
    with check (exists (select 1 from inspections i where i.id = inspection_id
        and i.origin <> 'legacy' and i.retracted_at is null));
grant select, insert on inspection_document_cache to dodo_audit_app;
grant select on inspection_document_cache to dodo_audit_admin;
