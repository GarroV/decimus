-- 0132_partner_space_safety.sql
--
-- Защита пространства партнёра (D759, пункты 1–3): три независимых куска одной миграции.
--
-- 1. Смена пароля гасит личный токен MCP. Триггер `0059` отзывал токены при смене роли,
--    пространства и заморозке, но не при смене пароля: человек менял пароль «на всякий
--    случай», а ключ Claude, выпущенный до этого, жил дальше. Подключения Claude по OAuth
--    смена с экрана уже отзывала (`0054`), токен MCP — нет. Триггер ловит ЛЮБОЙ путь
--    смены (экран «Настройки», `tools/web_user.py password`), а не два запроса.
--
-- 2. Заморозка всего пространства партнёра одной кнопкой.
--    `tenants.frozen_at` / `tenants.frozen_by` — пространство заморожено, когда и кем.
--    `web_users.space_frozen_at` — учётка заморожена ЭТОЙ кнопкой (а не по одной): по
--    отметке разморозка возвращает ровно тех, кого заморозила кнопка, и не трогает
--    замороженных раньше. Саму заморозку учёток делает прежний механизм — `disabled_at`
--    и триггеры `0059`/`0063` (сессии, подключения Claude, токены MCP, бот), поэтому
--    пространство и одиночная заморозка закрывают одно и то же. УК не замораживается.
--    Пока пространство заморожено, в нём нельзя завести учётку, перевести в него учётку
--    или снять заморозку с отдельной учётки: триггер на самой таблице, чтобы правило
--    держалось для любого пути (экран, команда с сервера).
--
-- 3. События «в пространстве партнёра появился админ» и «сменилась почта учётки» —
--    только запись для показа на экране главному админу и админу УК. Пишет триггер:
--    путь заведения и правки не важен. Кто это сделал — из `dodo.actor` (ставит дверь
--    приложения в той же транзакции); пусто — сама учётка или команда с сервера.
--    Отметка «Видел» — своя у каждого просматривающего: сигнал безопасности не должен
--    пропадать у второго администратора оттого, что первый его закрыл.
--
-- Раннер оборачивает файл в одну транзакцию сам. Накат идёт под владельцем схемы.

-- --- 1. Пароль гасит токен MCP ---------------------------------------------------

create or replace function revoke_mcp_tokens_on_access_change() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    if new.role is distinct from old.role
       or new.tenant_code is distinct from old.tenant_code
       or (new.disabled_at is not null and old.disabled_at is null)
       or new.password_hash is distinct from old.password_hash then
        update public.mcp_tokens
           set revoked_at = now(), revoked_by = 0
         where user_id = new.id and revoked_at is null;
    end if;
    return new;
end $$;

drop trigger web_users_access_change_revokes_mcp_tokens on web_users;
create trigger web_users_access_change_revokes_mcp_tokens
    after update of role, tenant_code, disabled_at, password_hash on web_users
    for each row execute function revoke_mcp_tokens_on_access_change();

-- --- 2. Заморозка пространства ---------------------------------------------------

alter table tenants
    add column frozen_at timestamptz,
    add column frozen_by uuid references web_users (id);

alter table web_users add column space_frozen_at timestamptz;

comment on column tenants.frozen_at is
    'Пространство заморожено кнопкой (D759); null — действует. УК не замораживается.';
comment on column tenants.frozen_by is
    'Кто заморозил пространство (учётка сайта); null — не известно.';
comment on column web_users.space_frozen_at is
    'Учётка заморожена кнопкой «Заморозить пространство» (D759), а не по одной. '
    'Разморозка пространства возвращает только такие учётки.';

create function freeze_space(p_code text, p_by uuid) returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    момент timestamptz := now();
    сделано integer;
begin
    if p_code = 'HQ' or not exists (select 1 from public.tenants where code = p_code) then
        raise exception 'freeze_space: % is not a partner space', p_code
            using errcode = 'P0001';
    end if;
    update public.tenants set frozen_at = момент, frozen_by = p_by
     where code = p_code and frozen_at is null;
    if not found then
        return 0;
    end if;
    update public.web_users
       set disabled_at = момент, disabled_by = p_by, space_frozen_at = момент
     where tenant_code = p_code and disabled_at is null;
    get diagnostics сделано = row_count;
    return сделано;
end $$;

create function unfreeze_space(p_code text) returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    сделано integer;
begin
    if p_code = 'HQ' or not exists (select 1 from public.tenants where code = p_code) then
        raise exception 'unfreeze_space: % is not a partner space', p_code
            using errcode = 'P0001';
    end if;
    -- Сначала снимается отметка пространства: сторож ниже не даёт снимать заморозку учёток,
    -- пока она стоит.
    update public.tenants set frozen_at = null, frozen_by = null
     where code = p_code and frozen_at is not null;
    update public.web_users
       set disabled_at = null, disabled_by = null, space_frozen_at = null
     where tenant_code = p_code and space_frozen_at is not null and disabled_at is not null;
    get diagnostics сделано = row_count;
    update public.web_users set space_frozen_at = null
     where tenant_code = p_code and space_frozen_at is not null;
    return сделано;
end $$;

revoke all on function freeze_space(text, uuid) from public;
revoke all on function unfreeze_space(text) from public;
grant execute on function freeze_space(text, uuid) to dodo_audit_admin;
grant execute on function unfreeze_space(text) to dodo_audit_admin;
grant select (space_frozen_at) on web_users to dodo_audit_admin;

comment on function freeze_space(text, uuid) is
    'Заморозить все действующие учётки пространства партнёра и пометить пространство (D759). '
    'Возвращает число замороженных учёток; 0 — пространство уже заморожено. УК и неизвестный '
    'код — отказ.';
comment on function unfreeze_space(text) is
    'Снять заморозку пространства и вернуть учётки, замороженные этой кнопкой (D759); '
    'замороженные по одной остаются замороженными. Возвращает число возвращённых учёток.';

create function web_users_frozen_space_guard() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    if new.disabled_at is null
       and (tg_op = 'INSERT'
            or new.tenant_code is distinct from old.tenant_code
            or old.disabled_at is not null)
       and exists (
           select 1 from public.tenants where code = new.tenant_code and frozen_at is not null
       ) then
        raise exception 'space % is frozen', new.tenant_code using errcode = 'P0001';
    end if;
    return new;
end $$;

create trigger web_users_frozen_space_guard
    before insert or update of tenant_code, disabled_at on web_users
    for each row execute function web_users_frozen_space_guard();

-- --- 3. События в пространствах партнёров ----------------------------------------

create table partner_account_events (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    tenant_code text not null references tenants (code),
    user_id uuid not null references web_users (id),
    kind text not null check (kind in ('admin_added', 'email_changed')),
    -- Кто сделал; null — сама учётка или команда с сервера.
    actor_id uuid references web_users (id)
);

create index partner_account_events_time_idx on partner_account_events (occurred_at desc);

create table partner_event_seen (
    event_id bigint not null references partner_account_events (id) on delete cascade,
    user_id uuid not null references web_users (id),
    seen_at timestamptz not null default now(),
    primary key (event_id, user_id)
);

comment on table partner_account_events is
    'Новые админы и смены почты в пространствах партнёров (D759): для показа на экране, '
    'наружу не отправляется. Пишет триггер web_users_partner_events.';
comment on table partner_event_seen is
    'Кто из главного админа и админов УК отметил событие «Видел» (D759): у каждого своя отметка.';

grant select on partner_account_events to dodo_audit_admin;
grant select, insert on partner_event_seen to dodo_audit_admin;

create function record_partner_event() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    кто uuid := nullif(current_setting('dodo.actor', true), '')::uuid;
begin
    if new.tenant_code = 'HQ' then
        return new;
    end if;
    if new.role = 'admin' and (tg_op = 'INSERT' or old.role is distinct from 'admin') then
        insert into public.partner_account_events (tenant_code, user_id, kind, actor_id)
        values (new.tenant_code, new.id, 'admin_added', кто);
    end if;
    -- Почта, заданная сразу после заведения, — часть заведения, а не смена.
    if tg_op = 'UPDATE' and new.email is distinct from old.email
       and not (old.email is null and new.created_at > now() - interval '10 minutes') then
        insert into public.partner_account_events (tenant_code, user_id, kind, actor_id)
        values (new.tenant_code, new.id, 'email_changed', кто);
    end if;
    return new;
end $$;

create trigger web_users_partner_events
    after insert or update of role, email, tenant_code on web_users
    for each row execute function record_partner_event();
