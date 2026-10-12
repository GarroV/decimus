-- 0059_mcp_token_identity.sql
--
-- Личный токен MCP принадлежит учётке сайта и получает срок; круг доступа к
-- MCP снимается (аудит 12.10.2026, F-017/F-022/F-023/F-035/F-036; решения
-- D417, D420, D447, D448).
--
-- До этой миграции токен знал только Telegram ID и пространство, снятое в
-- момент выпуска (`0011`), а выпускать его мог только «круг» — список Telegram
-- ID в `mcp_admins`, куда людей приводили друг друга по номеру. Роль учётки,
-- её отключение и отвязка бота на токен не влияли: отключённый человек или
-- контроль, которому проверки закрыты (D420), продолжал работать в Claude со
-- всеми инструментами пространства.
--
-- D448: доступ к Claude никто никому не выдаёт. Человек с действующей учёткой
-- сам выпускает себе токен (веб, бот или мини-апп — одна функция,
-- `src/db/mcp_access.py`); что он может в Claude, решает роль учётки;
-- кончается доступ отключением учётки или сменой роли.
--
-- У живого токена теперь есть:
--   user_id    — учётка сайта, на которую выпущен. Сервер MCP на КАЖДЫЙ запрос
--                читает её из `web_users`: отключённая учётка не находится;
--   role       — роль учётки в момент выпуска. Токен годен, пока роль та же;
--   expires_at — срок. По умолчанию 30 дней (`MCP_TOKEN_TTL_DAYS`).
-- Пространство токена (`tenant_code`) тоже сверяется с учёткой.
-- `telegram_id` становится необязательным: токен, выпущенный в вебе, Telegram
-- не знает. Живой токен один на УЧЁТКУ, а не на Telegram ID.
--
-- Смена роли, пространства или отключение учётки ГАСЯТ её живые токены
-- триггером (`web_users_access_change_revokes_mcp_tokens`): сверки на каждый
-- запрос хватило бы, чтобы токен перестал работать, но без гашения он ожил бы
-- при возврате прежней роли. Триггер держит это для любого пути правки учётки,
-- а не для двух запросов экрана.
--
-- Подпись отзыва `revoked_by`: Telegram ID отозвавшего — или `0`, если отозвал
-- не человек из чата (накат, правка учётки, отзыв из веба). Схема требует
-- подпись у каждого отзыва (`mcp_tokens_revocation_is_named`, `0011`).
--
-- Прежние токены. Живой токен связывается с учёткой через живую привязку бота
-- (`bot_bindings`) к неотключённой учётке того же пространства и получает срок
-- 30 дней от наката. Остальные живые токены гасятся (подпись `0`): связать их
-- не с чем, а токен без учётки — ровно та дверь, которую миграция закрывает.
-- Человек выпускает новый в своих настройках веба.
--
-- Круг (`mcp_admins`) удаляется: таблицу больше не читает ни один путь кода, а
-- оставленная, она выглядела бы действующим списком доступа. След «кто кого
-- приводил» теряется вместе с ней — по D448 он больше ничего не означает.
--
-- Раннер оборачивает файл в одну транзакцию сам. Накат идёт под владельцем
-- схемы, который обходит RLS (`src/db/migrate.py`).

alter table mcp_tokens
    add column user_id uuid references web_users (id),
    add column role text,
    add column expires_at timestamptz;

update mcp_tokens t
   set user_id = u.id,
       role = u.role,
       expires_at = now() + interval '30 days'
  from bot_bindings b
  join web_users u on u.id = b.user_id
 where t.revoked_at is null
   and b.telegram_id = t.telegram_id
   and b.unbound_at is null
   and u.disabled_at is null
   and u.tenant_code = t.tenant_code;

update mcp_tokens
   set revoked_at = now(), revoked_by = 0
 where revoked_at is null and user_id is null;

-- Живой токен без учётки, роли или срока схема больше не принимает: забытая
-- колонка в выпуске становится отказом записи, а не вечным токеном.
alter table mcp_tokens add constraint mcp_tokens_live_has_identity
    check (revoked_at is not null
           or (user_id is not null and role is not null and expires_at is not null));

alter table mcp_tokens alter column telegram_id drop not null;

-- Один живой токен на учётку — вместо одного на Telegram ID (`0011`). Тот же
-- смысл: повторный выпуск обязан гасить прежний, и забытый отзыв становится
-- отказом записи, а не двумя живыми токенами.
drop index mcp_tokens_one_live_per_person_idx;
create unique index mcp_tokens_one_live_per_user_idx
    on mcp_tokens (user_id) where revoked_at is null;

create function revoke_mcp_tokens_on_access_change() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    if new.role is distinct from old.role
       or new.tenant_code is distinct from old.tenant_code
       or (new.disabled_at is not null and old.disabled_at is null) then
        update public.mcp_tokens
           set revoked_at = now(), revoked_by = 0
         where user_id = new.id and revoked_at is null;
    end if;
    return new;
end $$;

create trigger web_users_access_change_revokes_mcp_tokens
    after update of role, tenant_code, disabled_at on web_users
    for each row execute function revoke_mcp_tokens_on_access_change();

drop table mcp_admins;

comment on column mcp_tokens.user_id is
    'Учётка сайта, на которую выпущен токен. Сервер MCP читает её роль, пространство '
    'и отключение на каждый запрос (аудит 12.10, D417/D420/D448).';
comment on column mcp_tokens.role is
    'Роль учётки в момент выпуска. Смена роли гасит токен (триггер на web_users).';
comment on column mcp_tokens.expires_at is
    'Срок токена. По умолчанию 30 дней от выпуска (MCP_TOKEN_TTL_DAYS).';
comment on column mcp_tokens.telegram_id is
    'Telegram ID, из чата которого выпущен токен; NULL — выпущен в вебе.';
comment on column mcp_tokens.revoked_by is
    'Кто отозвал: Telegram ID — или 0, если не человек из чата (накат, правка '
    'учётки, отзыв из веба).';
