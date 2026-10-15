-- 0074_trips.sql
--
-- Поездки на «Календаре» (D497, D505, D506): кто едет, куда, с какого по какое
-- число и план по дням — время, что происходит, пиццерия, заметка.
--
-- РАЗДЕЛЕНИЕ ПРОСТРАНСТВ (D505, владелец: «здесь крайне важно все разделить»).
-- Поездки и их планы — строго своего пространства, и на ЧТЕНИЕ тоже: в отличие
-- от проверок (УК читает всю сеть, D283), УК чужих поездок не видит, партнёр —
-- ни поездок УК, ни других партнёров. Держит сама база, а не только запрос:
--
--   * у обеих таблиц своя колонка `tenant_code`, и единственная политика роли
--     приложения пускает строку, только если она пространства обращения
--     (`decimus_space_writes`, `0062`: своё или служебное `*`); не поставленное
--     пространство — ошибка базы, а не пустой ответ;
--   * шаг плана ссылается на поездку парой (id, пространство): шаг не может
--     принадлежать поездке другого пространства;
--   * исполнитель-пользователь и автор ссылаются на учётку тоже парой (id,
--     пространство): в поездку нельзя вписать учётку чужого пространства;
--   * пиццерия в шаге — только из охвата пространства (`decimus_space_sees_unit`):
--     партнёр не впишет точку чужой страны даже подделанной формой.
--
-- Других прав, кроме роли приложения, на таблицы нет: ни администратор истории,
-- ни сервисы с ключом API их не читают.
--
-- Раннер оборачивает файл в одну транзакцию сам.

-- Учётка ссылается парой (id, пространство) — нужен уникальный ключ на эту пару.
create unique index web_users_id_tenant_idx on web_users (id, tenant_code);

create table trips (
    id uuid primary key default gen_random_uuid(),
    tenant_code text not null references tenants (code),
    -- Кто едет — как вписано (D506): имя любого человека или логин учётки.
    executor_name text not null
        check (char_length(btrim(executor_name)) between 1 and 120),
    -- Учётка исполнителя, если выбран пользователь админки; null — вписан текстом.
    executor_user_id uuid,
    country text check (country is null or country ~ '^[A-Z]{2}$'),
    date_from date not null,
    date_to date not null,
    status text not null default 'planned' check (status in ('planned', 'done', 'cancelled')),
    note text not null default '' check (char_length(note) <= 2000),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- Поездка не длиннее двух месяцев: дальше это уже не поездка, а опечатка в дате.
    check (date_to >= date_from and date_to <= date_from + 62),
    unique (id, tenant_code),
    foreign key (executor_user_id, tenant_code) references web_users (id, tenant_code),
    foreign key (created_by, tenant_code) references web_users (id, tenant_code)
);

create index trips_space_dates_idx on trips (tenant_code, date_from, date_to);

comment on table trips is
    'Поездки «Календаря» (D505, D506): только своего пространства, и на чтение тоже.';

create table trip_steps (
    id uuid primary key default gen_random_uuid(),
    trip_id uuid not null,
    tenant_code text not null,
    day date not null,
    -- Время необязательно: «весь день», «утром» пишутся текстом.
    at time,
    kind text not null check (kind in ('road', 'inspection', 'meeting', 'other')),
    unit_id uuid references units (id),
    body text not null default '' check (char_length(body) <= 500),
    created_at timestamptz not null default now(),
    check (kind <> 'inspection' or unit_id is not null),
    foreign key (trip_id, tenant_code) references trips (id, tenant_code) on delete cascade
);

create index trip_steps_trip_idx on trip_steps (trip_id, day, at);

comment on table trip_steps is
    'План поездки по дням (D506): время, что происходит, пиццерия, заметка. '
    'Пространство — то же, что у поездки (ссылка парой).';

-- Видит ли пространство обращения пиццерию `точка`: УК и служебная работа —
-- весь справочник, партнёр — точки своих стран (D289).
create function decimus_space_sees_unit(точка uuid) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select case decimus_space()
        when '*' then true
        when 'HQ' then true
        else exists (
            select 1
              from units u
              join space_countries s on s.country = u.country
             where u.id = точка and s.tenant_code = decimus_space()
        )
    end
$$;

alter table trips enable row level security;
alter table trip_steps enable row level security;

-- Одна политика на всё: читать, вписывать, править и удалять — только своё.
create policy trips_own_space on trips
    for all to dodo_audit_app
    using (decimus_space_writes(tenant_code))
    with check (decimus_space_writes(tenant_code));

create policy trip_steps_own_space on trip_steps
    for all to dodo_audit_app
    using (decimus_space_writes(tenant_code))
    with check (
        decimus_space_writes(tenant_code)
        and (unit_id is null or decimus_space_sees_unit(unit_id))
    );

grant select, insert, update, delete on trips, trip_steps to dodo_audit_app;
