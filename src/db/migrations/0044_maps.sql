-- 0044_maps.sql
--
-- Оценки пиццерий на картах (Google, Яндекс и др.) из Pointer API
-- (docs/09-pointer-api.md). Бот раз в сутки забирает сети и филиалы с текущими
-- оценками и кладёт сюда снимок дня: история копится у нас, Pointer отдаёт
-- только «сейчас».
--
-- Страна — `country_code` филиала (ISO-2, как у рейтингов). Связь филиала с
-- нашей пиццерией — отдельная задача: кода нашей сети у Pointer нет.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema maps;
grant usage on schema maps to dodo_audit_app, dodo_audit_admin;

create table maps.companies (
    uuid uuid primary key,
    network_uuid uuid,
    network_name text,
    name text not null,
    country_code text check (country_code ~ '^[A-Z]{2}$'),
    city text,
    address text,
    lat double precision,
    lng double precision,
    status_type_id integer,
    pointer_link text,
    seen_at timestamptz not null default now()
);
create index companies_country_idx on maps.companies (country_code);

-- Снимок оценки на дату, которую назвал Pointer (`ratings[].date`).
create table maps.ratings (
    company_uuid uuid not null references maps.companies (uuid),
    provider_id integer not null,
    on_date date not null,
    avg_rating numeric(3, 2) not null check (avg_rating between 0 and 5),
    ratings_count integer not null check (ratings_count >= 0),
    loaded_at timestamptz not null default now(),
    primary key (company_uuid, provider_id, on_date)
);

-- Журнал загрузок: когда, чем кончилась, сколько легло. Пустой журнал за
-- сутки — повод разбираться, а не тишина.
create table maps.loads (
    id bigserial primary key,
    at timestamptz not null default now(),
    outcome text not null check (outcome in ('ok', 'failed')),
    companies integer not null default 0,
    ratings integer not null default 0,
    error text
);

grant select on all tables in schema maps to dodo_audit_app, dodo_audit_admin;
grant insert, update on maps.companies, maps.ratings to dodo_audit_app;
grant insert on maps.loads to dodo_audit_app;
grant usage on sequence maps.loads_id_seq to dodo_audit_app;

-- Новый блок страницы рейтингов (D368): компоновка его покажет в конце.
alter table ratings.layout drop constraint layout_block_check;
alter table ratings.layout add constraint layout_block_check
    check (block in ('scores', 'violations', 'top', 'hard', 'risk', 'maps'));
insert into ratings.layout (block, position, updated_by) values ('maps', 5, 'migration 0044');
