-- 0051_units_registry.sql
--
-- Реестр пиццерий Dodo для экрана «Пиццерии на площадках» и автопоиска точек
-- в агрегаторах (D424, docs/17-aggregators.md). Источник — публичный API
-- Dodo (`unitinfo/all`): ежедневный сбор агрегаторов уже читает его по всем
-- странам IMF и теперь кладёт сюда то, что прочитал. Новая пиццерия появляется
-- сама, руками её заводить не нужно.
--
-- Это не `ratings.units` и не реестр проверок: здесь только то, что отдаёт
-- публичный API (код, имя, координаты, работает ли), — остальные таблицы схемы
-- ссылаются на пиццерию тем же `dodo_id` без внешнего ключа, как `agg.points`.
--
-- `first_seen` — когда пиццерия впервые попала в реестр. `null` — «была при
-- первом заполнении»: иначе первый же сбор пометил бы «новыми» всю сеть.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table agg.units (
    dodo_id text primary key check (dodo_id ~ '^[0-9a-f]{32}$'),
    country_code text not null check (country_code ~ '^[A-Z]{2}$'),
    name text not null,
    lat double precision not null,
    lng double precision not null,
    working boolean not null,
    first_seen date,
    last_seen date not null,
    updated_at timestamptz not null default now()
);
create index units_country_idx on agg.units (country_code);

grant select on agg.units to dodo_audit_app, dodo_audit_admin;
grant insert, update on agg.units to dodo_audit_app;
