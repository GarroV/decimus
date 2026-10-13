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
-- 3. Триггер `web_users_freeze_cascade`: переход `disabled_at` из `null` в дату
--    закрывает сессии, гасит необменянные коды OAuth, отзывает подключения
--    Claude, снимает живую привязку бота и гасит неиспользованные ссылки
--    привязки. Личные токены MCP по-прежнему гасит триггер `0059`. Триггер, а не
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

create function freeze_cascade() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    update public.web_sessions
       set closed_at = now()
     where user_id = new.id and closed_at is null;
    update public.oauth_codes
       set expires_at = now()
     where user_id = new.id and used_at is null and expires_at > now();
    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'frozen'
     where user_id = new.id and revoked_at is null;
    update public.bot_bindings
       set unbound_at = now()
     where user_id = new.id and unbound_at is null;
    update public.bot_link_tokens
       set used_at = now()
     where user_id = new.id and used_at is null;
    return new;
end $$;

revoke all on function freeze_cascade() from public;

create trigger web_users_freeze_cascade
    after update of disabled_at on web_users
    for each row
    when (new.disabled_at is not null and old.disabled_at is null)
    execute function freeze_cascade();

comment on function freeze_cascade() is
    'Заморозка (D462): при отключении учётки закрывает сессии, гасит коды и подключения '
    'Claude, снимает привязку бота и неиспользованные ссылки привязки. Токены MCP гасит 0059.';

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
