-- 0063_ratings_sheet.sql
--
-- Общая таблица контроля «база рейтингов» как источник РС и РКО (D464,
-- docs/15-ratings.md). Что нужно схеме:
--
-- 1. Оценка несёт флаги листа: нарушение Д3, критичное, обнуление и их названия.
--    Ложатся рядом с баллом; старые строки получают «нет».
-- 2. Собираемость РКО (отчёты ресторана и доставки за неделю) — своя таблица.
-- 3. Журнал загрузок узнаёт канал `sync` (забор таблицы самим decimus) и четыре
--    новых формата листов.
-- 4. Состояние забора по листам (`sheet_sync`) и заявки «Забрать сейчас»
--    (`sheet_sync_requests`, как `agg.requests`): забирает бот, просят веб и
--    Claude.
--
-- Новые таблицы схемы `ratings` получают построчные политики здесь же: цикл
-- в `0062` обошёл только таблицы, существовавшие тогда. Правила те же — читать
-- всем, писать роли приложения только УК и служебной работе.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table ratings.scores
    add column d3 boolean not null default false,
    add column d3_name text,
    add column critical boolean not null default false,
    add column critical_name text,
    add column zeroing boolean not null default false,
    add column zeroing_name text;

alter table ratings.imports drop constraint imports_channel_check;
alter table ratings.imports add constraint imports_channel_check
    check (channel in ('web', 'mcp', 'seed', 'sync'));
alter table ratings.imports drop constraint imports_format_check;
alter table ratings.imports add constraint imports_format_check check (
    format in (
        'rko-violations', 'rko-evaluations', 'rs-checkups', 'snapshot', 'sheet-scores',
        'base-scores', 'base-collection', 'base-rko-violations', 'base-rs-violations'
    )
);

create table ratings.collection (
    unit_dodo_id text not null references ratings.units (dodo_id),
    period_id bigint not null references ratings.periods (id),
    restaurant_reports integer not null check (restaurant_reports >= 0),
    delivery_reports integer not null check (delivery_reports >= 0),
    import_id bigint not null references ratings.imports (id),
    updated_at timestamptz not null default now(),
    primary key (unit_dodo_id, period_id)
);
create index collection_period_idx on ratings.collection (period_id);

-- Одна строка на лист: когда смотрели, чем кончилось, какой файл лёг последним.
-- `unchanged` — лист не менялся с прошлого раза (тот же sha256), журнал не пишется.
create table ratings.sheet_sync (
    tab text primary key check (length(btrim(tab)) between 1 and 60),
    checked_at timestamptz not null default now(),
    outcome text not null check (outcome in ('loaded', 'unchanged', 'failed')),
    sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
    import_id bigint references ratings.imports (id),
    note text check (note is null or length(note) <= 2000)
);

create table ratings.sheet_sync_requests (
    id bigint generated always as identity primary key,
    requested_at timestamptz not null default now(),
    requested_by text not null check (length(btrim(requested_by)) between 1 and 200),
    done_at timestamptz,
    outcome text check (outcome in ('ok', 'failed')),
    error text check (error is null or length(error) <= 500),
    check ((done_at is null) = (outcome is null))
);
create unique index sheet_sync_requests_one_open_idx
    on ratings.sheet_sync_requests ((true)) where done_at is null;

grant select on ratings.collection, ratings.sheet_sync, ratings.sheet_sync_requests
    to dodo_audit_app, dodo_audit_admin;
grant insert, update on ratings.collection, ratings.sheet_sync to dodo_audit_app;
grant insert on ratings.sheet_sync_requests to dodo_audit_app;
grant update (done_at, outcome, error) on ratings.sheet_sync_requests to dodo_audit_app;
grant usage on sequence ratings.sheet_sync_requests_id_seq to dodo_audit_app;
-- Сверка строк по ключу листа удаляет только заменяемое: у собираемости права
-- удалять нет — строка периода перезаписывается, а не пропадает.

do $$
declare
    т text;
begin
    foreach т in array array['collection', 'sheet_sync', 'sheet_sync_requests']
    loop
        execute format('alter table ratings.%I enable row level security', т);
        execute format(
            'create policy %I on ratings.%I for select using (true)', т || '_seen_by_all', т);
        execute format(
            'create policy %I on ratings.%I for insert to dodo_audit_app '
            'with check (decimus_space_is_hq())', т || '_hq_inserts', т);
        execute format(
            'create policy %I on ratings.%I for update to dodo_audit_app '
            'using (decimus_space_is_hq()) with check (decimus_space_is_hq())',
            т || '_hq_updates', т);
    end loop;
end
$$;
