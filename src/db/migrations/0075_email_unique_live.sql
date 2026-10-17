-- 0075_email_unique_live.sql
--
-- Почта входа через Google уникальна только среди ЖИВЫХ учёток (аудит 12.10,
-- F-031). Индекс `web_users_email_global_uq` (`0028`) держал и почту
-- замороженной учётки: заморозили человека — его адрес занят навсегда, и
-- завести на ту же почту новую учётку нельзя, пока старую не удалят (а учёток
-- не удаляют). Теперь почта замороженной свободна:
--
-- 1. `web_users_email_live_uq` — уникальность почты среди строк с
--    `disabled_at is null`. Новый индекс заводится раньше, чем снимается
--    прежний: между ними нет мгновения без защиты.
-- 2. Разморозка (`disabled_at` → `null`) упирается в тот же индекс, если
--    почту за время заморозки отдали живой учётке: код ловит отказ и говорит
--    причину (`web_access.unfreeze_account` → `EmailTakenError`), учётка
--    остаётся замороженной.
-- 3. `finish_own_google_link` (`0061`) отвечает «занята» только про живую
--    учётку — иначе человек не привязал бы в «Настройках» почту, которую
--    держит замороженная. Тело то же, изменено одно условие; гранты на
--    функцию `create or replace` сохраняет.
--
-- Опознание по почте (`find_by_email`) и так ищет только живых, поэтому вход
-- через Google находит ровно одну учётку.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create unique index web_users_email_live_uq on web_users (email)
    where email is not null and disabled_at is null;
drop index web_users_email_global_uq;

create or replace function finish_own_google_link(p_token text, p_state text, p_email text)
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
    if exists (select 1 from public.web_users
                where email = p_email and id <> чей and disabled_at is null) then
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
