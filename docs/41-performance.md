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
