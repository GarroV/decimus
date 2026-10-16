-- 0076_google_sub.sql
--
-- Номер аккаунта Google (`sub`) за учёткой (аудит 12.10, F-027). Вход через
-- Google сверял только строку почты, а почта у аккаунта Google не постоянна: её
-- меняют, адрес удалённого аккаунта заводят заново, домен Workspace переходит к
-- другому владельцу. У партнёров нет и проверки домена (`hd`, D430) — почта была
-- единственной привязкой. Номер аккаунта постоянен.
--
-- 1. `web_users.google_sub` — номер аккаунта, которым учётка входит через
--    Google; `null` — ещё не входила (у действующих учёток заполнится при
--    следующем входе). Уникален среди живых учёток.
-- 2. Триггер `web_users_forget_google_sub`: сменилась почта — номер снимается
--    (у новой почты свой аккаунт), если та же команда не записала номер сама.
--    Касается и админа на экране «Пользователи», и снятия почты в «Настройках».
-- 3. `claim_google_sub(почта, номер, записать)` — сверка при входе: номер не
--    записан — записать за живой учёткой с этой почтой; записан тот же — `ok`;
--    другой (или этот аккаунт уже держит другую живую учётку) — `other`, учётку
--    не отдают. `записать = false` — только сверка, без записи: ею вход
--    проверяет аккаунт ДО остальных шагов, а записывает номер лишь тогда, когда
--    в этом же запросе открывает сессию — недопущенный вход номер не занимает. Функция владельца: роль приложения строку
--    `web_users` не правит, а выбирает функция только учётку той почты, которую
--    Google подтвердил в этом же входе.
-- 4. `finish_own_google_link` (`0061`, `0075`) получает номер аккаунта и пишет
--    его вместе с почтой; тот же аккаунт у другой живой учётки — `taken`.
--    Прежняя функция на три аргумента снимается: её вызывает только код до
--    этой выкатки, а привязку почты в окно выкатки повторяют.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users add column google_sub text
    check (google_sub is null or char_length(google_sub) between 1 and 255);
create unique index web_users_google_sub_live_uq on web_users (google_sub)
    where google_sub is not null and disabled_at is null;

comment on column web_users.google_sub is
    'Номер аккаунта Google (sub), которым учётка входит (F-027). null — ещё не входила '
    'через Google; записывает claim_google_sub при первом входе или привязка в «Настройках», '
    'снимает смена почты.';

create function web_users_forget_google_sub() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.email is distinct from old.email
       and new.google_sub is not distinct from old.google_sub then
        new.google_sub := null;
    end if;
    return new;
end;
$$;

create trigger web_users_forget_google_sub
    before update of email on web_users
    for each row execute function web_users_forget_google_sub();

create function claim_google_sub(p_email text, p_sub text, p_record boolean)
    returns text
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чей uuid;
    прежний text;
begin
    if p_sub is null or btrim(p_sub) = '' then
        raise exception 'сверка без номера аккаунта Google';
    end if;
    select u.id, u.google_sub into чей, прежний
      from public.web_users u
     where u.email = p_email and u.disabled_at is null
       for update;
    if чей is null then
        return 'missing';
    end if;
    if прежний is not null then
        return case when прежний = p_sub then 'ok' else 'other' end;
    end if;
    if not p_record then
        return case when exists (select 1 from public.web_users
                                  where google_sub = p_sub and id <> чей
                                    and disabled_at is null)
                    then 'other' else 'ok' end;
    end if;
    -- Вложенный блок: тот же аккаунт уже держит другую живую учётку — не пускать.
    begin
        update public.web_users set google_sub = p_sub where id = чей;
    exception when unique_violation then
        return 'other';
    end;
    return 'ok';
end;
$$;

revoke all on function claim_google_sub(text, text, boolean) from public;
grant execute on function claim_google_sub(text, text, boolean) to dodo_audit_app;

drop function finish_own_google_link(text, text, text);

create function finish_own_google_link(p_token text, p_state text, p_email text, p_sub text)
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
    if p_sub is null or btrim(p_sub) = '' then
        raise exception 'привязка без номера аккаунта Google';
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
    if exists (select 1 from public.web_users
                where (email = p_email or google_sub = p_sub)
                  and id <> чей and disabled_at is null) then
        return 'taken';
    end if;

    -- Вложенный блок: отказ индекса откатывает только запись почты, погашенная
    -- метка остаётся погашенной.
    begin
        update public.web_users set email = p_email, google_sub = p_sub where id = чей;
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

revoke all on function finish_own_google_link(text, text, text, text) from public;
grant execute on function finish_own_google_link(text, text, text, text) to dodo_audit_app;
