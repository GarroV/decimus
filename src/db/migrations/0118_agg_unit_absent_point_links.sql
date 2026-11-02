-- 0118_agg_unit_absent_point_links.sql
--
-- Ручные решения по охвату агрегаторов (D700): отметка «пиццерии нет на площадке»
-- и закреплённая привязка точки к пиццерии (docs/17-aggregators.md).
--
-- Охват различает «пиццерии на площадке нет» и «не привязали». У поисковых
-- площадок (Wolt, Bolt Food, Яндекс Еда, Yemeksepeti, Trendyol Go, Pyszne) «нет»
-- следует из поиска у координат пиццерии. У площадок «по известной точке» (Glovo,
-- Chowdeck, Migros) поиска нет, поэтому «нет на площадке» — решение человека:
-- `agg.unit_absent`. Закреплённая привязка `agg.point_links` нужна там, где
-- площадка плохо геокодирует адрес и точка стоит дальше `MAX_LINK_M` от пиццерии:
-- ночной сбор берёт закреплённые пары первыми, иначе он бы их отменял.
--
-- Внешних ключей на `agg.points` и `agg.units` нет намеренно, как у самих точек:
-- точка может пропасть с витрины, а закрепление останется до снятия руками.
-- Права — как у `agg.requests` (0053): пишет роль приложения (веб, бот).
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table agg.unit_absent (
    aggregator text not null check (aggregator ~ '^[a-z][a-z0-9_]*$'),
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    marked_by text not null check (length(btrim(marked_by)) between 1 and 200),
    marked_at timestamptz not null default now(),
    primary key (aggregator, dodo_id)
);

create table agg.point_links (
    aggregator text not null check (aggregator ~ '^[a-z][a-z0-9_]*$'),
    point_key text not null,
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    linked_by text not null check (length(btrim(linked_by)) between 1 and 200),
    linked_at timestamptz not null default now(),
    primary key (aggregator, point_key),
    unique (aggregator, dodo_id)
);

grant select on agg.unit_absent, agg.point_links to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on agg.unit_absent, agg.point_links to dodo_audit_app;
