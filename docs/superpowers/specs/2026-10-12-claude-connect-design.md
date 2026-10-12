# Подключение Claude к decimus с сайта (D417)

Статус: в работе с 12.10.2026. Первый этап — коллеги УК (решение владельца
12.10.2026: «в первую очередь закрой потребности УК»). Второй этап — инструмент
партнёра «занести проверку» (D419), отдельной спекой.

## Что это и зачем

Сейчас Claude подключается к MCP decimus личным токеном из бота (`/mcp`) или
мини-аппа. claude.ai в браузере, Desktop и телефон так не подключаются: им нужен
OAuth. Права MCP решаются по пространству токена, роли учётки сайта MCP не знает:
«контроль» получил бы всё, что открыто УК.

После этой работы:

- на своей карточке («Пользователи» → своя) у каждого вошедшего блок
  «Подключить Claude»: адрес MCP с кнопкой «Скопировать», два шага для
  claude.ai / Desktop / телефона, строка для Claude Code, список активных
  подключений с кнопкой «Отключить»;
- человек вставляет адрес в Claude → Claude открывает страницу входа decimus →
  человек входит своей учёткой (пароль или Google), видит, кому даёт доступ, и
  жмёт «Разрешить» → Claude работает с правами его роли;
- отключение учётки, смена роли, отзыв подключения действуют на следующем же
  вызове.

Токены из бота и `.env` работают как раньше.

## Сквозной путь

1. Claude шлёт POST на `MCP_PUBLIC_URL` без токена → MCP отвечает `401` с
   `WWW-Authenticate: Bearer resource_metadata="<MCP_PUBLIC_URL>/.well-known/oauth-protected-resource"`.
2. Claude читает этот документ (RFC 9728): `resource` = `MCP_PUBLIC_URL`,
   `authorization_servers` = [`ADMIN_PUBLIC_URL`], `scopes_supported` = [`mcp`].
3. Claude читает `ADMIN_PUBLIC_URL/.well-known/oauth-authorization-server`
   (RFC 8414): `authorization_endpoint`, `token_endpoint`, `registration_endpoint`,
   `code_challenge_methods_supported: ["S256"]`, `grant_types_supported:
   ["authorization_code","refresh_token"]`, `response_types_supported: ["code"]`,
   `token_endpoint_auth_methods_supported: ["none"]`, `scopes_supported: ["mcp"]`.
   CIMD не объявляется: Claude тогда идёт через DCR.
4. DCR (RFC 7591): `POST /oauth/register` с JSON → запись клиента, ответ с
   `client_id`. Принимаются только адреса возврата Claude (см. «Безопасность»).
5. `GET /oauth/authorize?response_type=code&client_id&redirect_uri&code_challenge&code_challenge_method=S256&state&scope&resource`
   → не вошёл — на вход и обратно сюда; вошёл — страница согласия.
6. «Разрешить» (POST, та же страница) → код (10 минут, одноразовый) → 302 на
   `redirect_uri?code=…&state=…`. «Отказать» → `error=access_denied`.
7. `POST /oauth/token` (form-urlencoded): `authorization_code` с `code_verifier`
   (PKCE S256) → access (1 час) + refresh (30 дней, ротация при каждом обмене).
8. Claude шлёт MCP с `Authorization: Bearer <access>` → MCP находит подключение,
   учётку, роль → отвечает по правам роли.

## Компоненты

| Где | Что |
|---|---|
| `src/db/migrations/0051_oauth.sql` | `oauth_clients`, `oauth_codes`, `oauth_grants` (подключение: учётка × клиент), `oauth_tokens` (access/refresh, только SHA-256) |
| `src/db/oauth_store.py` | регистрация клиента, выдача/обмен кода, выпуск/ротация/отзыв токенов, разрешение access-токена в `OAuthOwner(user_id, login, tenant, role)` с `disabled_at is null` и неотозванным подключением, список и отзыв подключений человека. Общий для `src.web` и `src.mcp` (они пиры) |
| `src/web/oauth.py` | метаданные AS, `/oauth/register`, `/oauth/authorize` (GET/POST), `/oauth/token`; открытые endpoint'ы — в `OPEN_ENDPOINTS`, кроме authorize (он требует входа) |
| `src/web/auth.py` | безопасный возврат после входа: `next` только на `/oauth/authorize?…` своего сайта, для пароля и для Google (в подписанной куке state) |
| `src/web/security_headers.py` | на ответах `/oauth/authorize` — `form-action` дополнен `https://claude.ai https://claude.com http://localhost:* http://127.0.0.1:*` |
| `src/web/users_*`, `templates/users/_card.html` | блок «Подключить Claude» на своей карточке, `POST /users/claude-revoke`; адрес добавлен в `_control_may_enter` |
| `src/mcp/server.py` | `GET /.well-known/oauth-protected-resource` (и с суффиксом пути), `resource_metadata` в `WWW-Authenticate` |
| `src/mcp/config.py` | третья дверь: OAuth access-токен → `Access(tenant, may_retract=False, actor="web:<login>", role=…)` |
| `src/mcp/policy.py` | матрица «роль × вид инструментов», одна на `tools/list` и на вызов |
| env | `ADMIN_PUBLIC_URL`, `MCP_PUBLIC_URL` — без них OAuth выключен, MCP отвечает как раньше |

## Права по роли (ядро — тесты до кода)

Только для входа через OAuth; двери бота и `.env` не меняются.

| Роль | inspections (чтение) | checklist_source | checklist (правка) | import | ratings_read (чтение рейтингов) | ratings (управление: `import_ratings`, запрос обновления агрегаторов) | retraction |
|---|---|---|---|---|---|---|---|
| УК `superadmin`, `admin` | да | да | да, если HQ в `MCP_CHECKLIST_TENANTS` | да, если включён импорт (D335) | да | да | нет |
| УК `auditor` | да | да | нет (D344: методику правят админы) | нет | да | нет | нет |
| УК `control` | нет | нет | нет | нет | да | да | нет |
| партнёр, любая роль | да, свои страны (охват как сейчас) | нет | нет | нет (D335) | да | нет | нет |

Контролинг занимается только рейтингами и проверок не касается никак (D420,
отменяет D350): инструменты проверок, методики и загрузки истории ему не видны.
Вид `ratings_read` объявлен в каталоге (`KIND_RATINGS_READ`) раньше самих
инструментов — они приходят веткой `feat/mcp-ratings-tools`.

Инструменты, которых роль не может вызвать, не попадают в `tools/list`, а вызов
отвечает отказом. Партнёрское «занести проверку» — второй этап (D419).

## Безопасность

- PKCE S256 обязателен, `plain` не принимается.
- `redirect_uri` клиента при регистрации и на authorize — только
  `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`,
  `http://localhost:<порт>/callback`, `http://127.0.0.1:<порт>/callback`
  (порт любой). Иначе отказ без редиректа.
- Код одноразовый, 10 минут, привязан к клиенту, `redirect_uri` и `code_challenge`.
- Refresh ротируется; повторное предъявление уже обменянного refresh отзывает всё
  подключение.
- Токены и коды хранятся только SHA-256, в журналы не пишутся.
- Страница согласия показывает имя клиента с пометкой, что его назвал сам
  клиент и никто не проверял, хост возврата и всегда — предупреждение
  «разрешайте, только если подключение начали вы сами и только что»; для
  `localhost` — ещё одно (спека MCP).
- Отказы token endpoint — коды RFC 6749 (`invalid_grant`, `invalid_client`,
  `invalid_request`, `unsupported_grant_type`).
- `/oauth/register` и `/oauth/token` — под ограничителем частоты
  (`src/db/web_throttle.py`): неудачи считаются адресу. Успешные регистрации —
  не больше 10 в час с адреса и 1000 в час всего (`src/web/oauth.py`).
- Отжившее убирает функция базы `oauth_purge` (у приложения нет права DELETE):
  коды и токены, истёкшие больше суток назад, и клиентов старше суток без
  подключений. Зовётся при регистрации и после каждой выдачи токенов.
- Отключённая учётка или отозванное подключение — 401 на следующем вызове.
- Смена пароля (с экрана или командой) отзывает все подключения Claude учётки.
- Токен привязан к ресурсу (RFC 8707): код и токены хранят адрес MCP (без
  `resource` в запросе — `MCP_PUBLIC_URL`), обмен кода и refresh с другим
  `resource` — `invalid_target`, сервер MCP принимает только токен своего адреса.
- `retract_inspection` через OAuth недоступен никому.

## Проверка

- Ядро (права, токены): тесты до кода; каждый — на испорченной копии.
- Протокол целиком — скрипт `tools/oauth_smoke.py`: регистрация, authorize с
  сессией тестовой учётки, обмен кода, `tools/list` по ролям, refresh, отзыв.
  Гоняется на стенде MUSPELHEIM и на проде с тестовыми учётками УК / контроля.
- Последний шаг — подключение из claude.ai и Claude Code по кнопке.

## Документация

`docs/08-deploy.md` (переменные, адреса, проверка), `docs/furca/blocks/mcp.md`,
`docs/12-web-admin.md` (блок на карточке, страница согласия), инвентарь таблиц
`docs/furca/blocks/db.md`, CHANGELOG, карточка imf-vc, если там описан вход в
MCP.
