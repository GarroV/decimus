# Карта кода

> Откуда начинать, если пришёл в код, а не в предмет. Таблицы «файл — что делает»
> **генерируются** (`make map`, `tools/gen_map.py`): первая фраза докстринга файла
> под маркерами `<!-- map:begin … -->`. Руками здесь правятся только текст вокруг
> них, глоссарий и таблица «по задаче → куда идти». Маршруты, инструменты MCP,
> переменные окружения, миграции и цели Makefile — в [`inventory.md`](inventory.md).
> Тест `tests/test_docs_map.py` краснеет, если файл кода не назван в карте, карта
> называет несуществующий файл или таблицы отстали от кода.

## Что это

Dodo Audit Service (в коде и документах — Decimus) — сервис выездных проверок
пиццерий: аудитор фиксирует нарушения в Telegram-боте или мини-аппе, движок считает
оценку, управляющая компания и партнёры читают результат в веб-админке, а Claude и
Swarm — через MCP и API чтения. Какие поверхности есть и чем поднимаются — таблица
в [`README.md`](../README.md#что-уже-работает); кто и через какую дверь входит —
[`18-access-map.md`](18-access-map.md). Здесь — где что лежит в коде.

Порядок такой: сначала предмет (`02-domain.md`, `03-recording-rules.md`), потом эта
карта, потом документ нужного блока (`docs/furca/blocks/*.md` — контракты блоков).

## Глоссарий

Термины, на которых держится код и документы. Слово в коде и слово на экране не
всегда совпадают — тогда указаны оба.

| Термин | Что значит | Где живёт |
|---|---|---|
| Пространство (в коде — `tenant`, «тенант») | Замкнутый круг данных одной организации: её пиццерии, люди, проверки. Одно пространство — управляющая компания (код `HQ`), остальные — партнёры. Изоляция держится ключами схемы и политиками базы по пространству, которое ставит дверь (`src/db/space.py`, миграция `0062`), а не только фильтром в запросе. На экране и в разговоре говорят «пространство» | `src/db/spaces.py`, `src/domain/tenants.py`, `src/db/reach.py`, `src/db/space.py`; `docs/furca/blocks/spaces.md` |
| УК | Управляющая компания: владелец методики, видит всю сеть, принимает проверки партнёров. Её пространство — `HQ` | `src/domain/tenants.py` (`HQ_TENANT`), `docs/18-access-map.md` |
| Партнёр | Организация, чьи пиццерии проверяют; видит и правит только своё пространство и свои страны | `docs/18-access-map.md`, `src/db/reach.py` |
| Роль | Одна из шести: в пространстве УК — главный админ (`superadmin`), админ (`admin`), контроль (`control`), аудитор (`auditor`); у партнёра — админ и аудитор | `src/domain/tenants.py`, `src/web/access_policy.py`, `src/mcp/policy.py` |
| Контроль, контролинг | Роль УК и люди, которые ведут рейтинги: загружают и правят рейтинги, ведут своих людей; проверок не касаются никак — ни «Главной», ни «Проверок» даже на чтение (D420), после входа попадают в «Рейтинги» | `docs/12-web-admin.md` (роль «контроль»), `src/domain/permissions.py` (матрица), `src/mcp/policy.py` |
| Методика | Что и как проверяется: чек-лист, зоны, критерии классов, ставки вычетов, порядок обхода. Данные управляющей компании, вне git; версионируется изданиями | `docs/02-domain.md`, `src/domain/checklist.py`, `src/domain/version.py`, `src/domain/edition.py` |
| Чек-лист | Перечень пунктов методики с кодами, зонами и допустимыми классами. Правится одной дверью — через хранилище версий | `engine/manage.py`, `src/mcp/checklist.py`, `src/web/methodology.py` |
| Зона | Участок точки, на который делится оценка (десять зон, у каждой своя доля). Код зоны — сущность, название — перевод | `docs/02-domain.md`, `src/domain/checklist.py`, `src/bot/zones.py` (зона из слов аудитора) |
| Класс D1 / D2 / D3 | Критичность нарушения по критериям УК: D1 — отклонение (вычет 0,5 п.п.), D2 — существенное (2 п.п.), D3 — критическое (сжигает долю зоны). Ещё `R` — рекомендация без вычета | `docs/02-domain.md`, ставки — в данных методики (`scoring.json`), не в коде |
| Находка (в коде — запись, `finding`) | Одно зафиксированное нарушение: пункт, класс, зона, формулировка, кадры. В отчёт попадает только после подтверждения аудитора | `src/domain/findings.py`, `src/db/models.py`, `docs/03-recording-rules.md` |
| Обход (`walk`) | Проход аудитора по точке: порядок зон и пунктов, что ещё не осмотрено | `src/domain/route.py`, `docs/13-walk-mini-app.md` |
| Мини-апп | Рабочий экран обхода внутри Telegram: что не осмотрено, что было в прошлый раз, запись прямо там. Отдельный сервис со своим адресом `/tg/walk*` | `src/web/walk*.py`, `docs/13-walk-mini-app.md` |
| Оценка | Процент, буква и разбивка по зонам. Считает только движок; ни бот, ни веб, ни модель не пересчитывают | `engine/audit.py score`, `src/domain/scoring.py`, `src/report/rescore.py` |
| Повтор | Нарушение, которое было в прошлой проверке точки и не устранено; вычитает вдвое. Действует в момент расчёта и задним числом ничего не меняет | `docs/02-domain.md`, `src/bot/repeats.py` |
| Кадр | Фотография к записи; хранится в S3-совместимом хранилище, в вебе показывается сжатой копией | `src/db/photos.py`, `src/db/previews.py`, `src/db/storage.py` |
| Словарь синонимов (`photo-cues`; в коде и старых записях — «карта кадров», «карта слов») | Данные методики: какими словами аудитор называет нарушение или объект → какой пункт и какая зона за ними стоят. Нужна быстрому пути разбора, без неё каждый комментарий уходит в модель | `src/recognize/cues.py`, `src/recognize/fastpath.py`, `docs/furca/blocks/recognize.md` |
| Сдача, приёмка | Аудитор сдаёт проверку (`handover`); она лежит в базе `draft` на приёмке — её вычитывают, правят с пересчётом оценки (правит и УК, и партнёр; каждая правка пишется в журнал правок `inspection_edits` в той же транзакции: кто, когда, было → стало) и подтверждают, после чего она `finalized` и заморожена политиками базы | `src/domain/handover.py`, `src/db/accept.py`, `src/db/revise.py`, `src/db/inspection_edits.py`, `src/web/review.py` |
| Снятие | Отзыв сданной проверки из истории: помечается, не удаляется, причина обязательна. Делает только роль «администратор истории» | `src/db/retract.py`, `src/mcp/retraction.py`, `docs/furca/blocks/db.md` |
| Перенос | Смена даты и пиццерии у проверки; история каждой правки пишется самой базой | `src/db/move.py` |
| Legacy-проверка | Историческая проверка, загруженная из старого отчёта (`origin = 'legacy'`): оценка переносится как есть и нигде не пересчитывается | `src/db/imports_legacy.py`, `src/mcp/imports.py`, `docs/14-history-import.md` |
| План действий (экшн-план) | Ответ партнёра на запрос УК по проверке с D2/D3: файл с версиями, приём и возврат | `src/db/action_plans.py`, `src/web/action_plans.py`, `docs/12-web-admin.md` |
| Предписание | Письмо УК партнёру с требованием: черновик, отправка через почту сотрудника, ответ партнёра, закрытие | `src/db/prescriptions.py`, `src/web/prescriptions.py` |
| РС, РКО | Рейтинг стандартов и рейтинг клиентского опыта: средние оценки по пиццериям из выгрузок Dodo IS; раздел «Рейтинги» | `docs/15-ratings.md`, `src/ratings/` |
| Агрегатор | Площадка доставки с оценками пиццерий (Wolt, Glovo, Bolt Food, Yemeksepeti и др.); оценки собираются раз в сутки | `docs/17-aggregators.md`, `src/ratings/aggregators/` |
| Pointer | Внешний API оценок и отзывов с карт | `docs/09-pointer-api.md`, `src/ratings/pointer.py` |
| Свод пиццерий | Таблица сведений о пиццериях, из которой наполняется справочник профилей | `docs/16-unit-profiles.md`, `src/ratings/svod.py` |
| Swarm | Внутренняя платформа команды, главная которой показывает наши данные. Читает их по API чтения, своих копий не держит | `src/web/swarm_api.py`, `docs/12-web-admin.md` (раздел «API чтения для Swarm») |
| MCP | Протокол, которым Claude у человека читает историю проверок и правит методику и рейтинги. Свой сервер, только петля, наружу — туннелем | `src/mcp/`, `docs/furca/blocks/mcp.md`, [`inventory.md`](inventory.md) |
| Личный токен | Ключ Claude Desktop, который человек с учёткой выпускает себе сам — в своих настройках на сайте, в боте (`/mcp`) или мини-аппе; никто никому его не выдаёт (D448). В базе — отпечаток, учётка, роль, срок. Права — по роли учётки и допускам пространства; срок 30 дней (`MCP_TOKEN_TTL_DAYS`); отключение учётки и смена роли гасят его сразу. Не путать со служебным токеном `MCP_TOKENS` из `.env` | `src/db/mcp_access.py`, `src/mcp/policy.py`, `docs/furca/blocks/mcp.md` |
| Сервисный токен | Ключ внешнего сервиса к API чтения (`/api/v1/*`): только чтение, право на каждый метод, страны и срок у ключа | `src/db/api_access.py`, `tools/api_token.py`, `docs/18-access-map.md` |
| Ключ модели | Ключ провайдера нейросети для разбора комментариев и голосовых: вставляется главным админом на «Подключениях», лежит в базе зашифрованным (`SECRETS_KEY` — вне базы), иначе берётся `OPENAI_API_KEY` | `src/db/model_key.py`, `src/db/secret_crypto.py`, `src/web/model_key_screen.py`, `docs/12-web-admin.md` |
| FURCA | Процесс разработки проекта: анкета, спека, блоки с контрактами, граф задач, журнал решений. Артефакты — в `docs/furca/` | `docs/furca/`, `progress.md`, `tasks.md` |
| D###, T###, #N | Номер решения владельца (`docs/furca/decisions.md`), номер задачи стройки (`tasks.md`), номер issue на GitHub. Ссылки на них стоят в докстрингах — это «почему так» | `docs/furca/decisions.md`, `tasks.md` |
| Тестовая база | Тесты блока `db` и всего, что ходит в Postgres, идут на отдельной базе; без неё пропускаются, а пропуск — не зелёный | `Makefile` (`make test`), `tests/db_harness.py`, `tests/conftest.py` |

## Как устроен репозиторий

| Каталог | Роль |
|---|---|
| `src/` | Продукт: бот, веб, MCP, база, разбор моделью, сборка отчёта, предметная область, рейтинги |
| `engine/` | Движок: оценка, PDF, правка чек-листа. Вызывается **подпроцессом**, не импортом |
| `tools/`, `scripts/` | Операционка: сиды, замеры, учётки, проверки доступа; раскатка и смоук |
| `tests/` | Тесты; `tests/methodology/` — синтетическая методика, по которой они идут |
| `docs/` | Документы: предмет `01`–`18`, контракты блоков `docs/furca/`, эта карта и инвентарь |
| `front/` | Cloudflare Worker'ы: постоянные адреса админки и MCP |
| `deploy/`, `docker-compose*.yml`, `Dockerfile` | Сборка и состав сервисов |
| `demo/`, `checklist-blank/` | Синтетический демо-набор; пустой бланк чек-листа |

Слои кода, сверху вниз (обратный импорт запрещён, `make bounds`): `tools`; `bot`,
`mcp`, `web` — три равные поверхности, друг друга по договорённости не импортируют;
`ratings`; `recognize`, `report`, `db`; `domain`. Подробности — `[tool.importlinter]`
в `pyproject.toml`.

## src/web — веб-админка и мини-апп

Flask-приложение управляющей компании и партнёров. Вход обязателен на каждом адресе,
кроме перечня `OPEN_ENDPOINTS` в `src/web/auth.py`; заслоны ролей и пространств
стоят в `src/web/app.py` (`_install_*_gate`). Разделы навигации и признак «построен»
— `src/web/sections.py`. Тексты — каталогом по ключам, язык — параметр. Список
маршрутов с файлами — [`inventory.md`](inventory.md).

### Сборка приложения и общее

`app.py` собирает приложение и ещё держит часть экранов; остальные экраны
подключаются своими `install(app, conf)`.

<!-- map:begin files src/web/{__main__,app,assets,config,dates,db_refusal,errors,icons,sections,view,webauthn_rp}.py -->
| Файл | Что делает |
|---|---|
| `src/web/__main__.py` | Точка входа веб-админки: `python -m src.web` |
| `src/web/app.py` | Веб-админка управляющей компании: маршруты и сборка приложения |
| `src/web/assets.py` | Статика админки: отпечаток в адресе и долгий кеш |
| `src/web/config.py` | Окружение веб-админки: адрес, порт, тенант, язык интерфейса, ключ подписи |
| `src/web/dates.py` | Дата для человека: «6 сен 2026», а не `2026-09-06` и не `06.09.2026` (#963) |
| `src/web/db_refusal.py` | Отказ базы словами для вошедшего — без устройства стенда (#515, F-012 аудита 12.10) |
| `src/web/errors.py` | Отказы блока `web` |
| `src/web/icons.py` | Иконки админки — набор линейки из дизайн-системы (`static/icons.json`) |
| `src/web/sections.py` | Разделы веб-админки и признак «построен / не построен» (D138) |
| `src/web/view.py` | Подготовка того, что уже посчитано, к показу |
| `src/web/webauthn_rp.py` | Ключи доступа (WebAuthn): тонкая обёртка над `webauthn` (duo-labs/py_webauthn, D463) |
<!-- map:end -->

### Экраны

Страница = модуль с маршрутами (`install` или `_register_*` в `app.py`) + шаблон в
`src/web/templates/<раздел>/` + тексты в `texts_<раздел>.py`.

<!-- map:begin files src/web/{action_plans,actions_screen,calendar_screen,calendar_view,country,country_filter,country_page,country_settings,country_summary,country_units,edition,geo_names,google_mail,grade_explain,home_board,item_labels,home_page,home_ratings,home_ratings_block,inspection_titles,inspections,letter_draft,letter_markup,methodology,methodology_view,overview,plan_template,prescriptions,proofread,ratings,ratings_calendar,ratings_line,ratings_sheet,ratings_tiles,registry_period,registry_view,review,revision,to_inspect,unit_add,unit_card}.py -->
| Файл | Что делает |
|---|---|
| `src/web/action_plans.py` | Экшн-планы в вебе: вкладка «Экшн-планы» раздела «Действия» (волна 2, D263–D274, D526) |
| `src/web/actions_screen.py` | Раздел «Действия»: экшн-планы и предписания — один экран у УК и партнёра (D526, D527) |
| `src/web/calendar_screen.py` | Раздел «Календарь» (D497): сетка месяца с проверками и поездками (D505, D506) |
| `src/web/calendar_view.py` | Сетка месяца на экране «Календарь» (D497): проверки по дням |
| `src/web/country.py` | Экран «Страны» (прежде «Пиццерии»): снимок страны и история пиццерии (D260, D262, D512) |
| `src/web/country_filter.py` | Постоянный отбор стран экрана «Страны» (D536): «мне нужен только Кавказ» |
| `src/web/country_page.py` | Экран «Страны» (прежде «Пиццерии»): снимок страны и история пиццерии (D260, D262, D512) |
| `src/web/country_settings.py` | «Карточка страны» на экране «Страны» (D539, прежде «Настройки страны», D536) |
| `src/web/country_summary.py` | Сводка экрана «Страны» (D467): цифры периода и девелоперы стран |
| `src/web/country_units.py` | Строки пиццерий экрана «Страны» (D467): одна строка на пиццерию |
| `src/web/edition.py` | День публикации издания методики — для шапки проверки на приёмке |
| `src/web/geo_names.py` | Названия стран и городов для людей — по коду из справочника точек |
| `src/web/google_mail.py` | Черновик письма партнёру в почте вошедшего (D174, D176, #332) |
| `src/web/grade_explain.py` | «Почему такая буква» и «расшифровка» для карточки проверки (D490) |
| `src/web/home_board.py` | Задания карточки «Требует внимания» на «Главной» (D378, D398): стикеры по живым счётчикам |
| `src/web/home_page.py` | Экран «Главная» (D378): по образцу новой главной Swarm Brain |
| `src/web/home_ratings.py` | Блоки «Стандарты · РС» и «Клиентский опыт · РКО» на «Главной» (D378) |
| `src/web/home_ratings_block.py` | Блок «Рейтинги» на «Главной» (D418): РС, РКО, карты и агрегаторы (D557) — по кластерам (D502) |
| `src/web/inspection_titles.py` | Формулировки пунктов методики по коду — для деталей проверки в API Swarm (D391) |
| `src/web/inspections.py` | Раздел «Проверки»: что показать и чем это взято |
| `src/web/item_labels.py` | Пункт чек-листа для человека на экранах веба: «Порядок 13», а не `CLN13` (20.10.2026) |
| `src/web/letter_draft.py` | Письмо уходит в черновики почты вошедшего (T352, D174, D176, D185, #332) |
| `src/web/letter_markup.py` | Разметка письма партнёру: белый список из четырёх элементов (T353, D169, #332) |
| `src/web/methodology.py` | Раздел «Методика»: правка состава чек-листа той же дверью, что MCP и CLI |
| `src/web/methodology_view.py` | Экран чек-листа (D197): отбор, группировка и соседи пункта |
| `src/web/overview.py` | Экран «Обзор сети»: что показать и чем это взято |
| `src/web/plan_template.py` | Шаблон экшн-плана — `.xlsx` из записей проверки (#976, ступень 1) |
| `src/web/prescriptions.py` | Предписания в вебе: вкладка «Предписания» раздела «Действия» (волна 3, D266, D270, D275, D526) |
| `src/web/proofread.py` | «Добавить нарушение» на вычитке: подбор пункта по словам и кадрам (D535) |
| `src/web/ratings.py` | Раздел «Рейтинги» (спека 2026-10-08) и подраздел «Загрузки» |
| `src/web/ratings_calendar.py` | Период раздела «Рейтинги»: «‹ 2026 Q3 ›», по щелчку — календарь «с — по» |
| `src/web/ratings_line.py` | График средних раздела «Рейтинги» (D396): линия по периодам рейтинга |
| `src/web/ratings_sheet.py` | Блок «Таблица контроля» на «Загрузках»: когда забирали, чем кончилось, кнопка (D464) |
| `src/web/ratings_tiles.py` | Плитки раздела «Рейтинги» (D585): лицо плитки — заголовок, одна-две цифры и короткая строка |
| `src/web/registry_period.py` | Период реестра проверок: «с — по» по дате обхода |
| `src/web/registry_view.py` | Реестр проверок: отбор строк и подписи периода — без прав и без оценок |
| `src/web/review.py` | Чек-лист той версии, по которой считали проверку, — для правки записей на вычитке (D535) |
| `src/web/revision.py` | Правка записи на приёмке с пересчётом отчёта (D200) |
| `src/web/to_inspect.py` | «Где не проведено» на «Проверках» (D399; D418, D466, D497 — переезды; D501 — вернулся сюда) |
| `src/web/unit_add.py` | Новая пиццерия из веб-админки: экран страны → «Добавить пиццерию» (#437, D240) |
| `src/web/unit_card.py` | Карточка точки: где пиццерия сейчас, куда движется и что у неё не чинится |
<!-- map:end -->

### Вход, пользователи и доступ

Вход паролем и Google, сессия в подписанной куке, заслон происхождения формы,
экран «Пользователи» с карточкой человека, ключи API сервисов, подключение Claude
входом через сайт (OAuth).

<!-- map:begin files src/web/{access_policy,photo_upload,account_menu,accounts,auth,connections_form,demo_entry,landing,connections_screen,google_auth,google_link,google_profile,guard,journal,journal_screen,model_key_screen,oauth,origin,partner_spaces,people,profile,passkey_login,proxy,remote,security_headers,reauth,second_step,security_screen,settings_screen,ui_lang,usage_screen,usage_view,users_claude,users_mcp,users_page,users_screen,users_view}.py -->
| Файл | Что делает |
|---|---|
| `src/web/access_policy.py` | Кто кого ведёт на экране «Пользователи» (#585, D362, D364) — одно правило на экран |
| `src/web/account_menu.py` | Меню учётки (D468): состояние подключений для строки «Подключения» |
| `src/web/accounts.py` | Учётки админки так, как их видит экран (T338, #322) |
| `src/web/auth.py` | Вход в админку: форма, сессия в подписанной куке, выход (T323, D155) |
| `src/web/connections_form.py` | Разбор формы «Подключить сервис» и правки сервиса (D425) |
| `src/web/connections_screen.py` | Вкладка «Подключения» экрана «Пользователи»: ключи API сервисов (D425, #568) |
| `src/web/demo_entry.py` | Вход в открытое демо (D524): выбор роли и сессия без пароля — только на стенде демо |
| `src/web/google_auth.py` | Вход в админку по учётке Google (T332, D163, D168) |
| `src/web/google_link.py` | Привязка своей почты Google из «Настроек» (D447, D450, D430) |
| `src/web/google_profile.py` | Имя и фото из Google в учётку (D468): скачать фото один раз и записать |
| `src/web/guard.py` | Заслон прав веба: каждый маршрут спрашивает матрицу (`src/domain/permissions.py`) |
| `src/web/journal.py` | Журналы входов и действий на стороне веба (D462, `0067`) |
| `src/web/journal_screen.py` | Экраны журналов (D462): «Журнал» главного админа и «Мои входы» человека |
| `src/web/landing.py` | Посадочная страница продукта (D524): что такое Decimus, «Войти» и «Открыть демо» |
| `src/web/model_key_screen.py` | Блок «Ключ модели» на вкладке «Подключения»: вставить, проверить, убрать (D491) |
| `src/web/oauth.py` | Сервер авторизации OAuth для подключения Claude к MCP (D417) |
| `src/web/origin.py` | Заслон происхождения: пропустить отправку формы только со своей же страницы |
| `src/web/partner_spaces.py` | Пространства партнёров на экране «Пользователи» (#585, D364) |
| `src/web/passkey_login.py` | Вход ключом доступа без логина (D485): ключ открывает сессию сам, без второй ступени |
| `src/web/people.py` | Правка человека на вкладке «Пользователи»: роль и почта входа через Google (#399) |
| `src/web/photo_upload.py` | Загрузка кадров к черновику загрузки проверки по подписанной ссылке (мимо Claude) |
| `src/web/profile.py` | Свой пароль с экрана (#324): что форма пропускает к базе и что отвечает |
| `src/web/proxy.py` | Что сказать `waitress` про звенья перед нами — и кому из соседей верить |
| `src/web/reauth.py` | Свежий вход для действий, создающих долгоживущий доступ (аудит безопасности 12.10) |
| `src/web/remote.py` | Чей это адрес: кто пришёл на страницу, когда между нами стоит туннель |
| `src/web/second_step.py` | Вторая ступень входа: «Подтвердите вход» после Google или пароля (D463) |
| `src/web/security_headers.py` | Заголовки безопасности админки: один набор на КАЖДЫЙ ответ (#489) |
| `src/web/security_screen.py` | Экран «Вход и защита» (`/settings/security`, D463): способы подтверждения входа |
| `src/web/settings_screen.py` | Экран «Настройки» (`/settings`): настройки своего профиля — всё подключение в одном месте |
| `src/web/ui_lang.py` | Язык сайта: из профиля учётки, `?lang=` — разовый перекрёсток (D447) |
| `src/web/usage_screen.py` | Экран «Расход модели» (D537): сколько токенов и денег ушло на модель |
| `src/web/usage_view.py` | Расход модели (D537): из сумм базы — то, что рисует экран «Расход модели» |
| `src/web/users_claude.py` | Блок «Подключить Claude» в «Настройках» (D417): адрес MCP и подключения через сайт |
| `src/web/users_mcp.py` | Личный токен Claude в «Настройках»: выпустить себе и отозвать (D447, D448) |
| `src/web/users_page.py` | Сборка страницы «Пользователи»: список слева, карточка выбранного справа |
| `src/web/users_screen.py` | Экран «Пользователи» (`/users`): один экран доступа для всех, охват по роли (#585) |
| `src/web/users_view.py` | Вид экрана «Пользователи»: названия ролей, фильтры, выбор человека, адреса |
<!-- map:end -->

### API для сервисов

<!-- map:begin files src/web/{api_feed,swarm_api}.py -->
| Файл | Что делает |
|---|---|
| `src/web/api_feed.py` | Ответы API для сервисов (D426): оценки агрегаторов и топ нарушений по проверкам |
| `src/web/swarm_api.py` | API чтения для сервисов, v1 (#567, D387, D390, D426): рейтинги, нарушения, проверки, карты, агрегаторы |
<!-- map:end -->

### Тексты

Каталог `TEXTS[ключ][язык]` собирается в `texts.py` из словарей `texts_*.py`; тест
`tests/test_web_texts.py` требует, чтобы каждый ключ был заполнен на обоих языках.

<!-- map:begin files src/web/texts*.py -->
| Файл | Что делает |
|---|---|
| `src/web/texts.py` | Тексты веб-админки: каталог по ключам, язык — параметр |
| `src/web/texts_app.py` | Тексты мини-аппа как приложения аудитора (D373): главная и настройки |
| `src/web/texts_connections.py` | Тексты вкладки «Подключения» экрана «Пользователи» (D425, #568) |
| `src/web/texts_country.py` | Тексты экрана «Страны» (D467, D504, D536): колонка, шапка, плитки, пиццерии, панели |
| `src/web/texts_demo.py` | Тексты открытого демо и лендинга (D524): выбор роли, плашка, посадочная страница |
| `src/web/texts_grade.py` | Тексты «почему такая буква» и «расшифровка оценки» на карточке проверки (D490) |
| `src/web/texts_hints.py` | Тексты подсказок и обучения мини-аппа (D444) |
| `src/web/texts_home.py` | Тексты «Главной» (D378, D398, D418, D471): внимание, проверки, «Рейтинги», фильтры |
| `src/web/texts_journal.py` | Тексты журналов входов и действий (D462): подписи действий и экран «Журнал» |
| `src/web/texts_master.py` | Тексты метки «главный чек-лист» и шапки «Методики» (D440) |
| `src/web/texts_model_key.py` | Тексты блока «Ключ модели» на вкладке «Подключения» (D491) |
| `src/web/texts_oauth.py` | Тексты подключения Claude входом через сайт (D417): согласие, отказ, блок в «Настройках» |
| `src/web/texts_photo_upload.py` | Тексты страницы загрузки кадров к черновику по ссылке из Claude (`photo_upload.py`) |
| `src/web/texts_plans.py` | Тексты экшн-планов (волна 2) и раздела «Действия» (D526): вкладка, панель, блоки, карточки |
| `src/web/texts_prescriptions.py` | Тексты предписаний (волна 3): раздел УК, раздел партнёра, блок экрана страны |
| `src/web/texts_ratings.py` | Тексты раздела «Рейтинги» и подраздела «Загрузки» (спека 2026-10-08) |
| `src/web/texts_refusals.py` | Тексты отказов раздела «Методика»: хранилище методики и формы экрана (#475) |
| `src/web/texts_registry.py` | Тексты раздела «Проверки» в раскладке «список слева, карточка справа» |
| `src/web/texts_second_factor.py` | Тексты второй ступени входа (D463): «Подтвердите вход» и «Вход и защита» |
| `src/web/texts_settings.py` | Тексты экрана «Настройки» (D447): подключения, Google, язык, пароль |
| `src/web/texts_trips.py` | Тексты поездок «Календаря» (D505, D506): сетка, карточка, план, отказы |
| `src/web/texts_units.py` | Тексты заведения пиццерии из веб-админки (#437, D233, D240) |
| `src/web/texts_usage.py` | Тексты экрана «Расход модели» (D537): вкладка «Администрирования», расход токенов |
| `src/web/texts_users.py` | Тексты экрана «Пользователи» вместе с карточкой человека (#585, переделка экрана) |
| `src/web/texts_walk.py` | Тексты мини-аппа обхода (#418) — сливаются в общий каталог `texts.TEXTS` |
<!-- map:end -->

### Мини-апп обхода

Отдельный сервис (`python -m src.web.walk_main`) со своим томом на запись; админка
передаёт ему адреса `/tg/walk*` (`walk_proxy.py`). Вход — по подписи Telegram, не по
куке админки.

<!-- map:begin files src/web/walk*.py -->
| Файл | Что делает |
|---|---|
| `src/web/walk.py` | Мини-апп обхода в Telegram: что на точке ещё не осмотрено и что было здесь в прошлый раз (#418) |
| `src/web/walk_access.py` | Кого пускает мини-апп — ровно тех, кого пускает бот (D372) |
| `src/web/walk_app.py` | Сервис мини-аппа обхода: только адреса `/tg/walk*` и статика к ним |
| `src/web/walk_auth.py` | Кто открыл мини-апп обхода — по подписи Telegram, а не по куке админки (#418) |
| `src/web/walk_finish.py` | «Завершить проверку» из приложения (D422, D449): сводка или сразу отчёт |
| `src/web/walk_main.py` | Точка входа сервиса мини-аппа обхода: `python -m src.web.walk_main` |
| `src/web/walk_proxy.py` | Адреса мини-аппа обхода в админке — передача сервису обхода, без своей логики |
| `src/web/walk_rate.py` | Предел частоты запросов мини-аппа обхода по чату (#529, #710) |
| `src/web/walk_settings.py` | Мини-апп как приложение аудитора (D373): настройки и подключение Claude |
| `src/web/walk_start.py` | Начало проверки из мини-аппа (D392): те же шаги, что у мастера бота, — полями на одном экране |
| `src/web/walk_suggest.py` | Мини-апп обхода: поиск пункта по кадру и словам (D330) — `POST /tg/walk/suggest` |
| `src/web/walk_translate.py` | Мини-апп обхода: перевод свободного текста на другой язык (D394) — `POST /tg/walk/translate` |
| `src/web/walk_unseen.py` | Мини-апп обхода: «Ещё не смотрели» — пункты зоны, по которым записи пока нет (#837, D492) |
| `src/web/walk_write.py` | Запись из мини-аппа обхода (D312): кадр, нарушение, замер, рекомендация, сведения о визите |
| `src/web/walk_zone.py` | Мини-апп обхода: зона записи после того, как пункт найден (D445) |
<!-- map:end -->

### Шаблоны и статика

Jinja-шаблоны по разделам и статика с отпечатком в адресе (`assets.py`). Файлы
`dodo-ds.css` и `decimus-domain.css` — копии дизайн-системы, правятся не здесь
(`src/web/static/SOURCE.md`).

<!-- map:begin tree src/web/templates -->
| Каталог | Файлов | Какие |
|---|---|---|
| `src/web/templates/` | 23 | _account_menu.html, _account_menu_connections.html, _langpick.html, _login_lang.html, _period.html, _pick.html, _pick_page.html, _pick_ui.html, … (+15) |
| `src/web/templates/actions/` | 9 | _filters.html, _list_plans.html, _list_rx.html, _panel_fragment.html, _panel_plan.html, _panel_rx.html, index.html, prescription_form.html, … (+1) |
| `src/web/templates/calendar/` | 2 | _trip.html, index.html |
| `src/web/templates/country/` | 6 | _head.html, _mine.html, _parts.html, _settings.html, _summary.html, index.html |
| `src/web/templates/demo/` | 3 | app.html, locked.html, pick.html |
| `src/web/templates/inspections/` | 9 | _card_body.html, _card_parts.html, _panel.html, _panel_fragment.html, _row.html, card.html, letter.html, list.html, … (+1) |
| `src/web/templates/journal/` | 1 | page.html |
| `src/web/templates/methodology/` | 5 | apply.html, broken.html, checklists.html, index.html, unset.html |
| `src/web/templates/oauth/` | 2 | consent.html, refused.html |
| `src/web/templates/overview/` | 1 | index.html |
| `src/web/templates/prescriptions/` | 1 | not_found.html |
| `src/web/templates/ratings/` | 3 | coverage.html, imports.html, index.html |
| `src/web/templates/settings/` | 4 | confirm.html, continue.html, index.html, security.html |
| `src/web/templates/units/` | 3 | _profile.html, card.html, new.html |
| `src/web/templates/usage/` | 1 | page.html |
| `src/web/templates/users/` | 8 | _card.html, _connections.html, _model_key.html, _spaces.html, _tabs.html, connections.html, forbidden.html, index.html |
<!-- map:end -->

<!-- map:begin tree src/web/static -->
| Каталог | Файлов | Какие |
|---|---|---|
| `src/web/static/` | 59 | SOURCE.md, actions.js, apple-touch-icon.png, country.js, decimus-actions.css, decimus-country.css, decimus-domain.css, decimus-home.css, … (+51) |
| `src/web/static/fonts/` | 13 | golos-text-cyrillic-ext.woff2, golos-text-cyrillic.woff2, golos-text-latin-ext.woff2, golos-text-latin.woff2, ibm-plex-mono-cyrillic-400.woff2, ibm-plex-mono-cyrillic-500.woff2, ibm-plex-mono-cyrillic-600.woff2, ibm-plex-mono-latin-400.woff2, … (+5) |
| `src/web/static/landing/` | 15 | actions-en.webp, actions-ru.webp, match-en.webp, match-ru.webp, network-en.webp, network-ru.webp, pizzerias-en.webp, pizzerias-ru.webp, … (+7) |
<!-- map:end -->

## src/db — база и хранилище

Единственное место, где живёт SQL и права. Схема правится только миграциями
(`src/db/migrations/`, раннер `migrate.py`); продукт ходит под ролью приложения, а
снятие, перенос и приёмка — под ролью администратора истории
(`DATABASE_RETRACTION_URL`). Решений и расчётов здесь нет.

### Подключение, схема, файлы

<!-- map:begin files src/db/{checksum,config,database_target,errors,migrate,models,photos,pool,previews,reading,recipe_audit,reports,request_memo,space,space_guard,storage,storage_reconcile,target_refusal,timeouts}.py -->
| Файл | Что делает |
|---|---|
| `src/db/checksum.py` | Отпечаток миграции: что в нём участвует, а что нет (#258) |
| `src/db/config.py` | Окружение блока: где Postgres |
| `src/db/database_target.py` | Куда ведёт строка подключения — и все ли подключения ведут в одну базу (#487) |
| `src/db/errors.py` | Отказы блока `db` |
| `src/db/migrate.py` | Накат SQL-миграций |
| `src/db/models.py` | Типы, которыми блок `db` разговаривает наружу |
| `src/db/photos.py` | T094: выгрузка кадров проверки в хранилище |
| `src/db/pool.py` | Общий помощник подключения к базе: пул соединений на каждый DSN |
| `src/db/previews.py` | Сжатая копия кадра для показа в админке (D219) |
| `src/db/reading.py` | Подключение на время чтения: отказ базы — `DbError`, а не пустая выдача |
| `src/db/recipe_audit.py` | T203 (#170): можно ли снять прежний рецепт отпечатка на ЭТОЙ базе |
| `src/db/reports.py` | T336 (#317): готовый отчёт проверки уезжает в хранилище |
| `src/db/request_memo.py` | Память одного HTTP-запроса для чтений, которые страница просит из разных блоков |
| `src/db/space.py` | Пространство, от имени которого идёт обращение к базе (аудит 12.10, F-037, F-005) |
| `src/db/space_guard.py` | Пространство записи обязано быть заведено — опечатка в коде это отказ (#481) |
| `src/db/storage.py` | Хранилище кадров за S3-совместимым интерфейсом (D004, D054) |
| `src/db/storage_reconcile.py` | Сверка хранилища файлов с таблицами: экшн-планы и ответы на предписания (#496) |
| `src/db/target_refusal.py` | Расхождение баз в цепочке отказа — узнать и записать в журнал (#515, #521) |
| `src/db/timeouts.py` | Пределы ожидания базы по умолчанию для обычных соединений (F-119) |
<!-- map:end -->

### Проверки, справочники, чтение

<!-- map:begin files src/db/{accept,photo_intake,bot_langs,bot_links,checklist_langs,directory,fingerprint,finish_modes,imports,imports_legacy,inspection_edits,letters,mcp_access,move,push,queries,reach,retract,review_edit,revise,spaces,swarm_read,synonyms,translate_modes,trips,unit_profiles,units}.py -->
| Файл | Что делает |
|---|---|
| `src/db/accept.py` | Подтверждение проверки на приёмке (D199) |
| `src/db/bot_langs.py` | Язык бота, выбранный человеком (D303, #411): чтение и запись |
| `src/db/bot_links.py` | Привязка бота к учётке через веб (D286): выпуск ссылки, погашение, привязка, отвязка |
| `src/db/checklist_langs.py` | Язык чек-листа, выбранный аудитором при старте проверки (D451): чтение и запись |
| `src/db/directory.py` | T092: справочник точек и карта синонимов |
| `src/db/fingerprint.py` | Отпечаток содержимого завершённой проверки |
| `src/db/finish_modes.py` | Режим «Завершить» в мини-аппе, выбранный аудитором (D449): чтение и запись |
| `src/db/imports.py` | Загрузка проверки задним числом поштучно: черновик, записи, кадры (D305–D310, D334) |
| `src/db/imports_legacy.py` | Записи исторической проверки (`origin = 'legacy'`, D332): без движка |
| `src/db/inspection_edits.py` | Журнал правок записей проверки на приёмке (F-134, `0081`) |
| `src/db/letters.py` | T333 (#310): письмо партнёру, зафиксированное человеком |
| `src/db/mcp_access.py` | Личный доступ к MCP: токены учёток сайта (T253, D098; аудит 12.10, D448) |
| `src/db/move.py` | Перенос проверки по дате и пиццерии — с историей каждой правки (D195) |
| `src/db/photo_intake.py` | Приём кадра по ссылке загрузки: тип — по сигнатуре байт, а не по имени и заголовку клиента |
| `src/db/push.py` | T093: слив завершённой проверки в базу |
| `src/db/queries.py` | Чтение уже слитых проверок |
| `src/db/reach.py` | Охват чтения: что видит пространство (волна 1, #340; D283, D284, D289) |
| `src/db/retract.py` | T210, T233: снятие сданной проверки из истории |
| `src/db/review_edit.py` | Правка проверки на приёмке сверх исправления записи: новая запись и кадры (D465) |
| `src/db/revise.py` | Правка записи проверки на приёмке — вместе с пересчитанной оценкой (D200) |
| `src/db/spaces.py` | Пространства и их страны — заводит команда проекта (D284, D287, волна 1 — #340) |
| `src/db/swarm_read.py` | Чтение для API Swarm (#567, D387): рейтинги, собираемость, нарушения, проверки |
| `src/db/synonyms.py` | T284: карта синонимов формулировок — где живёт выученное (D119) |
| `src/db/translate_modes.py` | Перевод комментариев на язык отчёта, выбранный аудитором (D443): чтение и запись |
| `src/db/trips.py` | Поездки «Календаря» (D497, D505, D506): чтение и запись |
| `src/db/unit_profiles.py` | Справочник сведений о пиццериях (`unit_profiles`, миграция 0046): запись и чтение |
| `src/db/units.py` | Нормализация названия точки для сопоставления повторного ввода |
<!-- map:end -->

### Учётки, экшн-планы, предписания, рейтинги

<!-- map:begin files src/db/{action_plans,agg_store,api_access,busy_lock,job_lock,journals,maps_store,model_key,model_usage,oauth_store,prescriptions,prescriptions_write,rate_window,ratings,ratings_read,ratings_sync,second_factor,secret_crypto,web_access,web_own_profile,web_throttle,web_unlock}.py -->
| Файл | Что делает |
|---|---|
| `src/db/action_plans.py` | Экшн-планы: запрос, версии файла, приём и возврат (волна 2, D263–D274) |
| `src/db/agg_store.py` | Оценки в агрегаторах доставки в базе (схема `agg`, миграция 0050) |
| `src/db/api_access.py` | Сервисные токены внешнего API и журнал обращений (D356, D388, #568) |
| `src/db/busy_lock.py` | Замок «уже выполняется» между процессами (F-110): дедуп дорогих операций |
| `src/db/job_lock.py` | Замки плановых загрузчиков бота (F-125): один процесс на загрузку |
| `src/db/journals.py` | Журнал входов и журнал действий (D462, `0067`): запись и чтение |
| `src/db/maps_store.py` | Оценки на картах в базе (схема `maps`, миграция 0044): запись снимка и чтение |
| `src/db/model_key.py` | Ключ модели из базы (D491): запись, чтение, кэш на минуту |
| `src/db/model_usage.py` | Расход модели (D537, `0078`): запись вызова и чтение сводки для экрана |
| `src/db/oauth_store.py` | Хранилище OAuth: клиенты, коды, подключения и токены (D417, миграция `0054`) |
| `src/db/prescriptions.py` | Предписания: черновик, отправка через Gmail сотрудника, ответ партнёра, закрытие (волна 3) |
| `src/db/prescriptions_write.py` | Предписания: запись — черновик, отправка, закрытие (УК) и ответ партнёра (волна 3) |
| `src/db/rate_window.py` | Общее скользящее окно частоты запросов (F-110, миграция `0082`) |
| `src/db/ratings.py` | Запись рейтингов РС/РКО: журнал загрузок и строки схемы `ratings` (0039) |
| `src/db/ratings_read.py` | Чтение рейтингов для сводки и экрана «Загрузки», правка справочников (0039) |
| `src/db/ratings_sync.py` | Забор общей таблицы контроля: состояние по листам и заявки «Забрать сейчас» (D464) |
| `src/db/second_factor.py` | Вторая ступень входа (D463, `0068`): хранение и одноразовые переходы |
| `src/db/secret_crypto.py` | Шифрование секретов, которые лежат в базе (D491): AES-256-GCM, ключ — вне базы |
| `src/db/web_access.py` | Учётки и сессии веб-админки: кто входит и чем это подтверждается (T323) |
| `src/db/web_own_profile.py` | Свой профиль с экрана «Настройки» (D447): почта Google и язык сайта — уровень базы |
| `src/db/web_throttle.py` | Ограничитель перебора пароля на форме входа (T325, решения D154 и D155) |
| `src/db/web_unlock.py` | Снятие запрета на вход: дверь роли администратора истории (T328, D158) |
<!-- map:end -->

### Миграции

Файл применяется один раз в своей транзакции; применённый не правится (отпечаток
не совпадёт, накат откажет). Новая миграция — следующий номер, см. таблицу «по
задаче» ниже. Какие таблицы заводит каждая — в [`inventory.md`](inventory.md).

<!-- map:begin migrations -->
| Миграция | Что заводит |
|---|---|
| `0001_initial_schema.sql` | Схема блока db (T091): арендатор, точка, проверка, находка, кадр |
| `0002_unit_directory.sql` | T092: справочник точек и карта синонимов |
| `0003_tenant_scoped_reads.sql` | T110: чтение проверок стало обязательно арендаторским (`list_inspections` больше не отдаёт чужие проверки и не отдаёт всё разом) |
| `0004_finalized_write_protection.sql` | T111: завершённую проверку нельзя переписать и нельзя удалить |
| `0005_reads_by_period.sql` | T114: чтение научилось отбирать период и читать находки, и схеме от этого нужны другие индексы, чем от чтения «последних N по дате слива» (0003) |
| `0006_kind_is_a_code.sql` | T178: колонка `inspections.kind` хранит КОД вида проверки, а не слово, — и до этой миграции схема об этом молчала |
| `0007_model_suggestion.sql` | T164 (D077): предложение модели сохраняется рядом с итоговой записью |
| `0008_auditor_words.sql` | T185: сырые слова аудитора сохраняются рядом с записью |
| `0009_inspection_info.sql` | T200 (#163): информационная часть проверки получает место в базе |
| `0010_retracted_inspections.sql` | T210, T233: сданную проверку можно СНЯТЬ из истории |
| `0011_mcp_personal_access.sql` | T253, решения D098 и D099: доступ к MCP выпускается ЧЕЛОВЕКУ, а не стороне |
| `0012_phrase_aliases.sql` | T284: карта синонимов формулировок |
| `0013_phrase_alias_curation.sql` | T292: неверный синоним снимается и переправляется — правом, а не накатом |
| `0014_web_accounts.sql` | T323, решения D154 и D155: у веб-админки появляется вход |
| `0015_web_login_attempts.sql` | T325, решения D154 и D155: перебор пароля на форме входа перестаёт быть бесплатным |
| `0016_web_unlock.sql` | T328, решение D158: запертый вход открывается не только временем |
| `0017_unit_geography.sql` | T335: у точки появляется география |
| `0018_inspection_reports.sql` | T336 (#317): готовый отчёт проверки перестаёт жить только в телеграме |
| `0019_partner_letters.sql` | T333 (#310): правленое письмо партнёру перестаёт исчезать |
| `0020_web_user_roles.sql` | T338 (#322): учётками управляют из админки, а не из командной строки |
| `0021_web_user_email.sql` | T332 (#308): вход через учётку Google опознаёт человека по почте |
| `0022_web_password_change.sql` | T340 (#323): паролю учётки нужна смена |
| `0023_inspection_checklist_code.sql` | T345 (#262): продукт работает не с одним чек-листом, а с несколькими (D177), и проверка обязана помнить, ПО КАКОМУ из них её считали |
| `0024_finding_repeat.sql` | #359 (D191): повтор нарушения стоит вдвое, и проверка обязана помнить, какая запись была засчитана как повтор |
| `0025_inspection_moves.sql` | D195: у проведённой проверки можно сменить дату и пиццерию, и каждая такая правка остаётся в истории |
| `0026_photo_previews.sql` | D219: у записи в карточке проверки видны прикреплённые кадры — сжатой копией, «не в максимальном качестве, а в достаточном, чтоб было видно» |
| `0027_tenant_hq.sql` | Код тенанта — ключ, а не подпись: он стоит в восьми таблицах, и в четырёх из них — внутри составной ссылки на точку `(tenant_code, unit_id)` |
| `0028_login_across_spaces.sql` | Волна 1 пространств (#340, D282): у каждого человека свой логин, уникальный во всей системе, и один адрес админки на все пространства |
| `0029_space_countries.sql` | Волна 1 пространств (#340, D284): одна страна — один партнёр |
| `0030_inspection_unit_of_space.sql` | Волна 1 пространств (#340, D284): справочник пиццерий один |
| `0031_bot_bindings.sql` | D286: бот привязывается через веб |
| `0032_web_own_password.sql` | #324: человек меняет СВОЙ пароль с экрана |
| `0033_definer_search_path.sql` | Функции владельца (`security definer`) — с `pg_temp` ПОСЛЕДНИМ в пути поиска и с полными именами таблиц |
| `0034_inspection_acceptance.sql` | D199: у проверки появляется этап приёмки |
| `0035_bot_ui_langs.sql` | D303 (#411): аудитор сам выбирает язык бота, и выбор живёт за ЧЕЛОВЕКОМ — переживает проверки и перезапуск бота |
| `0036_action_plans.sql` | Экшн-планы, волна 2 спеки «Страна, предписания и экшн-планы» (D263–D265, D267–D269, D272, D274) |
| `0037_prescriptions.sql` | Предписания, волна 3 спеки «Страна, предписания и экшн-планы» (D266, D268–D270, D275) |
| `0038_inspection_import.sql` | D305–D310: исторические проверки загружаются через MCP поштучно |
| `0039_ratings.sql` | Рейтинги РС и РКО (спека docs/superpowers/specs/2026-10-08-ratings-design.md, D317–D329) |
| `0040_control_role.sql` | Роль веб-учётки «контроль» (D319, спека «Рейтинги»): загружает рейтинги и правит их справочники; чек-листы, методику, веса и людей не трогает |
| `0041_superadmin.sql` | Главный админ и пространства партнёров с экрана «Пользователи» (#585, D362, D364) |
| `0042_import_modes.sql` | D332, D334: загрузка проверок через MCP работает в ДВУХ явно разграниченных режимах, и режим — это происхождение проверки |
| `0043_ratings_layout.sql` | Компоновка страницы «Рейтинги» (D368, D370): какие блоки показывать и в каком порядке |
| `0044_maps.sql` | Оценки пиццерий на картах (Google, Яндекс и др.) из Pointer API (docs/09-pointer-api.md) |
| `0045_maps_link.sql` | Связь филиала Pointer с пиццерией Dodo (docs/09-pointer-api.md) |
| `0046_unit_profiles.sql` | Справочные сведения о пиццерии из «Свода пиццерий» девелопмента (D374–D376): адрес, партнёр и его почта, статус, даты запуска ресторана и доставки, закрытие, помещение |
| `0047_maps_excluded.sql` | Филиал на картах, который не пиццерия (тестовая карточка, учебный центр), — исключается из оценок стран и пиццерий (D453) |
| `0048_ratings_clusters.sql` | Кластер страны IMF для сводки рейтингов (D383, D384): CEE — вся Европа, остальные — OTHER (Other countries) |
| `0049_api_tokens.sql` | Сервисные токены внешнего API и журнал обращений (D356, D388, #568) |
| `0050_aggregators.sql` | Оценки пиццерий в агрегаторах доставки — Wolt, Glovo, Bolt Food, Яндекс Еда, Yemeksepeti и другие (#638, D389, docs/17-aggregators.md) |
| `0051_units_registry.sql` | Реестр пиццерий Dodo для экрана «Пиццерии на площадках» и автопоиска точек в агрегаторах (D424, docs/17-aggregators.md) |
| `0052_api_methods.sql` | Права сервисного токена — по методам API, а не двумя крупными кусками (D425) |
| `0053_agg_requests.sql` | Заявка на обновление оценок агрегаторов вне суточного расписания (D420, docs/17-aggregators.md) |
| `0054_oauth.sql` | Подключение Claude к decimus входом через сайт (D417): OAuth 2.1 с PKCE |
| `0055_maps_ratings_index.sql` | Индекс под выборки «последняя оценка филиала на карте» (`maps_store.latest`) и «оценка пиццерии на карте на дату» (`maps_store.unit_scores`) |
| `0056_finish_modes.sql` | D449: «Завершить» в мини-аппе работает в одном из двух режимов, и каждый аудитор выбирает свой в настройках приложения: `summary` — сначала сводка в чат, `report` … |
| `0057_checklist_langs.sql` | D451: язык чек-листа, выбранный аудитором на старте проверки в мини-аппе, запоминается за ЧЕЛОВЕКОМ — на следующем старте экран подставляет его же |
| `0058_translate_modes.sql` | D443: перевод комментариев на язык отчёта — автоматически или по кнопке, и каждый аудитор выбирает свой в настройках мини-аппа: `button` — переводит сам по кнопке под… |
| `0059_mcp_token_identity.sql` | Личный токен MCP принадлежит учётке сайта и получает срок; круг доступа к MCP снимается (аудит 12.10.2026, F-017/F-022/F-023/F-035/F-036; решения D417, D420, D447, D448) |
| `0060_d440_roles.sql` | Роли УК по D440: «бизнес-девелопер» (`developer`) вместо аудитора УК и «гость» (`guest`) — вся сеть на чтение |
| `0061_web_own_google_lang.sql` | «Настройки» (D447): человек сам привязывает и снимает свою почту Google и хранит язык сайта в профиле |
| `0062_space_isolation.sql` | Изоляция пространств на уровне базы (аудит 12.10, F-037, F-005) |
| `0063_freeze.sql` | «Заморозить» (D462, шаг 1): отключение учётки становится заморозкой — одним действием закрывается всё, чем человек входил, и записывается, кто заморозил |
| `0064_ratings_sheet.sql` | Общая таблица контроля «база рейтингов» как источник РС и РКО (D464, docs/15-ratings.md) |
| `0065_web_own_google_profile.sql` | Имя и фото из Google в блоке учётки (D468) |
| `0066_move_with_action_plan.sql` | Перенос проверки в пиццерию другой страны не оставляет по ней экшн-план (приватный advisory GHSA-wqh3-3qcr-cccp) |
| `0067_journals.sql` | Два журнала на случай взлома учётки (D462, шаг 2): «кто и откуда входил» и «что делали админы» |
| `0068_second_factor.sql` | Вторая ступень входа (D463): ключ доступа (passkey, Touch ID), код из приложения- аутентификатора (TOTP, RFC 6238) и одноразовые резервные коды |
| `0069_passkey_login.sql` | Вход ключом идёт с формы входа, до того как известно, кто пришёл: вызов выдаётся браузеру без учётки (ключ находится по номеру, а не по логину) |
| `0070_model_key.sql` | Раньше ключ жил только в окружении процессов (`OPENAI_API_KEY`), и сменить его значило править `.env` на площадке |
| `0071_finding_reading.sql` | #855 (D495): показание термометра, которое аудитор подтвердил или исправил (#836), — факт проверки и обязано пережить сдачу |
| `0072_ratings_clusters_four.sql` | Четыре кластера стран вместо двух (D502): CEE — Европа, TR — Турция (большой отдельный проект), CAUCASUS — Кавказ, OTHER — остальные страны |
| `0073_inspection_by_process.sql` | D507: «Где сеть теряет проценты» на главной читается по процессам (блокам методики), а не по зонам |
| `0074_trips.sql` | Поездки на «Календаре» (D497, D505, D506): кто едет, куда, с какого по какое число и план по дням — время, что происходит, пиццерия, заметка |
| `0075_email_unique_live.sql` | Почта входа через Google уникальна только среди ЖИВЫХ учёток (аудит 12.10, F-031) |
| `0076_google_sub.sql` | Номер аккаунта Google (`sub`) за учёткой (аудит 12.10, F-027) |
| `0077_web_country_filter.sql` | «Страны» (D536): постоянный отбор стран у человека — «мне нужен только Кавказ» |
| `0078_model_usage.sql` | Расход модели (D537): одна строка на каждый вызов провайдера — когда, какого вида, какая модель, сколько токенов на входе и выходе (или секунд звука), кто спросил, в… |
| `0079_units_merged_into.sql` | D538: название пиццерии — латиницей по справочнику (`unit_profiles`); другие написания («Тбилиси-1») — только синонимы |
| `0080_ratings_layout_compare.sql` | D551 (#972): блок «Сравнение девелоперов и стран» на «Рейтингах» — только УК |
| `0081_inspection_edits.sql` | Журнал правок записей проверки на приёмке (аудит F-134, #1006) |
| `0082_rate_windows.sql` | Общее скользящее окно частоты запросов (аудит F-110, #1006) |
| `0083_ratings_layout_aggregators.sql` | D585: агрегаторы на «Рейтингах» — своя плитка выше, а не часть блока карт |
<!-- map:end -->

## src/mcp — MCP-сервер

JSON-RPC поверх одного POST на локальной петле, личный токен в заголовке. Каталог
инструментов — `catalogue.py` (`TOOLS`); какой вид инструмента открыт какой роли —
`policy.py`. Полный перечень с описаниями — [`inventory.md`](inventory.md).

<!-- map:begin files src/mcp/*.py -->
| Файл | Что делает |
|---|---|
| `src/mcp/__main__.py` | Запуск MCP-сервера: `python -m src.mcp` (или `make mcp`) |
| `src/mcp/audit.py` | Журнал изменяющих вызовов MCP: кто, какой инструмент, чем кончилось |
| `src/mcp/catalogue.py` | Каталог инструментов MCP: чем агент партнёра может спросить у базы проверок и чем поправить |
| `src/mcp/checklist.py` | Хранилище версий методики: правка через агента идёт в новую версию, а не поверх боевой |
| `src/mcp/checklist_layout.py` | Раскладка хранилища методик: пространство, чек-лист, издания |
| `src/mcp/checklist_source.py` | Исходник эталона для того, кого по нему проверяют (T315, D132) |
| `src/mcp/checklist_tools.py` | Инструменты методики: что агент может прочитать и изменить в чек-листе |
| `src/mcp/checklists.py` | Чек-листы как сущности: перечень, заведение с нуля, состояние, применение к проду |
| `src/mcp/checklists_tools.py` | Инструменты MCP уровня чек-листа: перечень, заведение, состояние, применение к проду |
| `src/mcp/cli.py` | Точка запуска сервера, отделённая от `__main__` ради проверяемости |
| `src/mcp/config.py` | Окружение MCP-сервера: чей токен, чьи проверки, на каком адресе слушать |
| `src/mcp/confirm.py` | Двухшаговое подтверждение опасных инструментов MCP (F-130, #1006) |
| `src/mcp/db_target.py` | Непригодное окружение базы — «не задано» или «ведёт не туда» (#521) |
| `src/mcp/errors.py` | Отказы блока `mcp` |
| `src/mcp/import_batch.py` | `import_add_findings`: пакетная запись подтверждённых находок (#1017) |
| `src/mcp/import_catalogue.py` | Каталог инструментов загрузки проверок задним числом (D305–D310, D332–D335): описания для агента |
| `src/mcp/import_info.py` | Информационная часть загруженной проверки: `import_info_fields`, `import_set_info` |
| `src/mcp/import_modes.py` | Два режима загрузки проверок задним числом (D332, D334): что каждый принимает |
| `src/mcp/import_photo_link.py` | `import_photo_upload_link`: ссылка, по которой кадры к черновику идут мимо модели |
| `src/mcp/import_suggest.py` | `import_suggest_items`: подбор пунктов чек-листа по словам находки (#1015) |
| `src/mcp/imports.py` | Инструменты загрузки проверок задним числом поштучно (D305–D310, D332–D335) |
| `src/mcp/info_part.py` | Информационная часть записанной проверки в карточке чтения (T207) |
| `src/mcp/install.py` | Скрипт установки, который сервер отдаёт по публичному GET (#244, D112) |
| `src/mcp/instructions.py` | Текст `instructions` рукопожатия MCP: как вести загрузку проверки (#1018) |
| `src/mcp/letters.py` | Письмо партнёру по записанной проверке — для протокола MCP |
| `src/mcp/methodologies.py` | Какими методиками оценены проверки ряда — справка, а не запрет (D365) |
| `src/mcp/move.py` | Инструмент «исправить дату или пиццерию проверки» (D195) — та же функция, что у веба |
| `src/mcp/photo_cues.py` | Карта слов: правка через агента, версиями (T144, issue #115) |
| `src/mcp/phrases.py` | Карта синонимов формулировок глазами управляющей компании (T294) |
| `src/mcp/policy.py` | Права MCP по роли учётки сайта — по той же матрице, что веб и бот (D408, D417) |
| `src/mcp/ratelimit.py` | Предел частоты запросов к MCP: по токену и по адресу клиента |
| `src/mcp/ratings_read.py` | Чтение рейтингов через Claude (D420): сводка, пиццерии, состояние агрегаторов |
| `src/mcp/ratings_tools.py` | Управление рейтингами через Claude: загрузка (D320) и заявка на обновление агрегаторов (D420) |
| `src/mcp/retraction.py` | Инструмент «отклонить проверку из истории» (T211, решения D086 и D089) |
| `src/mcp/route.py` | Порядок обхода точки: правка `route.csv` через агента (T317, хвост T313) |
| `src/mcp/rpc.py` | Разбор сообщений MCP: JSON-RPC 2.0 поверх одного POST-запроса |
| `src/mcp/scoring.py` | Ставки вычетов и начальный процент версии методики — чтение (T348) |
| `src/mcp/server.py` | Транспорт MCP-сервера: HTTP на локальной петле, личный токен в заголовке |
| `src/mcp/suggestions.py` | Предложения для управляющей компании: где модель промахнулась и что дописать в карту слов |
| `src/mcp/tools.py` | Инструменты чтения: что именно агент может спросить у базы проверок |
| `src/mcp/uncovered.py` | Накопитель непокрытых формулировок глазами управляющей компании (T270) |
<!-- map:end -->

## src/bot — телеграм-бот

Диалог аудитора: мастер начала проверки, фиксация с кадра или словами, правка в
чате, завершение с PDF и письмом. Сборка диспетчера — `app.py`; обработчики по
командам и кнопкам — `routers/`. Состояние проверки — файлы, не база (читает и
пишет `src/domain`).

<!-- map:begin files src/bot/*.py -->
| Файл | Что делает |
|---|---|
| `src/bot/__main__.py` | Запуск бота: `python -m src.bot` |
| `src/bot/access.py` | Кто работает ботом и в каком пространстве (D286, волна 1 — #340) |
| `src/bot/agg_loader.py` | Раз в сутки (D389) и по заявке (D420) — оценки пиццерий в агрегаторах доставки (docs/17-aggregators.md) |
| `src/bot/albums.py` | Склейка альбома по `media_group_id` в один материал (задача T054) |
| `src/bot/app.py` | Сборка бота: диспетчер, роутеры, доступ, запуск (задача T050) |
| `src/bot/auditor.py` | Имя проверяющего по Telegram ID (задача T063, решение D032) |
| `src/bot/config.py` | Окружение бота: токен, кому отвечать, как запускаться |
| `src/bot/dates.py` | Разбор даты из живой фразы аудитора — перенесён в домен (`src/domain/dates.py`) |
| `src/bot/errors.py` | Отказы блока `bot` |
| `src/bot/finish_translate.py` | Автоперевод комментариев при сборке отчёта (D443) |
| `src/bot/frame_copies.py` | Копии присланных кадров на диске площадки, на 7 дней (#367, решение владельца D179) |
| `src/bot/image_convert.py` | Приведение присланной картинки к JPEG (#1023) |
| `src/bot/image_input.py` | Кадр, присланный файлом, а не фото (#1023) |
| `src/bot/info.py` | Информационная часть проверки: какие поля спрашиваются и чем они разные (T158) |
| `src/bot/inspection.py` | Чтение проверки так, чтобы бот не онемел ни на одной форме порчи (T126) |
| `src/bot/item_labels.py` | Пункт чек-листа для аудитора в чате: «Порядок 13», а не `CLN13` (20.10.2026) |
| `src/bot/journal.py` | Журнал разбора проверки: что система увидела, предложила и что сделал человек (#367, D179) |
| `src/bot/keyboards.py` | Инлайн-клавиатуры мастера начала проверки (T050, T051, T052) |
| `src/bot/lang.py` | Языки этого чата — так, чтобы на них нельзя было упасть (T126) |
| `src/bot/lang_choice.py` | Кто говорит с ботом прямо сейчас и какой язык он выбрал (D303, #411) |
| `src/bot/maps_loader.py` | Раз в сутки — оценки пиццерий на картах из Pointer (docs/09-pointer-api.md) |
| `src/bot/material.py` | Связывание фото нарушения с комментарием аудитора |
| `src/bot/mcp_setup.py` | Строка настройки Claude Desktop: свой мост, штатный `plutil`, никакого Node (#222, D103) |
| `src/bot/merged.py` | Кадр того же нарушения — в уже занятую запись (#443, решения D243, D247) |
| `src/bot/pending.py` | Что в этом чате ждёт нажатия кнопки: вопрос «Разобрать?» и показанные предложения |
| `src/bot/photo_backfill.py` | Дозагрузка кадров, не легших в хранилище на сдаче (#459) |
| `src/bot/photos.py` | Получение файлов из телеграма: кадры для разбора и для отчёта, голос для транскрипции |
| `src/bot/phrases.py` | Карта синонимов формулировок со стороны разговора (T285, решение D119) |
| `src/bot/propose.py` | Предложения по кадрам и словам аудитора — общее ядро бота и мини-аппа (D330) |
| `src/bot/reading.py` | Показание термометра: разбор ответа аудитора и подпись числа (#836) |
| `src/bot/refusal.py` | Отказ движка — сырьё, а не сообщение (задача T127) |
| `src/bot/repeats.py` | Вопрос о повторе: такой же пункт уже был нарушением в предыдущей проверке точки |
| `src/bot/reply_words.py` | Короткие ответы словами, которые правят запись без разбора (D254, D255) |
| `src/bot/report_lang.py` | Язык отчёта в конце проверки (D415): какие языки предложить этой пиццерии |
| `src/bot/roster.py` | Связки «юзернейм → Telegram ID», собранные по приглашениям до D286 (#230) |
| `src/bot/run_guard.py` | Память бота о проверке и чужой старт: сверка личности проверки (D392) |
| `src/bot/sealed.py` | Сданная проверка не правится (задача T201, решение владельца D080) |
| `src/bot/sheet_loader.py` | Раз в несколько часов и по заявке — забор общей таблицы контроля «база рейтингов» (D464, docs/15-ratings.md) |
| `src/bot/shown.py` | Карты «сообщение → запись»: чем бот показал запись и из чего она выросла |
| `src/bot/sidecar.py` | Заметки бота рядом с проверкой: то, чего нет ни у движка, ни в отчёте |
| `src/bot/start_options.py` | Что предлагает начало проверки: открытые чек-листы пространства человека |
| `src/bot/states.py` | Состояния диалога старта проверки (T050, T051, T052) |
| `src/bot/stops.py` | Отказы, которые останавливают мастер проверки: журнал и счётчик (#436) |
| `src/bot/texts.py` | Тексты интерфейса бота: каталог по ключам, язык — параметр |
| `src/bot/unit_pick.py` | Пиццерия проверки — из справочника, а не из написанного (D196) |
| `src/bot/upload_sweeper.py` | Уборка брошенных кадров мини-аппа по расписанию (F-033, #531) и старых записей журналов |
| `src/bot/usage.py` | Учёт расхода модели в боте (D537): чья проверка стоит за вызовом |
| `src/bot/version.py` | Версия сборки: чем именно отвечает этот процесс (T246, #201) |
| `src/bot/view.py` | Из чего складываются строки, которые аудитор читает в чате |
| `src/bot/zones.py` | Зона из слов аудитора (задача T124, решения D047 и D048, правило 6) |
<!-- map:end -->

### Роутеры бота

<!-- map:begin files src/bot/routers/*.py -->
| Файл | Что делает |
|---|---|
| `src/bot/routers/correct.py` | Правка записи ОТВЕТОМ на сообщение бота (задача T204, решение D081) |
| `src/bot/routers/edit.py` | Правки записи прямо в чате: кнопки «Зона» и «Удалить», ответ на вопрос о повторе (T056) |
| `src/bot/routers/fallback.py` | Последний рубеж нажатий: кнопка, которую некому обработать (T134, issue #105) |
| `src/bot/routers/finish.py` | Завершение проверки: итог, предвычитка, отчёт и письмо (T058, T068) |
| `src/bot/routers/help.py` | Краткая справка «как работать с ботом» (#257) |
| `src/bot/routers/info.py` | Информационная часть в конце проверки (T158, решения D069, D070) |
| `src/bot/routers/lang.py` | Выбор языка бота человеком (D303, #411): `/lang` и кнопки языков |
| `src/bot/routers/material.py` | Приём материала: кадры, альбомы и связывание с комментарием (T053, T054, T059) |
| `src/bot/routers/mcp.py` | Настройка подключения к MCP: личный токен человеку на его учётку (T209, T253, T261) |
| `src/bot/routers/record.py` | Разбор материала и фиксация записи (T055, T057, T067, T117, T121) |
| `src/bot/routers/records.py` | Показ записанного посреди обхода: «что я записал» (T139, задача #110) |
| `src/bot/routers/resend.py` | Повторная отправка отчёта по уже завершённой проверке (#261, D122) |
| `src/bot/routers/start.py` | Начало проверки и продолжение незавершённой (T050, T051, T052, T063) |
| `src/bot/routers/stops.py` | `/stops` — счётчик отказов мастера за период, только админам (#436) |
| `src/bot/routers/version.py` | Команда «какая это сборка» (T246, #201) |
<!-- map:end -->

## src/ratings — рейтинги и оценки площадок

Раздел «Рейтинги»: разбор выгрузок РС/РКО, расчёты сводки, оценки на картах
(Pointer) и в агрегаторах. Чистые функции над прочитанным; запись и чтение —
`src/db/ratings*.py`, `maps_store.py`, `agg_store.py`.

<!-- map:begin files src/ratings/*.py -->
| Файл | Что делает |
|---|---|
| `src/ratings/base.py` | Листы общей таблицы контроля «база рейтингов» (D464) |
| `src/ratings/compare.py` | Сравнение девелоперов и стран рядом (D551, #972) — только для УК |
| `src/ratings/countries.py` | Страны выгрузок рейтинга → код ISO |
| `src/ratings/coverage.py` | Охват пиццерий на площадках — картах и агрегаторах (D424) |
| `src/ratings/csvio.py` | Чтение CSV выгрузок: кодировка, разделитель, номера строк |
| `src/ratings/directory_feed.py` | Справочник пиццерий из рейтингов РС и РКО (D556, #981) |
| `src/ratings/feed.py` | Ответы API Swarm по рейтингам (#567, D387): чистая сборка над прочитанными строками |
| `src/ratings/formats.py` | Три CSV-выгрузки рейтинга Dodo IS и узнавание формата по заголовку |
| `src/ratings/importer.py` | Дверь загрузки рейтингов: байты → разбор → одна транзакция → отчёт |
| `src/ratings/layout.py` | Компоновка страницы «Рейтинги» (D368, D370): порядок и видимость блоков |
| `src/ratings/links.py` | Ссылки Dodo IS в выгрузках рейтинга: id пиццерии, проверки и периода |
| `src/ratings/maps.py` | Оценки на картах: загрузка из Pointer и сводка по странам для страницы рейтингов |
| `src/ratings/maps_link.py` | Связь филиала Pointer с пиццерией Dodo — по координатам |
| `src/ratings/matching.py` | Сопоставление пиццерии рейтинга без id (D323): нормализация, разбор, допуск опечаток |
| `src/ratings/model.py` | Общие типы рейтингов РС и РКО: что разборщики отдают импортёру |
| `src/ratings/periods.py` | Период отчёта: месяц, квартал, период рейтинга РС (спека «Словарь», решение плана 12) или произвольный отрезок «с — по» из календаря |
| `src/ratings/pointer.py` | Клиент Pointer API: сети и филиалы с текущими оценками на картах |
| `src/ratings/report.py` | Сводка раздела «Рейтинги» (D324): отбор → чтение → расчёты `summary` |
| `src/ratings/sheet.py` | Лист «Качество по пиццериям» таблиц контроля (`sheet-scores`, D324) |
| `src/ratings/sheet_sync.py` | Забор общей таблицы контроля «база рейтингов» самим decimus (D464) |
| `src/ratings/snapshot.py` | Снимок рейтинга Dodo IS (JSON) — то, что Claude собирает в браузере сотрудника |
| `src/ratings/summary.py` | Расчёты сводки рейтингов (D324): чистые функции над уже прочитанными фактами |
| `src/ratings/svod.py` | «Свод пиццерий» девелопмента → справочник `unit_profiles` (D374–D376) |
| `src/ratings/units_view.py` | Оценки пиццерий одним списком: РС, РКО, карта и агрегаторы (D420) |
<!-- map:end -->

### Агрегаторы доставки

Один модуль на площадку; общий обход, привязка к пиццериям и страж — `collect.py`.
Бот запускает сбор раз в сутки (`src/bot/agg_loader.py`).

<!-- map:begin files src/ratings/aggregators/*.py -->
| Файл | Что делает |
|---|---|
| `src/ratings/aggregators/__main__.py` | Руками (на площадке — `docker exec decimus-bot-1 python -m src.ratings.aggregators …`): |
| `src/ratings/aggregators/alert.py` | Уведомление о сбое суточного сбора агрегаторов (D434) |
| `src/ratings/aggregators/base.py` | Общее для сборщиков агрегаторов: найденная точка, HTTP с паузой и повтором |
| `src/ratings/aggregators/bolt.py` | Bolt Food: публичный поиск заведений у координат |
| `src/ratings/aggregators/chowdeck.py` | Chowdeck (Нигерия): оценка известной точки по id заведения |
| `src/ratings/aggregators/collect.py` | Сбор оценок во всех агрегаторах: обход, привязка к пиццериям, страж, запись |
| `src/ratings/aggregators/glovo.py` | Glovo: оценка известной точки по id магазина и координатам доставки |
| `src/ratings/aggregators/glovo_link.py` | Glovo: новые точки находятся сами или привязываются по ссылке (D424, #648) |
| `src/ratings/aggregators/migros.py` | Migros Yemek (Турция): оценка известной точки по адресу её страницы |
| `src/ratings/aggregators/migros_link.py` | Привязка пиццерии к Migros Yemek по ссылке на страницу магазина (#717) |
| `src/ratings/aggregators/migros_relay.py` | Ретранслятор Migros Yemek на домашнем сервере (D434) |
| `src/ratings/aggregators/pyszne.py` | Pyszne.pl (Just Eat Takeaway, Польша): витрина у координат |
| `src/ratings/aggregators/queue.py` | Заявка на обновление оценок агрегаторов вне расписания (D420) |
| `src/ratings/aggregators/summary.py` | Сводка оценок агрегаторов по группам сводки (кластер, страна, срез) |
| `src/ratings/aggregators/trendyol.py` | Trendyol Go (бывший Trendyol Yemek, Турция): подсказки поиска и карточка |
| `src/ratings/aggregators/wolt.py` | Wolt: каталог заведений у координат пиццерии |
| `src/ratings/aggregators/yandex_eda.py` | Яндекс Еда: поиск у координат пиццерии, затем карточка заведения |
| `src/ratings/aggregators/yemeksepeti.py` | Yemeksepeti (Delivery Hero, Турция): витрина заведений у координат |
<!-- map:end -->

## src/domain — предметная область

Методика, состояние проверки, маршрут обхода, вызов движка подпроцессом. Не знает ни
Telegram, ни HTTP, ни SQL.

<!-- map:begin files src/domain/*.py -->
| Файл | Что делает |
|---|---|
| `src/domain/bot_checklists.py` | Чек-листы, по которым аудитор может начать проверку в боте (волна 3, D221) |
| `src/domain/checklist.py` | Чтение методики: пункты чек-листа, зоны, допустимые классы, версия набора |
| `src/domain/checklist_store.py` | Раскладка хранилища методик — та её часть, которую читает бот (#455) |
| `src/domain/client_ip.py` | Чей это адрес у сервера MCP: клиент за общим прокси (D462, журнал действий) |
| `src/domain/config.py` | Окружение блока: где лежит методика, где состояние, где движок |
| `src/domain/dates.py` | Разбор даты из живой фразы аудитора (задача #220) |
| `src/domain/demo.py` | Открытое демо: учётки ролей и переключатели — контракт между посевом и входом |
| `src/domain/edition.py` | Издание методики, на котором идёт проверка, и его снимок рядом с состоянием |
| `src/domain/engine.py` | Вызов движка подпроцессом — единственный способ, которым блок его трогает |
| `src/domain/errors.py` | Отказы блока `domain` |
| `src/domain/findings.py` | Операции над записями проверки: фиксация, правка, удаление, фотографии |
| `src/domain/geo.py` | Страны и города сети: названия для людей, страна города, местные написания |
| `src/domain/handover.py` | Сдана ли проверка: признак, который ставит бот, а читают и бот, и мини-апп (D080, D312) |
| `src/domain/info.py` | Информационные поля проверки — блок `info` состояния (T158, решения D069, D070) |
| `src/domain/info_fields.py` | Состав информационной части проверки: какие поля и каким способом вводятся (T158, D312) |
| `src/domain/item_label.py` | Пункт чек-листа для человека: «Порядок 13», а не `CLN13` (решение владельца 20.10.2026) |
| `src/domain/journal.py` | Что и как попадает в журналы входов и действий (D462, `0067`) |
| `src/domain/kinds.py` | Вид проверки: код — сущность, слово — перевод (T152, задача #123) |
| `src/domain/log_ids.py` | Идентификаторы людей и пространств в журнале — меткой, а не как есть (F-015) |
| `src/domain/model_usage.py` | Расход модели (D537, `0078`): виды вызова и кто за ним стоит |
| `src/domain/models.py` | Типы предметной области, которыми блок разговаривает с остальными |
| `src/domain/permissions.py` | Матрица «роль × действие» и проверка `can` — единственное место, где решается, что роли можно (D408; роли — D440, D420, D429; партнёр — D341, D346, D367) |
| `src/domain/photo_upload_link.py` | Ссылка загрузки кадров к черновику загрузки проверки: подписанный токен без срока |
| `src/domain/public_urls.py` | Публичные адреса админки и MCP — для подключения Claude через OAuth (D417) |
| `src/domain/repeat_rule.py` | Правило «пункт уже был нарушением в прошлой проверке» (D191, D255) |
| `src/domain/report_langs.py` | Языки отчёта по странам (D415): перечень — данные, а не код |
| `src/domain/route.py` | Маршрут обхода: в каком порядке аудитор идёт по зонам и по пунктам внутри них |
| `src/domain/scoring.py` | Оценка проверки |
| `src/domain/second_factor.py` | Вторая ступень входа (D463): правила без базы и без веба |
| `src/domain/shape.py` | Оценочная форма издания: чем считали, а не что написано (T349, #337) |
| `src/domain/state.py` | Состояние проверки: чтение, старт и собственные поля блока |
| `src/domain/tenants.py` | Код тенанта управляющей компании и перевод старого кода (D234, #439) |
| `src/domain/translation.py` | Поля методики, заполненные не на том языке, на котором их напечатают (T186) |
| `src/domain/uncovered.py` | Накопитель непокрытых формулировок — случай, когда записи не появилось |
| `src/domain/unit_match.py` | Сопоставление точек справочника `units` со сведениями о пиццериях `unit_profiles` (#316, #909) |
| `src/domain/unit_name.py` | Имя пиццерии «Город-N» по-английски — из написанного как угодно (D233) |
| `src/domain/unit_new.py` | Новая пиццерия справочника из веб-админки: что заводится и почему нет (#437) |
| `src/domain/unit_resolve.py` | Одно правило имени пиццерии на бота, мини-апп, MCP, админку и загрузки (D538) |
| `src/domain/upload_sweep.py` | Уборка кадров мини-аппа, не попавших ни в одну проверку (F-033, #531) |
| `src/domain/uploads.py` | Кадры, снятые в мини-аппе обхода (D312): где лежат и как на них сослаться |
| `src/domain/version.py` | Идентификатор версии методики: имя набора, дата публикации, отпечаток данных |
| `src/domain/walk_users.py` | Кому открыт мини-апп обхода (#418): все проверяющие или только тестеры |
<!-- map:end -->

## src/recognize — разбор моделью

Единственное место, где продукт говорит с провайдером модели. Модель предлагает —
фиксирует человек. Правила разбора слов лежат данными (`language_rules.json`), имя
модели — параметр.

<!-- map:begin files src/recognize/*.py -->
| Файл | Что делает |
|---|---|
| `src/recognize/classify.py` | T031: разбор комментария аудитора в предложения записей |
| `src/recognize/client.py` | T031: единственное место, где блок разговаривает с провайдером модели |
| `src/recognize/config.py` | Настройки разбора |
| `src/recognize/cues.py` | Словарь синонимов (D523; в коде — «карта», файл `photo-cues.md`): слова → какие пункты показать |
| `src/recognize/errors.py` | Отказы блока `recognize` |
| `src/recognize/fastpath.py` | T113 (D063): быстрый путь — пункт без вызова модели, когда слова однозначны |
| `src/recognize/guard.py` | Границы на свободный текст ответа модели (F-131) |
| `src/recognize/language.py` | T192 (#157): правила разбора слов аудитора — данные, а не константы в коде |
| `src/recognize/manual.py` | T034: модель недоступна — перечень пунктов для ручного выбора кнопками |
| `src/recognize/merge.py` | Свести комментарий записи, к которой лёг ещё один кадр (#443, решение D247) |
| `src/recognize/models.py` | Что блок отдаёт наружу: предложения, а не решения |
| `src/recognize/pricing.py` | Оценка стоимости вызовов модели в долларах (D537) |
| `src/recognize/process_hint.py` | Указание аудитора «<описание>, это <процесс>» (T166, D077) |
| `src/recognize/prompt.py` | T031/T032: текст запроса к модели — правила фиксации и перечень кандидатов |
| `src/recognize/revise.py` | Правка записи ответом словами (#454, решения D294, D295) |
| `src/recognize/rules_check.py` | T032: страховка после модели — код-уровневая проверка формулировки |
| `src/recognize/schema.py` | T031: схема ответа модели |
| `src/recognize/shortlist.py` | T030: перечень кандидатов, который уходит в запрос к модели |
| `src/recognize/transcribe.py` | T033: голосовое сообщение аудитора → текст |
| `src/recognize/translate.py` | Перевод свободного текста аудитора на язык отчёта (D394, #542) |
| `src/recognize/zone_words.py` | Зона из слов аудитора: обиходные названия мест и разбор текста (T124, D047, D048) |
<!-- map:end -->

## src/report — отчёт и письмо

Сборка PDF и письма партнёру вызовом `engine/report.py` подпроцессом; пересборка, а
не пересчёт.

<!-- map:begin files src/report/*.py -->
| Файл | Что делает |
|---|---|
| `src/report/build.py` | Сборка отчёта и письма партнёру |
| `src/report/detail_pdf.py` | PDF-отчёт по записанной в базе проверке — для загруженной «текущей» (D334) |
| `src/report/engine.py` | Вызов `engine/report.py` подпроцессом — единственный способ собрать отчёт |
| `src/report/engine_call.py` | Общее для тех, кто зовёт движок подпроцессом: где он лежит, сколько ждать, что печатать |
| `src/report/errors.py` | Отказы блока `report` |
| `src/report/explain.py` | Почему оценка такая — ответ движка по записанной проверке (D490) |
| `src/report/info_titles.py` | Подписи полей информационной части — формулировки вопросов по кодам |
| `src/report/letters.py` | Письмо партнёру по уже записанной проверке — пересборка, а не пересчёт |
| `src/report/photos.py` | Где взять кадр, приложенный к записи или к информационному полю, и что считать его пропажей |
| `src/report/rescore.py` | Пересчёт записанной проверки движком — для правки на приёмке (D200) |
<!-- map:end -->

## engine/ — движок

Считает оценку и собирает PDF; запускается подпроцессом, данные берёт из
`CHECKLIST_DIR` и `INSPECTION_FILE`. Оценку не считает больше никто.

<!-- map:begin files engine/*.py -->
| Файл | Что делает |
|---|---|
| `engine/audit.py` | Движок проверки пиццерии: чек-лист, фиксация нарушений, расчёт оценки |
| `engine/manage.py` | Правка самого чек-листа: добавить, убрать, изменить вопрос; импорт из xlsx-шаблона IMF |
| `engine/report.py` | Собирает итоговый PDF-отчёт и черновик письма партнёру из inspection.json |
<!-- map:end -->

## tools/ и scripts/ — операционка

Сиды демо, замеры, учётки веб-админки, сервисные токены, проверки доступа к MCP,
бэкап состояния; раскатка и смоук. Каждая цель, которая их зовёт, — в
[`inventory.md`](inventory.md) (раздел «Makefile»).

<!-- map:begin files tools/*.py tools/*.sh tools/walk_mockup/*.py -->
| Файл | Что делает |
|---|---|
| `tools/api_token.py` | Сервисные токены внешнего API: выпустить, перечислить, отозвать (D356, D388) |
| `tools/backfill_by_process.py` | Разбивка по процессам для проверок, принятых до миграции 0073 — разовый доливщик (D507) |
| `tools/backfill_previews.py` | Сжатые копии для кадров, выгруженных до D219 — разовый доливщик |
| `tools/bench_dataset.py` | Оснастка задачи T035: офлайн-набор кадров для замера точности разбора |
| `tools/bench_run.py` | T035: замер точности разбора на боевых данных — число, а не мнение |
| `tools/comment_only_measure.py` | T202: цена решения D081 «кадр с комментарием разбирается по комментарию» |
| `tools/demo_refresh.sh` | Обновление демо-стенда из `main` (задача T102, решение D059) |
| `tools/fastpath_measure.py` | T113, T125: доля срабатываний быстрого пути — так, как его зовёт живой бот |
| `tools/gen_map.py` | Карта кода: перегенерация таблиц в docs/ между маркерами (`make map`, #731) |
| `tools/landing_shots.py` | Снимки живых экранов для посадочной страницы (D545) — одной командой |
| `tools/loadcheck.py` | Замер потолка нагрузки: сколько одновременных проверок продукт держит |
| `tools/loadcheck_live.py` | Живой замер: настоящие вызовы модели, настоящие кадры (T101, решение D062) |
| `tools/mcp_bridge.sh` | Мост stdio ↔ HTTP для MCP-сервера проверок (T095) |
| `tools/mcp_healthcheck.py` | Проба здоровья MCP-сервера — изнутри его контейнера (задача T255, #210) |
| `tools/mcp_install.sh` | Установщик подключения к MCP-серверу проверок (#244, решение D112) |
| `tools/mcp_outside.py` | Смоук доступа к MCP-серверу С ЧУЖОЙ МАШИНЫ (задача T256, #211) |
| `tools/mcp_watch.py` | Сторож доступности MCP снаружи (#243) |
| `tools/methodology_leak.py` | Проверка: методика управляющей компании не цитируется в репозитории (#138, #854) |
| `tools/oauth_smoke.py` | Сквозной прогон подключения Claude входом через сайт (D417) против живого стенда |
| `tools/porcha_core.py` | Порча ядра (#268): испорченный расчёт обязан уронить прогон |
| `tools/porcha_permissions.py` | Порча матрицы прав (D408): каждая сломанная защита обязана уронить свой тест |
| `tools/porcha_ratings.py` | Порча защит рейтингов: каждая сломанная защита обязана уронить свой тест |
| `tools/porcha_second_factor.py` | Порча второй ступени входа (D463): каждая сломанная защита обязана уронить свой тест |
| `tools/porcha_walk.py` | Порча защит мини-аппа обхода (D312): каждая сломанная защита обязана уронить свой тест |
| `tools/pre-push-guard.sh` | Сторож пуша: не пускает наружу значения из приватного списка |
| `tools/process_hint_measure.py` | T166 (D077): сколько раз признак «<описание>, это <процесс>» срабатывает зря |
| `tools/regress_check.py` | Регрессионный якорь: цифры на боевых данных не должны меняться |
| `tools/seed_demo.py` | Идемпотентный сид демо-набора (задачи T074, T100; блок infra) |
| `tools/seed_open_demo.py` | Посев открытого демо (D524): выдуманная сеть пиццерий на отдельном стенде |
| `tools/seed_ratings_demo.py` | Демо-рейтинги для веб-админки (`make web-demo`): английский, вымышленные пиццерии |
| `tools/seed_walk_stand.py` | Стенд мини-аппа обхода (#418): середина проверки и прошлая проверка той же точки |
| `tools/seed_web_demo.py` | Демо-история в базе: то, что показывает веб-админка |
| `tools/space.py` | Пространства и их страны: завести, привязать к странам, перечислить |
| `tools/state_backup.py` | Бэкап тома состояния стенда (`STATE_DIR`) в каталог бэкапа (задача #233) |
| `tools/storage_reconcile.py` | Сверка хранилища файлов с таблицами — экшн-планы и предписания (#496) |
| `tools/unit_canon.py` | Справочник пиццерий к каноническим именам «Город-N» по-английски (D233, #440) |
| `tools/units.py` | Справочник точек сети: загрузка с сайтов стран и заведение руками |
| `tools/units_normalize.py` | Привести справочник пиццерий `units` к эталону `unit_profiles` (#316, #909) |
| `tools/walk_healthcheck.py` | Проба здоровья сервиса мини-аппа обхода — изнутри его контейнера |
| `tools/walk_mockup/build.py` | Кликабельный макет мини-аппа обхода (#418) — один HTML-файл для отзывов коллег |
| `tools/web_unlock.py` | Запрет на вход: показать запертых и снять запрет |
| `tools/web_user.py` | Учётки веб-админки: завести, перечислить, заморозить |
| `tools/worktree_new.sh` | Рабочая копия для блока стройки — одинаково каждый раз |
| `tools/zone_coverage.py` | T272: покрытие словаря зон — сколько формулировок доходит до зоны и что дописать |
| `tools/zone_words_measure.py` | T242 (#198): узнаётся ли зона, названная НЕ в именительном падеже |
<!-- map:end -->

### scripts/

<!-- map:begin files scripts/*.py scripts/*.sh -->
| Файл | Что делает |
|---|---|
| `scripts/accept-clone.sh` | Свежий клон main для приёмки: клонирует, подкладывает данные вне git, ставит окружение |
| `scripts/check_run_complete.py` | Сторож полноты прогона: краснеет, когда проверки не выполнялись |
| `scripts/deploy.sh` | Раскатка на площадку одной командой (T246, #201) |
| `scripts/prod-update.sh` | Обновление прода на Linux (VPS) — запускается НА САМОМ СЕРВЕРЕ из каталога репозитория |
| `scripts/smoke.sh` | Смоук раскатанного бота на целевой площадке |
<!-- map:end -->

## front/ — Cloudflare Worker'ы

Постоянные адреса админки и MCP: Worker принимает запрос и пересылает его на сервер
без своей логики (`docs/08-deploy.md`, §8.9).

<!-- map:begin tree front -->
| Каталог | Файлов | Какие |
|---|---|---|
| `front/` | 6 | .deploy.env.example, deploy.sh, wrangler.admin.template.jsonc, wrangler.demo.template.jsonc, wrangler.mcp.template.jsonc, wrangler.stand.template.jsonc |
| `front/src/` | 2 | index.js, proxy.js |
| `front/test/` | 1 | proxy.test.mjs |
<!-- map:end -->

## По задаче → куда идти

Каждая строка сверена с кодом на 12.10.2026; поменялось устройство — поправьте
строку тем же изменением.

| Задача | Куда идти |
|---|---|
| Поправить текст экрана админки | `src/web/texts.py` или `texts_<раздел>.py`: ключ `TEXTS[ключ] = {"ru": …, "en": …}`; оба языка обязательны, `tests/test_web_texts.py` это проверяет |
| Поправить текст бота | `src/bot/texts.py` — тот же каталог по ключам; `tests/test_bot_texts.py` |
| Поправить текст письма партнёру или PDF | Тексты отчёта и письма — в `engine/report.py` (`letter_text`, `build_letter`); пересборка по записанной проверке — `src/report/letters.py`; разметка письма в почте — `src/web/letter_markup.py` |
| Добавить страницу или маршрут веба | Модуль с `install(app, conf)` по образцу `src/web/prescriptions.py`, вызов — в `create_app` (`src/web/app.py`); шаблон — `src/web/templates/<раздел>/`; тексты — `texts_<раздел>.py` и подключение в `texts.py`. Новый раздел навигации — ещё `SECTIONS` в `src/web/sections.py`, `SCREENS` в `app.py` (приложение не соберётся, если они разошлись) и `view.<раздел>` в матрице `src/domain/permissions.py`. Пишущий маршрут объявляет действие `@guard.action(...)` — без него он закрыт (403) и роняет `tests/test_web_guard.py` |
| Сделать адрес открытым без входа | Только через `OPEN_ENDPOINTS` в `src/web/auth.py` — по умолчанию закрыто всё; зачем и что открыто — `docs/18-access-map.md` |
| Дать или закрыть роли действие, ограничить раздел по роли | Одна матрица «роль × действие» — `src/domain/permissions.py` (`MATRIX`, граница — `_boundary`); веб спрашивает её заслоном `src/web/guard.py`, MCP — `src/mcp/policy.py`, бот — `src/bot/access.py`. Партнёру закрыто всё, что матрица не объявила открытым его пространству (`guard.open_to_tenant`, 404 в `_install_hq_gate` `src/web/app.py`; необъявленный маршрут называет `tests/test_web_guard.py`); «кто кем управляет» — `src/web/access_policy.py`; охват чтения — `src/db/reach.py`; потом `docs/18-access-map.md` и `make porcha-permissions` |
| Роль и права MCP | Инструмент → действие матрицы: `src/mcp/policy.py` (`action_of`, `TOOL_ACTIONS`); закрытое в Claude сверх матрицы — `CLAUDE_CLOSED` в `src/domain/permissions.py` |
| Добавить инструмент MCP | Описание и схема — запись `ToolSpec` в `TOOLS` (`src/mcp/catalogue.py`), обработчик — рядом с похожими (`tools.py`, `checklist_tools.py`, `ratings_tools.py`); какой роли он открыт, решает действие матрицы (`policy.action_of`: по виду или `TOOL_ACTIONS`); перечень — `docs/inventory.md` (`make map`), контракт — `docs/furca/blocks/mcp.md` |
| Новая миграция | Файл `src/db/migrations/NNNN_<смысл>.sql` со следующим номером, заголовок-комментарий «зачем» (первая фраза уйдёт в эту карту); накат — `make migrate`; применённый файл не править. Тест с базой — по образцу `tests/test_db_*.py` (`tests/db_harness.py`) |
| Изменить расчёт оценки, ставки, пороги букв | Расчёт — `engine/audit.py` (`score`); ставки и пороги — `scoring.json` методики, в коде не дублируются; разбор ответа движка — `src/domain/scoring.py`. После правки — `make regress` |
| Добавить или изменить пункт чек-листа, зону, критерий | Данные методики вне git; правка одной дверью — `engine/manage.py` / MCP (`src/mcp/checklist.py`) / экран «Методика» (`src/web/methodology.py`). Версии и издания — `src/domain/version.py`, `src/domain/edition.py` |
| Новая команда или кнопка бота | Роутер в `src/bot/routers/` по образцу `version.py` или `help.py`, подключение — в `src/bot/app.py` (`include_router`); тексты — `src/bot/texts.py` |
| Изменить разбор комментария моделью | Запрос — `src/recognize/prompt.py`, схема ответа — `schema.py`, быстрый путь без модели — `fastpath.py`, карта слов — `cues.py`; замеры — `make fastpath`, `make zonecov` |
| Рейтинги: новый блок страницы | Состав и порядок блоков — `BLOCKS` в `src/ratings/layout.py`; расчёты — `src/ratings/summary.py`, `report.py`; экран — `src/web/ratings.py`; тексты — `src/web/texts_ratings.py`; контракт — `docs/15-ratings.md` |
| Рейтинги: новый формат выгрузки | Узнавание по заголовку — `src/ratings/formats.py`, разбор — `csvio.py`, загрузка в транзакции — `importer.py` |
| Подключить агрегатор доставки | Модуль в `src/ratings/aggregators/` по образцу `wolt.py` (поиск у координат) или `glovo.py` (известная точка), затем строка в `SEARCHERS` или `KNOWN` в `collect.py`; описание — `docs/17-aggregators.md` |
| Метод API чтения для Swarm | Адрес и право — `src/web/swarm_api.py`, сборка ответа — `src/web/api_feed.py`, чтение — `src/db/swarm_read.py`, `src/ratings/feed.py`; права ключей — `src/db/api_access.py`; контракт — `docs/12-web-admin.md`, «API чтения для Swarm» |
| Новая переменная окружения | Читается в `config.py` своего блока (`src/<блок>/config.py`) с понятным отказом на мусор; впишите в `.env.example` с комментарием — тест `tests/test_docs_map.py` требует; `make map` обновит `docs/inventory.md` |
| Добавить язык интерфейса или отчёта | Интерфейс — языки в `src/web/texts*.py` и `src/bot/texts.py` (тесты требуют полноты по каждому языку); языки отчёта по странам — данные в `src/domain/report_langs.py`; формулировки методики — таблица `translations` (миграция `0001`) |
| Роль «администратор истории»: снять, принять, перенести проверку | `src/db/retract.py`, `src/db/accept.py`, `src/db/move.py` — под `DATABASE_RETRACTION_URL`; веб-двери — `src/web/review.py`, `src/web/revision.py`; права держит база (миграции `0010`, `0025`, `0034`) |
| Загрузить историческую проверку | `src/mcp/imports.py`, `import_modes.py`, запись — `src/db/imports.py`, `imports_legacy.py`; процедура — `docs/14-history-import.md` |
| Пространство и страны | Завести и привязать — `tools/space.py` (`make space`), логика — `src/db/spaces.py`, `src/db/reach.py` |
| Завести учётку веб-админки или ключ API | `tools/web_user.py` (`make web-user`), `tools/web_unlock.py` (`make web-unlock`), `tools/api_token.py` |
| Демо и тестовый стенд | `make demo` (бот), `make web-demo` и `make web-up` (админка), сиды — `tools/seed_*.py` |
| Раскатка и откат | `docs/08-deploy.md`; `scripts/deploy.sh`, `scripts/prod-update.sh`, смоук — `scripts/smoke.sh` |
| Написать тест | Блоки без базы — `tests/test_<блок>_*.py` с общей оснасткой `tests/*_harness.py`; с базой — `tests/test_db_*.py` (`tests/db_harness.py`), на CI пропускаются; методика тестов — `tests/methodology/` |
