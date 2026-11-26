# Операционная аналитика для Swarm

`GET /api/v1/performance?countries=RS&as_of=2026-11-15` читает только кеш Decimus,
без HTTP-запросов к Dodo IS. Право `performance:read` назначается явно; миграция
не добавляет его существующим токенам. Страны ограничиваются правами токена.
Старый `GET /api/v1/sales` и его таблица остаются самостоятельным контрактом.

`as_of` — включительная дата отсечения месяца. Без него берётся вчерашний день
в часовом поясе страны. Неизвестный пояс отмечается `timezone_fallback: true`,
используется UTC. Будущая дата и незавершённый текущий день не принимаются.
Исторический полный месяц запрашивается его последним днём.

## Окна и числа

Для 15 ноября возвращаются current 1–15 ноября, mom 1–15 октября и yoy
1–15 ноября прошлого года. В коротком месяце отсечение прижимается к последнему
дню; 29 февраля прошлого невисокосного года становится 28 февраля. Границы
всех окон включительны и выводятся в ответе.

Значения Decimal передаются строками, отсутствующие — `null`. Ноль означает
полученный из источника ноль. Разность `delta` — в единицах метрики, `delta_pct`
— относительные проценты; при нулевой базе `delta_pct: null` и
`comparison_status: zero_baseline`. Неполное покрытие не даёт процента роста.

Метрики: `revenue` (валюта в `currency`), `orders` (число), `delivery_seconds`
и `restaurant_cooking_seconds` (средние секунды), `stops_seconds` (суммарные
секунды), `stops_count`, `certificates_count` (число). Средние страны считаются
по сумме числителей и знаменателей. Если источник дал только среднее unit,
оно помечается `aggregation: source_average`; среднее страны из таких значений
недоступно. Валюты никогда не складываются и не сравниваются между собой.

## Контракт коллектора

`src/domain/performance.py`:

- `Window(start: date, end: date)`; `comparison_windows(as_of: date)` возвращает
  словарь `current`, `mom`, `yoy`.
- `Observation(country, subject_id, metric, period, value=None, numerator=None,
  denominator=None, currency=None, timezone='UTC', source='dodois',
  status='complete', covered_units=None, expected_units=None, loaded_at=None, reason=None)`.
  Числа только конечные `Decimal`. `subject_id` — ISO-2 страны либо 32hex unit.
  Среднее с известным весом передаётся числителем и знаменателем.
- `NativeLfl(country, subject_id, query: Window, granularity, date, revenue_raw,
  orders_raw, loaded_at=None, source='dodois/customer-feedback/lfl')`.

`src/db/performance.py`:

- `upsert_observations(rows: Sequence[Observation]) -> int`;
- `replace_lfl(country, query, granularity, rows: Sequence[NativeLfl]) -> int`;
- `record_load(country, kind, period, *, error_code=None) -> None`;
- `read_observations(countries, start, end) -> list[Observation]`;
- `read_lfl(countries, query) -> list[NativeLfl]`;
- `load_states(countries, period) -> list[dict]`;
- `unit_names(countries) -> dict[str, tuple[str, str]]` (unit → страна, имя).

Оконный кеш `dodois.performance_windows` хранит запрошенные периоды, источник,
пояс, числители, знаменатели, валюту и покрытие. `performance_loads` сохраняет
последнюю попытку, последнюю удачу и безопасный код ошибки для каждого окна.
Ошибка не стирает прежние удачные значения. История запрашивается у источника
при первом сборе; не требуется ждать год накопления.

## Native LFL

Dodo IS предоставляет `customer-feedback/lfl/by-units` и `by-countries`.
`performance_lfl` сохраняет неизменённые `lflRevenue` / `lflOrder`, даты запроса,
`granularity` и `date` bucket. Доказательства схемы:
[по пиццериям](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7a9cf987af1d6-lfl-lfl-po-zavedeniyam),
[по странам](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7f63c84f4d4ec-lfl-lfl-po-stranam).

Документация не определяет единицу чисел и однозначное соответствие bucket
неполному MTD. Поэтому API отдаёт `unit: source_value`,
`status: source_period_unverified`, `revenue_raw`, `orders_raw` и исходные даты.
Проценты не усредняются и собственная когорта не подменяет native LFL.

Проверка реального источника 24.11.2026 для RS и BG: запросы `Month` за 1–14
и 1–23 ноября вернули одинаковые значения и по country, и по unit. `Day` за
1–23 вернул 23 суточных bucket. Поэтому даже наличие ответа не доказывает
соответствие MTD; `reason: native_bucket_not_request_slice` остаётся явным.
Нативные bucket не получают вычисленные `delta_pct`.

`replace_lfl` вызывается один раз после объединения ответов by-units и
by-countries. При отказе одного метода неполный ответ не заменяет прежний кеш.

## Ответ

Верхний уровень: `as_of` (параметр или `null` при локальном отсечении),
`countries`. У страны: `cc`, `name`, `timezone`, `timezone_fallback`, `as_of`,
`periods`, `metrics`, `lfl`, `units`, `loads`. У unit: `dodo_id`, `name`,
`metrics`, `lfl`. У каждой метрики: `unit`, `current`, `mom`, `yoy`; у значения:
`value`, `status`, `coverage`, `loaded_at`, `stale`, `source`, `currency`.
Статусы данных: `complete`, `partial`, `unavailable`. Неизвестное покрытие
понижает `complete` до `partial`. Unit получает покрытие 1/1; активное число
unit для country передаётся коллектором явно. Если сохранённой country строки
нет, feed не считает реестр названий списком активных unit и оставляет
свёртку с неизвестным expected_units неполной. Данные старше 36 часов
помечаются `stale: true`; это отметка свежести загрузки, не полноты периода.

## Если данных нет

Проверить `loads` ответа и `dodois.performance_loads`: нужные страна, вид и
точные границы окна. `unavailable` означает отсутствие достаточных данных,
а не нулевой результат. При `partial` проверить expected/covered units и веса
средних; при `stale` — последнюю попытку коллектора и вход страны в Dodo IS.
Повторный сбор нужного окна исправляет кеш; пользовательский API сбор не запускает.

## Сбор и накопление

`src/dodois/performance.py` вызывается существующей часовой задачей
`dodois_metrics_loader.py`, под тем же advisory lock, после прежнего сбора.
До 3 стран за заход, до 6 окон на страну, общий предел 180 запросов включает
деление пачек, страницы сертификатов и повтор 429. Отметка `country_attempt`
пишется до чтения токенов и обнаружения пиццерий; ранний отказ не блокирует
ротацию остальных стран. Секреты не продлеваются, новые входы не создаются.

Приоритет — текущий срез и его MoM/YoY, затем 12 полных исторических месяцев.
MTD обновляется через 20 ч, полные исторические месяцы — через 30 дней;
повтор после отказа не чаще часа. Полные месяцы читаются последним числом
через `as_of`. История запрашивается сразу; локальные успешные окна остаются
доступны, если источник позже перестал их возвращать. Пропущенные unit не
перезаписываются нулём или `missing_unit`; неполный ответ фиксируется кодом.

Итоги выручки/заказов страны берутся из авторитетного
`finances/sales/country`; источник возвращает `result` объектом (живой HTTP200).
Это включает исторические закрытые точки без догадки по текущему списку.
Для текущих средних охват — активные точки и ответившие точки с данными.
Исторический охват средних без дат открытия/закрытия помечается
`historical_cohort_unknown`; цифра остаётся доступна, процент не утверждается.

Доставка и приготовление восстанавливаются как взвешенные средние из
округлённых секунд и количества заказов того же ответа. Источник и
`source_rounded_average` сохраняются; общее число заказов finances весом не
служит. Стопы учитывают только Complete, интервалы обрезаются окном и
объединяются в пределах точки. Redirection не смешивается с полной остановкой.
Семантика стопов, начатых до границы запроса, пока не подтверждена, поэтому
этот показатель `partial/boundary_semantics_unverified`.

Finances документирует полуинтервал `[from,to)`; запрос оканчивается в 00:00
дня после включительного отсечения. Другие методы принимают такие же
локальные timestamps, но точное включение граничного события и часовой пояс
не описаны столь же явно; это ограничение источника, а не доказанный полный
учёт пограничной секунды. Неизвестные многозонные страны используют явный
UTC fallback. Сертификаты — количество записей `delivery/vouchers` с полной
пагинацией и дедупликацией orderId; персональные поля не сохраняются.

Для BG до 2026 года валюта BGN, затем EUR ([ЕЦБ](https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.pr260101~c830245e42.en.html)). Разные валюты не сравниваются;
YoY выручки через смену валюты недоступен до приведения базы. Заказы и время
сравниваются независимо от валюты.

Проверки: `test_performance.py`, `test_performance_api.py`,
`test_performance_parse.py`, `test_performance_collector.py`. Схемы первичного
API — [исследование](research/2026-11-24-operating-metrics-api.md).

### Полнота country finance

Только точный источник `dodois/finances/sales/country` для `revenue` и `orders`
со `subject_id`, равным коду страны, считается авторитетным итогом страны.
Он может иметь `status: complete` без количества unit: покрытие помечается
`scope: source_country`, `covered_units` и `expected_units` остаются `null`.
Сопоставимые полные окна этого источника допускают вычисление MoM/YoY.
Это исключение не применяется к unit, другим источникам и другим метрикам.

## Первое включение на проде

Порядок зависимостей: код Decimus в `main` → новые образы → миграция `0135` →
запуск `web` и `bot` → явное право существующему ключу Swarm → первичный сбор
RS/BG/HR/SI → проверка ответа API → включение cockpit в Swarm. До получения
данных API возвращает `unavailable`; выкладка Swarm не должна выдавать такую
пустую загрузку за готовую главную.

Штатная команда — `docs/08-deploy.md`, §8.3:

```bash
cd /srv/decimus
DECIMUS_OVERLAYS=/srv/decimus/compose.edge.yaml scripts/prod-update.sh
```

Она сама выполняет `git pull --ff-only`, сверяет HEAD с опубликованным `main`,
собирает образы с профилями `backup` и `migrate`, проверяет образы и накатывает
схему **до** запуска нового приложения. `DATABASE_ADMIN_URL` получает только
одноразовый сервис `migrate`; запускать накат через `exec bot` нельзя.
Новые переменные окружения, OAuth-входы и учётки для performance не требуются.
Часовой сборщик включается при запуске нового образа `bot` автоматически.

В репозитории нет очереди автоматических ночных выкладок: штатный скрипт
запускается по явному разрешению владельца. Внешний одноразовый оркестратор
должен соблюдать это разрешение, установленное окно и последовательность выше.

### Право существующего сервисного ключа

Сначала сопоставить runtime-ключ Swarm с отпечатком в `api.tokens`, не выводя
ни ключ, ни отпечаток. Затем выбрать ровно одну действующую строку. Ни миграция,
ни эта процедура не выпускают новый ключ и не расширяют доступы других строк.
На VPS после миграции:

```bash
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml -f compose.edge.yaml "$@"; }
# SWARM_TOKEN_ID и SWARM_CONSUMER — проверенная выше строка, не значения секретов.
dc exec -T db psql -U dodo_audit -d dodo_audit_service \
  -v ON_ERROR_STOP=1 -v token_id="$SWARM_TOKEN_ID" -v consumer="$SWARM_CONSUMER" <<'SQL'
begin;
select id, consumer, scopes from api.tokens
where id = :'token_id'::bigint and consumer = :'consumer' and revoked_at is null
  and (expires_at is null or expires_at > now()) for update;
update api.tokens set scopes = array_append(scopes, 'performance:read')
where id = :'token_id'::bigint and consumer = :'consumer' and revoked_at is null
  and (expires_at is null or expires_at > now())
  and not ('performance:read' = any(scopes));
select id, consumer, scopes from api.tokens
where id = :'token_id'::bigint and consumer = :'consumer';
commit;
SQL
```

Проверка выбора ровно одной действующей строки и успешного добавления права —
обязательная часть оркестратора. Остальные права и ограничения стран сохраняются.
Секреты Swarm менять не требуется; новый `web` читает права из базы на запросе.

### Первичный сбор без ожидания часовой очереди

На том же VPS запускать пачками не более трёх стран. Первые пачки —
`RS,BG,HR`, затем `SI,AM,AZ`; остальные подключённые страны — после них.
Один процесс использует общий бюджет 180 HTTP-запросов, штатную задержку и
обработку 429; замок общий с часовым заданием. Код не продлевает OAuth-входы.

```bash
dc exec -T -e PERFORMANCE_COUNTRIES=RS,BG,HR bot python - <<'PY'
import json
import os
from src.db import dodois_logins, performance as store
from src.db.job_lock import DODOIS_METRICS_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.dodois.performance import Budget, collect_country
from src.domain.performance import comparison_windows, country_timezone, last_complete_day

countries = tuple(dict.fromkeys(os.environ['PERFORMANCE_COUNTRIES'].split(',')))
if not 1 <= len(countries) <= 3:
    raise SystemExit('expected one to three countries')
ready = True
with acting_space(SYSTEM_SPACE), job_lock(DODOIS_METRICS_LOCK_KEY, what='performance bootstrap') as got:
    if not got:
        raise SystemExit(75)  # другой сборщик работает; повторить позже
    budget = Budget(180)
    for cc in countries:
        login = dodois_logins.get_login(cc)
        if login is None or budget.remaining <= 0:
            ready = False
            print(json.dumps({'cc': cc, 'ready': False, 'reason': 'login_or_budget'}))
            continue
        outcomes = collect_country(login, budget=budget)
        zone, _ = country_timezone(cc)
        period = comparison_windows(last_complete_day([zone]))['current']
        rows = store.read_observations([cc], period.start, period.end)
        available = {r.metric for r in rows if r.subject_id == cc and r.period == period
                     and r.metric in {'revenue', 'orders'} and r.amount is not None}
        country_ready = available == {'revenue', 'orders'}
        ready = ready and country_ready
        print(json.dumps({'cc': cc, 'as_of': period.end.isoformat(), 'ready': country_ready,
                          'requests_remaining': budget.remaining,
                          'errors': sorted({r.error for r in outcomes if r.error})}))
if not ready:
    raise SystemExit(1)
PY
```

После первых четырёх стран оставшиеся пачки: `BY,CY,EE`, `ES,GE,ID`,
`KG,LT,ME`, `MN,NG,PL`, `RO,TJ,TR`. Пачка, не прошедшая проверку данных,
не считается готовой; учитывать часовой интервал повтора из `performance_loads`.
Итоги historical source могут быть неполными: их показывают с исходным статусом,
не заменяют нулём. Полные месяцы догружает тот же сборщик в следующих заходах.

### Минимальная проверка перед включением Swarm

1. В `schema_migrations` есть `0135_performance.sql`; `web` и `bot` работают
   с опубликованной версией, штатный смоук выкатки прошёл.
2. Фактический runtime-ключ Swarm получает HTTP 200 с `Content-Type: application/json`
   и объектом `countries`/`metrics`/`periods` на
   `/api/v1/performance?countries=RS,BG,HR,SI`; для каждой страны текущие
   `revenue`/`orders` имеют значение, корректную валюту и свежий `loaded_at`.
   MoM/YoY используют даты ответа; отсутствующая база остаётся явной.
3. Тот же ключ по-прежнему получает HTTP 200 на прежнем разрешённом методе
   `/api/v1/ratings/scores?type=rs`. Значение ключа не выводится.
4. После этого включить Swarm и проверить опубликованный cockpit: выбранная
   страна/метрика читают эти данные, а недоступные значения остаются явными.

Внешний HTTP-смоук должен использовать поддерживаемый User-Agent: отказ
Cloudflare 1010 с `text/plain` отсекает запрос до приложения и не доказывает
ошибку scope сервисного ключа. Проверять HTTP-статус и тело ответа раздельно.

### Дневной график

Текущий контракт предоставляет три точных периодных значения. Их можно
показать столбцами с датами current/MoM/YoY. Неподтверждённая непрерывная
дневная линия из них не строится. У finances есть настоящий `/daily` с
окном до десяти включённых дней; для полного месяца потребуется до четырёх
запросов на country. У остальных текущих метрик нет эквивалентной нативной
дневной серии в проверенном контракте. Добавление дневного кеша и API серии
не является условием включения проверенных периодных показателей.

## Дневные графики главной

Ответ страны содержит `daily.current`, `daily.mom`, `daily.yoy`: календарные
точки `{date, metrics}` с теми же значениями и признаками полноты, что у итогов.
Пропущенный день остаётся `unavailable`, не превращается в ноль и не вычисляется
из месячной суммы. Выручка и заказы читаются из настоящего
`finances/sales/country/daily` порциями до десяти дней; последняя одиночная дата
запрашивается с перекрытием предыдущего дня и устраняется по дате.
Другие метрики читаются по отдельным дням с прежними весами средних и правилами
границ. Страновые дневные финансы не зависят от полноты списка пиццерий.

Хранилище — существующие `performance_windows` с одинаковыми началом и концом
дня; миграций нет. Сбор входит в прежний общий бюджет180 запросов и замок
сборщика. Дневные финансы приоритетны, остальные дни подхватываются ограниченно
с ротацией по последней попытке. Ошибка запроса не стирает прежние значения.
