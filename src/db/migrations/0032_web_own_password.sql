-- 0032_web_own_password.sql
--
-- #324: человек меняет СВОЙ пароль с экрана.
--
-- Писать хеш будет веб-процесс, то есть роль приложения (`dodo_audit_app`), а
-- у неё на `web_users` только чтение (`0014`) — намеренно. Права на колонку ей
-- не выдаётся и здесь: `grant update (password_hash)` пустил бы пробитое
-- приложение переписать пароль ЛЮБОМУ, ограничения «только свою строку» в
-- гранте не бывает.
--
-- Вместо права — функция владельца (`security definer`), и она сама решает,
-- ЧЬЮ строку трогать: ту, чья ЖИВАЯ СЕССИЯ ей предъявлена. Предъявляется
-- ТОКЕН из куки, а не отпечаток: отпечатки роли приложения видны, токены — нет,
-- и чужой отпечаток, поданный вместо токена, не опознаёт никого. Пробитое
-- приложение по-прежнему не сменит пароль человеку, чьей сессии у него нет.
--
-- Текущий пароль сверяет приложение (scrypt живёт в коде, `src/db/web_access.py`),
-- а функция принимает прежний хеш и меняет строку, только если он всё ещё на
-- месте: между сверкой и записью пароль могли сменить, и вторая запись поверх
-- первой молча вернула бы учётку тому, от кого её закрывали.
--
-- Остальные сессии человека закрываются в той же транзакции, своя остаётся:
-- смена пароля — реакция на «меня взломали», и она обязана выбивать вошедшего,
-- но не самого человека.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create function change_own_password(p_token text, p_old_hash text, p_new_hash text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
begin
    select u.id into чей
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.password_hash = p_old_hash;
    if чей is null then
        return false;
    end if;

    update web_users set password_hash = p_new_hash where id = чей;

    update web_sessions
       set closed_at = now()
     where user_id = чей
       and closed_at is null
       and fingerprint <> отпечаток;
    return true;
end;
$$;

comment on function change_own_password(text, text, text) is
    'Смена СВОЕГО пароля с экрана (#324): строку выбирает живая сессия, чей токен предъявлен; '
    'прежний хеш обязан быть на месте; остальные сессии человека закрываются, своя — нет.';

revoke all on function change_own_password(text, text, text) from public;
grant execute on function change_own_password(text, text, text) to dodo_audit_app;
