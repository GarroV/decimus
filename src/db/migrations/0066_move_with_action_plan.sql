-- 0066_move_with_action_plan.sql
--
-- Перенос проверки в пиццерию другой страны не оставляет по ней экшн-план
-- (приватный advisory GHSA-wqh3-3qcr-cccp). Партнёр видит запрос экшн-плана и
-- файлы по СТРАНЕ точки проверки (0036, D284), поэтому перенос проверки УК в
-- точку другой страны (D195) отдал бы их партнёру той страны. Как и у предписаний
-- (0037: основание сверяется по ТЕКУЩЕЙ стране), граница держится в базе, а не в
-- вызове: перенос между странами при существующем запросе экшн-плана отвергается,
-- какой бы ролью он ни шёл. Перенос внутри страны, а также проверка без плана
-- не затронуты.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create function guard_move_with_action_plan() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    была text;
    станет text;
begin
    -- Роль, которая переносит, запрос экшн-плана может не видеть: читаем в
    -- правах владельца функции.
    select u.country into была from public.units u where u.id = old.unit_id;
    select u.country into станет from public.units u where u.id = new.unit_id;
    if была is not distinct from станет then
        return new;
    end if;
    if exists (select 1 from public.action_plan_requests r where r.inspection_id = old.id) then
        raise exception 'проверку % с экшн-планом нельзя перенести в пиццерию другой страны (% → %)',
            old.id, coalesce(была, '—'), coalesce(станет, '—')
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

revoke all on function guard_move_with_action_plan() from public;

create trigger inspections_move_with_action_plan
    before update of unit_id on inspections
    for each row
    when (old.unit_id is distinct from new.unit_id)
    execute function guard_move_with_action_plan();
