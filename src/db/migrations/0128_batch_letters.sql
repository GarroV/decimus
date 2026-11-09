-- 0128_batch_letters.sql
--
-- D739 (#1579): общее письмо партнёру по нескольким проверкам одной страны, зафиксированное
-- человеком. Одиночное письмо (`partner_letters`, 0019) остаётся как есть: общее — рядом,
-- а не вместо него.
--
-- Правило то же, что у одиночного: заготовку собирает код и пересобирает при каждом открытии,
-- в базу попадает только то, что человек прочитал, поправил и подтвердил. Запись заморожена —
-- передумал, фиксируется НОВОЕ письмо, и обе записи видно.
--
-- `batch_letters` — само письмо: пространство и страна, текст, язык, кто и когда. `ids_key` —
-- состав проверок строкой (идентификаторы по возрастанию через запятую): по нему окно письма
-- находит «то самое письмо для этого набора и языка». `batch_letter_inspections` — состав:
-- по нему карточка проверки показывает строку «вошла в общее письмо от <дата>».
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table batch_letters (
    id uuid primary key default gen_random_uuid(),
    tenant_code text not null references tenants (code),
    country text not null check (country ~ '^[A-Z]{2}$'),
    body text not null check (length(btrim(body)) > 0),
    lang text not null,
    ids_key text not null,
    saved_by text not null,
    created_at timestamptz not null default now()
);

create index batch_letters_by_set on batch_letters (ids_key, lang, created_at desc);

create table batch_letter_inspections (
    batch_letter_id uuid not null references batch_letters (id) on delete cascade,
    inspection_id uuid not null references inspections (id) on delete cascade,
    primary key (batch_letter_id, inspection_id)
);

create index batch_letter_inspections_by_inspection on batch_letter_inspections (inspection_id);

comment on table batch_letters is
    'Общее письмо партнёру по нескольким проверкам одной страны, зафиксированное человеком '
    '(D739). Заготовку по-прежнему собирает код; сюда попадает только подтверждённое.';
comment on column batch_letters.ids_key is
    'Состав проверок: идентификаторы по возрастанию через запятую. Ключ поиска письма '
    'для набора, не источник правды о составе — тот в batch_letter_inspections.';
comment on table batch_letter_inspections is
    'Какие проверки вошли в общее письмо; по строке карточка проверки ссылается на письмо.';

alter table batch_letters enable row level security;
alter table batch_letters force row level security;
create policy batch_letters_app_access on batch_letters
    for all to dodo_audit_app using (true) with check (true);
create policy batch_letters_frozen_once_written on batch_letters
    as restrictive for update
    using (false);

alter table batch_letter_inspections enable row level security;
alter table batch_letter_inspections force row level security;
create policy batch_letter_inspections_app_access on batch_letter_inspections
    for all to dodo_audit_app using (true) with check (true);
create policy batch_letter_inspections_frozen_once_written on batch_letter_inspections
    as restrictive for update
    using (false);

grant select, insert on batch_letters, batch_letter_inspections to dodo_audit_app;
grant select on batch_letters, batch_letter_inspections to dodo_audit_admin;
