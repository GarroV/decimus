-- 0056_mcp_token_identity.sql
--
-- Личный токен MCP привязывается к учётке сайта и получает срок (аудит
-- 12.10.2026, F-017/F-022/F-023/F-035; решения D417, D420).
--
-- До этой миграции токен знал только Telegram ID и пространство, снятое в
-- момент выпуска (`0011`). Роль учётки, её отключение и отвязка бота на токен
-- не влияли: отключённый человек или контроль, которому проверки закрыты
-- (D420), продолжал работать в Claude со всеми инструментами пространства.
--
-- Теперь у живого токена есть:
--   user_id    — учётка сайта, на которую выпущен. Сервер MCP на КАЖДЫЙ запрос
--                читает её из `web_users`: отключённая учётка не находится;
--   role       — роль учётки в момент выпуска. Токен годен, пока роль учётки
--                та же: смена роли (повышение или понижение) гасит токен до
--                перевыпуска, а права в Claude решает роль (`src/mcp/policy.py`);
--   expires_at — срок. По умолчанию 30 дней (`MCP_TOKEN_TTL_DAYS`), дальше
--                токен не находится и выпускается заново.
-- Пространство токена (`tenant_code`) тоже сверяется с учёткой: перенос учётки
-- в другое пространство гасит токен так же, как смена роли.
--
-- Прежние токены. Живой токен связывается с учёткой ТОЛЬКО через живую
-- привязку бота (`bot_bindings`, одна живая на Telegram ID — индекс `0031`) к
-- неотключённой учётке того же пространства. Такой получает роль учётки и срок
-- 30 дней от наката. Остальные живые токены гасятся: связать их не с чем, а
-- оставлять токен без учётки значит оставлять ровно ту дверь, которую
-- миграция закрывает. Человек выпускает новый после привязки бота в вебе.
-- Подпись отзыва у них `0` — «погашено накатом», не рукой человека: схема
-- требует подпись у каждого отзыва (`mcp_tokens_revocation_is_named`).
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

create index mcp_tokens_user_idx on mcp_tokens (user_id) where revoked_at is null;

comment on column mcp_tokens.user_id is
    'Учётка сайта, на которую выпущен токен. Сервер MCP читает её роль, пространство '
    'и отключение на каждый запрос (аудит 12.10, D417/D420).';
comment on column mcp_tokens.role is
    'Роль учётки в момент выпуска. Токен годен, пока роль учётки та же: смена роли '
    'гасит его до перевыпуска.';
comment on column mcp_tokens.expires_at is
    'Срок токена. По умолчанию 30 дней от выпуска (MCP_TOKEN_TTL_DAYS).';
