-- 0046_unit_profiles.sql
--
-- Справочные сведения о пиццерии из «Свода пиццерий» девелопмента (D374–D376):
-- адрес, партнёр и его почта, статус, даты запуска ресторана и доставки,
-- закрытие, помещение. Файл свода живёт вне git; сюда он попадает загрузкой
-- (`python -m src.ratings.svod <файл>`), повтор перезаписывает строку.
--
-- Ключ — (страна, нормализованное имя): кода в своде нет, имя пиццерии —
-- единственное, по чему его строки опознаются. Связь с остальным продуктом —
-- кодом: `dodo_id` (32 hex, тот же, что у `ratings.units` и `maps.companies`)
-- проставляет загрузка по публичному API Dodo, а точке справочника `units`
-- этот же код ложится в `units.code`. Пиццерия на стройке кода ещё не имеет.
--
-- `partner_email` — личные данные (D375): только эта база, в репозиторий и
-- журналы не попадает. `extra` — остальные колонки свода как есть, «на
-- будущее»; колонки с именами сотрудников загрузка отбрасывает.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table unit_profiles (
    country_code text not null check (country_code ~ '^[A-Z]{2}$'),
    name_normalized text not null,
    name text not null,
    dodo_id text unique check (dodo_id ~ '^[0-9a-f]{32}$'),
    stage text not null check (stage in ('open', 'paused', 'pipeline', 'closed')),
    status text not null,
    city text,
    address text,
    partner text,
    partner_email text,
    restaurant_on date,
    delivery_on date,
    revenue_on date,
    closed_on date,
    total_area numeric,
    seats integer,
    extra jsonb not null default '{}',
    loaded_at timestamptz not null default now(),
    primary key (country_code, name_normalized)
);

create index unit_profiles_dodo_idx on unit_profiles (dodo_id);

grant select on unit_profiles to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on unit_profiles to dodo_audit_app;
