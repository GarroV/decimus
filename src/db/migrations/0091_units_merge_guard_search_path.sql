-- 0091_units_merge_guard_search_path.sql
--
-- Сторож слияния точек (`units_merge_guard`, 0079) — функция владельца (`security
-- definer`) — был заведён с путём поиска `pg_catalog, public` без `pg_temp`. Без
-- `pg_temp` ПОСЛЕДНИМ в пути временная схема сеанса ищется первой, и вызвавший мог бы
-- подменить временной таблицей `inspections` или `units` ту, что читает сторож
-- (то же, что закрыла 0033 для остальных функций владельца).
--
-- Функция пересоздаётся тем же телом: путь поиска — `pg_catalog, public, pg_temp`,
-- таблицы названы схемой. Триггер `units_merge_guard` остаётся прежним.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create or replace function units_merge_guard() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    if new.merged_into is null then
        return new;
    end if;
    if exists (select 1 from public.inspections i where i.unit_id = new.id) then
        raise exception using message =
            'У пиццерии с проверками дубль не снимается: проверки сначала переносят на цель';
    end if;
    if exists (
        select 1 from public.units t where t.id = new.merged_into and t.merged_into is not null
    ) then
        raise exception using message =
            'Цель слияния сама снята: пиццерию вливают в живую точку, цепочек не бывает';
    end if;
    if exists (select 1 from public.units c where c.merged_into = new.id) then
        raise exception using message =
            'В эту пиццерию уже влиты другие: сначала их переводят на живую точку';
    end if;
    return new;
end $$;
