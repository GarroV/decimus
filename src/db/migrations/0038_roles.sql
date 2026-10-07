-- 0038_roles.sql
--
-- Роли с матрицей «роль × действие» (спека «Администрирование», D306, D309-D311).
--
-- Человеку назначается роль, права роли определяют, что она может. Граница
-- пространств правами не задаётся: её держит `can` в коде
-- (`src/domain/permissions.py`), здесь — только охват роли (УК или страна).
--
-- ОХВАТ ПРАВА (D311). У действий над проверкой право несёт охват: `own` —
-- только проверки, которые занесла учётка человека, `all` — все проверки, до
-- которых пускает граница. У прочих действий — только `all`. Нет строки — нет
-- права.
--
-- ПЕРЕНОС. Роли учёток до этой миграции — `admin`/`auditor` (`0020`). Они
-- переводятся по пространству учётки ровно по таблице спеки:
--   HQ × admin → hq_admin, HQ × auditor → hq_staff,
--   страна × admin → country_admin, страна × auditor → country_staff.
--
-- ЗАСЕВ — таблица спеки с D310 (`unit.create` у `hq_staff`) и D311 (сотрудникам
-- над проверкой — `own`); с кодом (`DEFAULT_MATRIX`) его сверяет
-- `tests/test_db_roles_migration.py`.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table roles (
    code text primary key check (code ~ '^[a-z][a-z0-9_]{1,39}$'),
    scope text not null check (scope in ('hq', 'country')),
    name_ru text not null check (length(btrim(name_ru)) between 1 and 80),
    name_en text not null check (length(btrim(name_en)) between 1 and 80),
    created_at timestamptz not null default now()
);

create table role_permissions (
    role_code text not null references roles (code) on delete cascade,
    action_code text not null check (action_code ~ '^[a-z]+\.[a-z_]+$'),
    reach text not null default 'all' check (reach in ('own', 'all')),
    primary key (role_code, action_code),
    constraint role_permissions_own_on_inspection check (
        reach = 'all' or action_code in (
            'inspection.retract', 'inspection.move', 'inspection.accept',
            'inspection.revise', 'inspection.letter'
        )
    )
);

insert into roles (code, scope, name_ru, name_en) values
    ('hq_admin', 'hq', 'Админ УК', 'HQ admin'),
    ('hq_staff', 'hq', 'Сотрудник УК', 'HQ staff'),
    ('country_admin', 'country', 'Админ страны', 'Country admin'),
    ('country_staff', 'country', 'Сотрудник страны', 'Country staff');

insert into role_permissions (role_code, action_code, reach)
select 'hq_admin', код, 'all' from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect', 'unit.create', 'space.manage',
    'roles.manage'
]) as код
union all
select 'hq_staff', код, 'all' from unnest(array[
    'inspection.conduct', 'prescription.manage', 'prescription.reply', 'plan.manage',
    'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'mcp.connect', 'unit.create'
]) as код
union all
select 'country_admin', код, 'all' from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect'
]) as код
union all
select 'country_staff', код, 'all' from unnest(array[
    'inspection.conduct', 'prescription.reply', 'plan.submit', 'mcp.connect'
]) as код
union all
select роль, код, 'own'
  from unnest(array['hq_staff', 'country_staff']) as роль
 cross join unnest(array[
    'inspection.retract', 'inspection.move', 'inspection.accept', 'inspection.revise',
    'inspection.letter'
]) as код;

-- Прежнее ограничение `0020` знает только admin/auditor — снимается до переноса.
alter table web_users drop constraint web_users_role_check;
alter table web_users alter column role drop default;

update web_users
   set role = case
       when tenant_code = 'HQ' and role = 'admin' then 'hq_admin'
       when tenant_code = 'HQ' then 'hq_staff'
       when role = 'admin' then 'country_admin'
       else 'country_staff'
   end;

alter table web_users
    add constraint web_users_role_fkey foreign key (role) references roles (code);

comment on column web_users.role is
    'Код роли (roles.code): что человеку можно — правами role_permissions. '
    'Роль УК — только у людей HQ, роль страны — только у людей страны '
    '(триггер web_users_role_scope). Чью историю видно, решает tenant_code.';

-- Охват роли сверяется со строкой учётки: роль УК у партнёра — отказ. Внешний
-- ключ этого не выразит: условие смотрит в две таблицы.
create function web_users_role_scope() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    охват text;
begin
    -- Пустую роль ловит `not null`, незаведённую — внешний ключ: каждый отказ
    -- называет свою причину. Триггер BEFORE стреляет раньше обоих, и без этой
    -- строки он отвечал бы «не для пространства» на опечатку в роли, а тесты
    -- прочих ограничений строки зеленели бы его отказом, а не своим.
    if new.role is null or not exists (select 1 from roles where code = new.role) then
        return new;
    end if;
    select scope into охват from roles where code = new.role;
    if охват is distinct from (case when new.tenant_code = 'HQ' then 'hq' else 'country' end) then
        raise exception 'Роль % не для пространства %', new.role, new.tenant_code
            using errcode = 'check_violation', constraint = 'web_users_role_scope';
    end if;
    return new;
end;
$$;

create trigger web_users_role_scope
    before insert or update of role, tenant_code on web_users
    for each row execute function web_users_role_scope();

grant select on roles, role_permissions to dodo_audit_app, dodo_audit_admin;
