-- 0061_web_own_google_lang.sql
--
-- «Настройки» (D447): человек сам привязывает и снимает свою почту Google и
-- хранит язык сайта в профиле.
--
-- Роль приложения по-прежнему только читает `web_users` (`0014`): права на
-- колонки `email` и `web_lang` ей не выдаются, потому что «только свою строку»
-- в гранте не бывает. Пишут функции владельца (`security definer`), и строку
-- каждая выбирает сама — по ЖИВОЙ СЕССИИ, чей ТОКЕН ей предъявлен (не
-- отпечаток: отпечатки роли приложения видны, токены — нет). Тот же приём, что
-- у `change_own_password` (`0032`, путь поиска — `0033`).
--
-- 1. `web_users.web_lang` — язык сайта, выбранный человеком; `null` — язык
--    стенда. Форма — две латинские буквы; какие языки заведены, проверяет код
--    (третий язык добавляется словарём, без миграции).
-- 2. `web_google_link_states` — метки захода «привязать Google». Метка
--    одноразовая и принадлежит СЕССИИ, которая её начала: возврат от Google в
--    другой сессии или повтор той же метки ничего не привязывает. Хранится
--    отпечаток метки, не сама метка. Роль приложения таблицу не видит вовсе.
-- 3. `begin_own_google_link` — записать метку за своей сессией.
-- 4. `finish_own_google_link` — погасить метку и привязать почту. Ответ —
--    код исхода (`ok`, `session`, `state`, `linked`, `taken`). Почта уникальна
--    индексом `web_users_email_global_uq` (`0028`); проверка здесь — только
--    чтобы назвать исход словом, гонку двух привязок ловит индекс.
-- 5. `unlink_own_google` — снять свою почту, только если предъявлен хеш
--    пароля, всё ещё стоящий на учётке (сверяет пароль приложение, scrypt живёт
--    в коде): без пароля человек запер бы себя — после снятия он входит паролем.
-- 6. `set_own_web_lang` — язык сайта своей учётки.
--
-- Привязка и снятие закрывают ОСТАЛЬНЫЕ сессии человека (своя остаётся),
-- гасят необменянные коды OAuth и отзывают подключения Claude (`email`): дверь
-- входа сменилась, и вошедший прежней дверью — например, по утёкшему паролю —
-- не должен пережить смену ни сессией, ни подключением. Тот же порядок
-- (сперва коды, потом подключения), что у `change_own_password` (`0054`).
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users add column web_lang text
    check (web_lang is null or web_lang ~ '^[a-z]{2}$');

comment on column web_users.web_lang is
    'Язык сайта, выбранный человеком в «Настройках» (D447); null — язык стенда. '
    'Бот и мини-апп хранят свой язык отдельно. Пишет только set_own_web_lang (0061).';

create table web_google_link_states (
    fingerprint text primary key check (fingerprint ~ '^[0-9a-f]{64}$'),
    session_fingerprint text not null check (session_fingerprint ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz not null,
    used_at timestamptz
);

comment on table web_google_link_states is
    'Метки захода «привязать Google» из «Настроек» (0061): отпечаток метки, сессия, '
    'которая её начала, срок и когда погашена. Одноразовая и только для своей сессии.';

create function begin_own_google_link(p_token text, p_state text, p_ttl_seconds integer)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
begin
    if p_ttl_seconds is null or p_ttl_seconds < 1 or p_ttl_seconds > 3600 then
        raise exception 'срок метки привязки вне 1..3600 секунд: %', p_ttl_seconds;
    end if;
    if not exists (
        select 1
          from public.web_sessions s
          join public.web_users u on u.id = s.user_id
         where s.fingerprint = отпечаток
           and s.closed_at is null
           and s.expires_at > now()
           and u.disabled_at is null
    ) then
        return false;
    end if;

    -- Уборка попутно: метки старше суток никому не нужны.
    delete from public.web_google_link_states where expires_at < now() - interval '1 day';

    insert into public.web_google_link_states (fingerprint, session_fingerprint, expires_at)
    values (
        encode(sha256(convert_to(p_state, 'UTF8')), 'hex'),
        отпечаток,
        now() + make_interval(secs => p_ttl_seconds)
    );
    return true;
end;
$$;

create function finish_own_google_link(p_token text, p_state text, p_email text)
    returns text
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
    прежняя text;
begin
    if p_email is null then
        raise exception 'привязка без почты: снимают почту unlink_own_google';
    end if;
    select u.id, u.email into чей, прежняя
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       for update of u;
    if чей is null then
        return 'session';
    end if;

    update public.web_google_link_states
       set used_at = now()
     where fingerprint = encode(sha256(convert_to(p_state, 'UTF8')), 'hex')
       and session_fingerprint = отпечаток
       and used_at is null
       and expires_at > now();
    if not found then
        return 'state';
    end if;

    if прежняя is not null then
        return 'linked';
    end if;
    if exists (select 1 from public.web_users where email = p_email and id <> чей) then
        return 'taken';
    end if;

    -- Вложенный блок: отказ индекса откатывает только запись почты, погашенная
    -- метка остаётся погашенной.
    begin
        update public.web_users set email = p_email where id = чей;
    exception when unique_violation then
        return 'taken';
    end;

    update public.web_sessions
       set closed_at = now()
     where user_id = чей and closed_at is null and fingerprint <> отпечаток;
    update public.oauth_codes
       set expires_at = now()
     where user_id = чей and used_at is null and expires_at > now();
    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'email'
     where user_id = чей and revoked_at is null;
    return 'ok';
end;
$$;

create function unlink_own_google(p_token text, p_hash text)
    returns text
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
    прежняя text;
begin
    select u.id, u.email into чей, прежняя
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.password_hash = p_hash
       for update of u;
    if чей is null then
        return 'denied';
    end if;
    if прежняя is null then
        return 'none';
    end if;

    update public.web_users set email = null where id = чей;
    update public.web_sessions
       set closed_at = now()
     where user_id = чей and closed_at is null and fingerprint <> отпечаток;
    update public.oauth_codes
       set expires_at = now()
     where user_id = чей and used_at is null and expires_at > now();
    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'email'
     where user_id = чей and revoked_at is null;
    return 'ok';
end;
$$;

create function set_own_web_lang(p_token text, p_lang text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
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
       and u.disabled_at is null;
    if чей is null then
        return false;
    end if;
    update public.web_users set web_lang = p_lang where id = чей;
    return true;
end;
$$;

revoke all on function begin_own_google_link(text, text, integer) from public;
revoke all on function finish_own_google_link(text, text, text) from public;
revoke all on function unlink_own_google(text, text) from public;
revoke all on function set_own_web_lang(text, text) from public;
grant execute on function begin_own_google_link(text, text, integer) to dodo_audit_app;
grant execute on function finish_own_google_link(text, text, text) to dodo_audit_app;
grant execute on function unlink_own_google(text, text) to dodo_audit_app;
grant execute on function set_own_web_lang(text, text) to dodo_audit_app;
