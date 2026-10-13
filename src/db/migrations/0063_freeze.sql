-- 0063_freeze.sql
--
-- «Заморозить» (D462, шаг 1): отключение учётки становится заморозкой — одним
-- действием закрывается всё, чем человек входил, и записывается, кто заморозил.
--
-- До этой миграции отключение (`web_users.disabled_at`) гасило личные токены MCP
-- (`0059`), а сессии, подключения Claude (OAuth), привязку бота и выпущенные, но
-- не использованные ссылки привязки оставались как были. Каждая дверь на
-- отключённую учётку и так не пускала (учётка читается на каждый запрос), но
-- ничто не мешало возврату: снять отключение значило воскресить сессию и
-- подключение Claude, закрытые только «по месту». Теперь заморозка всё гасит
-- насовсем, а размороженный человек заново привязывает бота и подключает Claude.
--
-- 1. `web_users.disabled_by` — кто заморозил (учётка сайта); `null` — командой
--    с машины или отключено до этой миграции. Пишет та же роль, что
--    `disabled_at` (администратор истории, `0020`), и тем же запросом.
-- 2. `oauth_grants.revoked_reason` принимает `frozen`.
-- 3. Триггер `web_users_freeze_cascade`: смена `disabled_at` (заморозка И разморозка)
--    закрывает сессии, гасит необменянные коды и выпущенные токены OAuth, отзывает
--    подключения Claude и токены MCP, снимает живую привязку бота и гасит
--    неиспользованные ссылки привязки (`close_all_access`). Учётки, отключённые до
--    этой миграции, закрываются при накате. Триггер, а не
--    код экрана: заморозка держится для ЛЮБОГО пути отключения (экран, команда
--    `tools/web_user.py`), и забыть шаг на новом пути нельзя. Функция владельца
--    (`security definer`), потому что у роли, которая отключает, прав на эти
--    таблицы нет и быть не должно.
-- 4. `sign_out_everywhere(token)` — «Выйти везде» из «Настроек»: строку выбирает
--    живая сессия, чей токен предъявлен (тот же приём, что `change_own_password`,
--    `0032`). Закрывает все сессии человека, включая текущую, гасит коды и
--    подключения Claude и личный токен MCP. Привязка бота остаётся. Ответ `false`
--    — сессия не живая, ничего не сделано.
--
-- Раннер оборачивает файл в одну транзакцию сам. Накат идёт под владельцем
-- схемы, который обходит RLS (`src/db/migrate.py`).

alter table web_users add column disabled_by uuid references web_users (id);

comment on column web_users.disabled_by is
    'Кто заморозил учётку (D462): учётка сайта; null — командой с машины или до 0063. '
    'Снимается вместе с disabled_at.';

alter table oauth_grants drop constraint oauth_grants_revoked_reason_check;
alter table oauth_grants add constraint oauth_grants_revoked_reason_check
    check (revoked_reason in ('user', 'reuse', 'password', 'email', 'frozen'));

grant select (disabled_by), update (disabled_by) on web_users to dodo_audit_admin;

-- Всё закрывается ОДНОЙ функцией (`close_all_access`): заморозка, разморозка и
-- накат зовут её же, и список закрываемого не расходится между путями.
-- Токены OAuth, выпущенные подключением, гасятся и сроком, и отзывом
-- подключения: отзыв — то, что читают двери, срок — запас на случай, если
-- отметку отзыва кто-то снимет.
create function close_all_access(p_user uuid) returns void
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    update public.web_sessions
       set closed_at = now()
     where user_id = p_user and closed_at is null;
    update public.oauth_codes
       set expires_at = now()
     where user_id = p_user and used_at is null and expires_at > now();
    update public.oauth_tokens
       set expires_at = now()
     where grant_id in (select id from public.oauth_grants where user_id = p_user)
       and expires_at > now();
    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'frozen'
     where user_id = p_user and revoked_at is null;
    update public.mcp_tokens
       set revoked_at = now(), revoked_by = 0
     where user_id = p_user and revoked_at is null;
    update public.bot_bindings
       set unbound_at = now()
     where user_id = p_user and unbound_at is null;
    update public.bot_link_tokens
       set used_at = now()
     where user_id = p_user and used_at is null;
end $$;

revoke all on function close_all_access(uuid) from public;

comment on function close_all_access(uuid) is
    'Закрыть всё, чем человек входит (D462): сессии, коды и токены OAuth, подключения '
    'Claude, токены MCP, привязку бота, ссылки привязки. Только для триггера заморозки '
    'и наката: прав на неё нет ни у кого, кроме владельца.';

create function freeze_cascade() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    perform public.close_all_access(new.id);
    return new;
end $$;

revoke all on function freeze_cascade() from public;

-- И при заморозке, и при разморозке. Заморозка закрывает всё; разморозка закрывает
-- ещё раз то, что могло пережить отключение, сделанное до этой миграции или
-- мимо триггера: размороженная учётка не получает назад ничего прежнего.
create trigger web_users_freeze_cascade
    after update of disabled_at on web_users
    for each row
    when ((old.disabled_at is null) <> (new.disabled_at is null))
    execute function freeze_cascade();

comment on function freeze_cascade() is
    'Заморозка и разморозка (D462): при смене disabled_at закрывает всё, чем человек входит '
    '(close_all_access).';

-- Накат: учётки, отключённые ДО этой миграции, держали сессии, подключения Claude и
-- бота живыми (отключение гасило только токены MCP, `0059`), и разморозка вернула бы
-- их. Закрываем сейчас.
select public.close_all_access(id) from web_users where disabled_at is not null;

create function sign_out_everywhere(p_token text) returns boolean
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
begin
    select u.id into чей
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       for update of u;
    if чей is null then
        return false;
    end if;

    update public.web_sessions
       set closed_at = now()
     where user_id = чей and closed_at is null;
    update public.oauth_codes
       set expires_at = now()
     where user_id = чей and used_at is null and expires_at > now();
    update public.oauth_tokens
       set expires_at = now()
     where grant_id in (select id from public.oauth_grants where user_id = чей)
       and expires_at > now();
    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'user'
     where user_id = чей and revoked_at is null;
    update public.mcp_tokens
       set revoked_at = now(), revoked_by = 0
     where user_id = чей and revoked_at is null;
    return true;
end $$;

revoke all on function sign_out_everywhere(text) from public;
grant execute on function sign_out_everywhere(text) to dodo_audit_app;

comment on function sign_out_everywhere(text) is
    '«Выйти везде» (D462): по живой сессии (токен предъявлен) закрывает все сессии человека, '
    'включая эту, гасит коды и подключения Claude и личный токен MCP. Привязка бота остаётся.';
