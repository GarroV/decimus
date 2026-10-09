-- 0045_maps_link.sql
--
-- Связь филиала Pointer с пиццерией Dodo (docs/09-pointer-api.md). Кода нашей
-- сети у Pointer нет, поэтому связь ищется по координатам: ближайшая пиццерия
-- из публичного API Dodo (`publicapi.dodois.io/<страна>/api/v1/unitinfo/all`),
-- не дальше порога. `dodo_id` — тот же код, что у `ratings.units.dodo_id`
-- (32 hex). Внешнего ключа нет намеренно: пиццерия на карте бывает, а в
-- рейтингах её нет (закрыта, ещё не попала в выгрузку).
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table maps.companies
    add column dodo_id text check (dodo_id ~ '^[0-9a-f]{32}$'),
    add column dodo_name text,
    add column link_distance_m integer check (link_distance_m >= 0),
    add column linked_at timestamptz;

create index companies_dodo_idx on maps.companies (dodo_id);

grant update (dodo_id, dodo_name, link_distance_m, linked_at) on maps.companies to dodo_audit_app;
