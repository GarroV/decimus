-- 0063_web_own_google_profile.sql
--
-- Имя и фото из Google в блоке учётки (D468). Берутся при входе через Google и
-- при привязке Google в «Настройках»; у учётки без Google колонки пусты, и
-- экран показывает логин и инициалы.
--
-- 1. `web_users.display_name` — отображаемое имя (имя и фамилия) из проверенного
--    `id_token`; `null` — не знаем, показывается логин.
-- 2. `web_users.avatar` / `avatar_type` / `avatar_etag` — само фото, скачанное
--    ОДИН РАЗ при входе (`src/web/google_profile.py`) и отдаваемое со своего
--    адреса (`/settings/avatar`): политика источников страницы остаётся
--    `img-src 'self'`, и страница не ходит к Google ни за чем. Предел —
--    200 КБ, виды — jpeg, png, webp. Три колонки живут только вместе
--    (`web_users_avatar_whole`). `avatar_etag` — первые 16 знаков sha256 байтов,
--    ставит функция; по нему страница узнаёт, сменилось ли фото, не читая байты.
-- 3. `set_own_google_profile` — записать имя и фото СВОЕЙ учётке. Как у
--    `set_own_web_lang` (`0061`): роль приложения `web_users` только читает, а
--    строку функция выбирает сама, по ЖИВОЙ СЕССИИ, чей ТОКЕН ей предъявлен.
--    Пустое значение прежнее не затирает: сбой скачивания фото не должен
--    стирать то, что уже есть.
--
-- Чтение — прежним `grant select on web_users` (`0014`) на таблицу: новых прав
-- роли приложения не нужно. Свою картинку отдаёт маршрут по своей же сессии;
-- чужую по ключу он не отдаёт вовсе.
--
-- ОТКАТ по смыслу: `drop function set_own_google_profile(text, text, bytea, text);`
-- затем `alter table web_users drop constraint web_users_avatar_whole, drop column
-- avatar_etag, drop column avatar_type, drop column avatar, drop column display_name;`
-- — потеряются только скачанные имя и фото, при следующем входе через Google они
-- берутся заново.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users
    add column display_name text
        check (display_name is null or char_length(display_name) between 1 and 120),
    add column avatar bytea
        check (avatar is null or octet_length(avatar) <= 204800),
    add column avatar_type text
        check (avatar_type is null or avatar_type in ('image/jpeg', 'image/png', 'image/webp')),
    add column avatar_etag text
        check (avatar_etag is null or avatar_etag ~ '^[0-9a-f]{16}$'),
    add constraint web_users_avatar_whole check (
        (avatar is null) = (avatar_type is null) and (avatar is null) = (avatar_etag is null)
    );

comment on column web_users.display_name is
    'Имя и фамилия из Google (D468); null — показывается логин. Пишет только set_own_google_profile (0063).';
comment on column web_users.avatar is
    'Фото из Google, скачанное один раз при входе (D468); до 200 КБ. Отдаёт только /settings/avatar своей сессии.';
comment on column web_users.avatar_type is
    'Тип фото по сигнатуре байт, не по заголовку: image/jpeg, image/png или image/webp (0063).';
comment on column web_users.avatar_etag is
    'Первые 16 знаков sha256 байтов фото: версия для ETag и адреса (0063).';

create function set_own_google_profile(p_token text, p_name text, p_avatar bytea, p_type text)
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

    update public.web_users
       set display_name = coalesce(nullif(btrim(p_name), ''), display_name),
           avatar = coalesce(p_avatar, avatar),
           avatar_type = case when p_avatar is null then avatar_type else p_type end,
           avatar_etag = case
               when p_avatar is null then avatar_etag
               else substr(encode(sha256(p_avatar), 'hex'), 1, 16)
           end
     where id = чей;
    return true;
end;
$$;

revoke all on function set_own_google_profile(text, text, bytea, text) from public;
grant execute on function set_own_google_profile(text, text, bytea, text) to dodo_audit_app;
