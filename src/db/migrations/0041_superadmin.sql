-- 0041_superadmin.sql
--
-- Главный админ и пространства партнёров с экрана «Пользователи» (#585, D362,
-- D364).
--
-- 1. Роль веб-учётки `superadmin` — главный админ: всё по проекту, включая
--    назначение других главных админов. Бывает только в пространстве УК.
--    Миграция НЕ назначает никого: кто заведён в бою, она не знает. Первого
--    главного назначает команда `tools/web_user.py role <логин> superadmin`
--    (docs/08-deploy.md), дальше — главный админ на экране.
--
-- 2. Последнего действующего главного админа нельзя отключить, понизить или
--    удалить. Держит триггер, а не экран: запись мимо кода получает тот же
--    отказ. Гонку «двое главных снимают друг друга одновременно» закрывает
--    общая блокировка транзакции (`pg_advisory_xact_lock`): вторая ждёт
--    коммита первой и считает живых главных уже после него. Без блокировки
--    каждая видела бы второго живым, и обе прошли бы.
--
-- 3. Пространство партнёра и его страны заводятся с экрана. Экран ходит ролью
--    администратора истории (`dodo_audit_admin`, как учётки), поэтому ей
--    выдаётся заведение строки `tenants` и привязка стран. Удаления и правки
--    нет: код пространства не меняется никогда, а снятая страна тихо сузила бы
--    охват чтения партнёра.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_users drop constraint web_users_role_check;
alter table web_users add constraint web_users_role_check
    check (role in ('auditor', 'admin', 'control', 'superadmin'));
alter table web_users add constraint web_users_superadmin_only_hq
    check (role <> 'superadmin' or tenant_code = 'HQ');

comment on column web_users.role is
    'Что человеку можно В АДМИНКЕ: auditor — работать со своей историей, '
    'admin — вдобавок вести людей своего охвата, control — загружать рейтинги '
    'и править их справочники (только HQ), superadmin — главный админ, всё по '
    'проекту (только HQ, последнего не снять). Чью историю видно, решает tenant_code.';

create function keep_last_superadmin() returns trigger
    language plpgsql
    set search_path = pg_catalog, pg_temp
as $$
begin
    if old.role <> 'superadmin' or old.disabled_at is not null then
        return case when tg_op = 'DELETE' then old else new end;
    end if;
    if tg_op = 'UPDATE' and new.role = 'superadmin' and new.disabled_at is null then
        return new;
    end if;
    -- Одна блокировка на всех главных: снимающие ждут друг друга, и каждый
    -- следующий считает живых после коммита предыдущего.
    perform pg_advisory_xact_lock(hashtext('decimus.web_users.superadmin'));
    if not exists (
        select 1
          from public.web_users
         where role = 'superadmin'
           and disabled_at is null
           and id <> old.id
    ) then
        raise exception 'Последнего действующего главного админа нельзя отключить или понизить (D364)'
            using errcode = 'DC001';
    end if;
    return case when tg_op = 'DELETE' then old else new end;
end;
$$;

revoke all on function keep_last_superadmin() from public;

create trigger web_users_keep_last_superadmin
    before update of role, disabled_at or delete on web_users
    for each row execute function keep_last_superadmin();

grant select, insert on tenants to dodo_audit_admin;
grant insert on space_countries to dodo_audit_admin;
