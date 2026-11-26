# Dodo IS: операционные метрики, LFL и исторические сравнения

Проверено 24.11.2026 по публичной официальной документации. Выручка, число заказов,
доставка, приготовление в ресторане, стопы и сертификаты за опоздание имеют API.
Готовый native LFL существует для **выручки и количества заказов**, по заведениям и
странам; для его первого получения не требуется год локального накопления.
Для времени, стопов и сертификатов native LFL в проверенном контракте отсутствует.

## Статус доказательств

- **Подтверждено документацией:** HTTP 200 публичного Stoplight, опубликованные
  параметры, поля, ограничения и исключения; 16 операций сохранены в
  [машинном снимке](2026-11-24-operating-metrics-api.json). В снимке раскрыты
  `$ref`; сохранены `source_url`, query schemas, response schemas и security.
- **Вывод / проектное правило:** рекомендуемая агрегация и защита от несовпадения
  выборок ниже. Это не дополнительная гарантия поставщика.
- **Не проверено live:** ответы бизнес-API, права конкретных стран, заполненность
  истории, фактическая семантика неполных LFL-периодов и границ, отсутствие дублей
  на границах. Токены, входы, production и учётные записи не использовались.

Первичный источник — [workspace Stoplight](https://stoplight.io/api/v1/workspaces/d2s6NzUzMjk/projects),
данные которого использует [docs.dodois.io](https://docs.dodois.io/).
Проекты: `dodo-is` (`cHJqOjExMTA4MQ`), `ratings` (`cHJqOjI4OTk1Mg`).
Английский проект (`cHJqOjMwMzkzMA`) также публикует обе операции LFL.
Локальный MAXIMUS-каталог использован как указатель, а все приведённые операционные
контракты повторно получены из Stoplight. MAXIMUS не изменялся.

## Матрица для сводки

| Значение | Источник | Native LFL | YoY и история | Агрегация |
|---|---|---|---|---|
| Выручка без VAT | `finances/sales/units` либо `/daily`, `/monthly` | `customer-feedback/lfl/by-units`, `/by-countries`: `lflRevenue` | Два исторических запроса; глубина хранения не объявлена | Сумма `sales` в одной валюте; нельзя складывать страны с разной валютой |
| Заказы | Те же finances: `ordersCount` | Те же LFL: `lflOrder` | Два исторических запроса; год локального накопления не обязателен | Сумма count по непересекающимся юнитам/периодам |
| Доставка от оформления до клиента | `delivery/statistics`: `avgDeliveryOrderFulfillmentTime` | Нет в опубликованной LFL-схеме | Исторический запрос ≤31 дня; retention не объявлен | `Σ(avg × deliveryOrdersCount) / Σ(deliveryOrdersCount)` по одному контракту; округление/выборка ограничивают точность |
| Приготовление в ресторане | `production/orders-handover-statistics`, `salesChannels=DineIn`: `avgCookingTime` | Нет | Исторический запрос ≤31 дня; retention не объявлен | `Σ(avgCookingTime × ordersCount) / Σ(ordersCount)` из того же ответа |
| Стопы каналов | `production/stop-sales-channels` | Нет | ≤31 дня; retention не объявлен | События и длительность раздельно; интервалы одного канала объединять |
| Стопы секторов доставки | `delivery/stop-sales-sectors` | Нет | ≤31 дня; документация указывает 01.04.2023, но содержит опечатку в имени граничного параметра | Интервалы по сектору; не суммировать с каналами как один общий простой |
| Стопы продуктов / ингредиентов | `production/stop-sales-products`, `-ingredients` | Нет | ≤31 дня; retention не объявлен | Счёт и длительность по соответствующему объекту; не потерянные продажи |
| Сертификаты за опоздание | `delivery/vouchers`: `vouchers[]` | Нет | Исторические from/to; предел окна и retention не объявлены | Число записей после полной пагинации; не равно автоматически `lateOrdersCount` |

Во всех строках «нет native LFL» означает отсутствие соответствующего поля/операции
в проверенных опубликованных схемах, а не доказательство отсутствия внутренних
отчётов Dodo IS. YoY для таких строк можно вычислять по историческим raw-метрикам;
это собственное сравнение, не native LFL поставщика.

## Базы адресов и доступ

Для finances, delivery и production база —
`https://api.dodois.{io|com}/dodopizza/{countryLower}`.
Контур берётся из действующего входа страны Decimus, а не определяется заново по
догадке. Операции перечисляют `.io` для RU/KZ/BY/KG/TJ/UZ и `.com` для прочих
стран; локальное подключение и его контур описаны в [24-dodois.md](../24-dodois.md).

Для LFL база другая: `https://api.dodois.{io|com}/customer-feedback`;
пути `/dodopizza/{country}/lfl/...` в проверенных операциях нет.
[Service schema](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/zdqsi3sfgeo0b-customer-rating-api)
публикует OAuth2 authorizationCode/clientCredentials со scope `shared`, но в самих
LFL-операциях `security: []`, при этом описан ответ 401. Поэтому отсутствие security
в операции не подтверждает публичный доступ без токена; пригодность существующего
входа со scope `shared` требует реального ответа.

В finances указан scope `shared`; доставка/сертификаты — `deliverystatistics` и
`user.role:read`; приготовление — `productionefficiency` и `user.role:read`;
стопы — `stopsales` и `user.role:read`. Это описание схем security, не результат
проверки scopes конкретного входа. Роли, когда они явно ограничены, указаны в
операционном приложении. Отсутствие отдельного описания ролей не даёт права
расширять существующие доступы.

## Native LFL: что известно точно

[По заведениям](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7a9cf987af1d6-lfl-lfl-po-zavedeniyam):
обязательные `from`, `to` — даты `YYYY-MM-DD`; `units` — ≤30 UUID через запятую без
пробелов (schema minLength 32, maxLength 990). Необязательная `granularity` —
`Day | Week | Month`, default `Day`. Ответ: `lfl[]` с обязательными
`unitId`, `countryId`, `date`, `lflRevenue`, `lflOrder`.

[По странам](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7f63c84f4d4ec-lfl-lfl-po-stranam):
те же `from`, `to`, `granularity`; вместо units обязательный `countries` — ≤10
ISO 3166-1 alpha-2 кодов через запятую без пробелов (schema minLength 2,
maxLength 300). Ответ — те же поля без `unitId`.

- `lflRevenue`, `lflOrder` — number/decimal. Примеры `0.05`, `0.02` согласуются
  с долями роста 5%/2%; **это вывод по примерам**, явного определения единицы и
  формулы нет. До live-подтверждения сохранять raw, не делать неявное двойное ×100.
- [Модель строки unit](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/e520f2174b1d4-lfl-by-units-item)
  и [страны](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/f49f5f5a64a7c-lfl-by-countries-item)
  описывают `date` как первый день недели/месяца для Week/Month и «период целиком»
  для Day. Последнее не согласовано с query-описанием «дни, недели, месяцы».
- **Не установлены:** способ выбора когорты, возраст точек, сравнение календарных
  дат или дней недели, смещение 364/365/366 дней, VAT-база, включение границ,
  результат для нового юнита/нулевой базы, окно, глубина истории, частичный месяц.
  Не утверждать, что Month всегда полный месяц или что он гарантированно MTD.
- **Правило интеграции:** запрашивать нужный период напрямую и сохранять
  `requested_from`, `requested_to`, `granularity`, response `date` и источник.
  До подтверждения соответствия returned bucket конкретному MTD не подписывать
  его как точный MTD. Native LFL доступен уже сейчас; эта неопределённость решается
  проверкой ответа, а не ожиданием года собственных данных.
- Нельзя усреднять LFL-проценты дней или точек для MTD/страны. Для суммы темп
  считается через суммы сопоставимых текущих и базовых величин либо с весами
  базовых величин: `Σ(current)/Σ(base) - 1`. Native-ответ не содержит эти базы и
  когорту. Для страны предпочтителен прямой `/by-countries`; он не доказывает
  соответствие произвольной выбранной подгруппе юнитов.

## Выручка, заказы и окна

`finances/sales/units` отдаёт итог за период, country — итог по стране;
`/daily` и `/monthly` — строки дней/месяцев. Все суммы `sales` без VAT, валюты в
ответе нет. Валюта — из справочника страны; ошибку валюты не подменять EUR.
`ordersCount` в finances — заказы продаж; не заменять его production-count или
filtered delivery-count, у которых другая выборка.

| Вариант | Вход | Максимальное окно | Границы |
|---|---|---|---|
| `/units`, `/country` | from/to datetime `YYYY-MM-DDTHH:mm:ss`; units дополнительно для /units | 62 дня | `[from,to)`; from < to |
| `/units/daily`, `/country/daily` | fromDate/toDate date; units для /units | 10 дней | Обе включены; fromDate < toDate |
| `/units/monthly`, `/country/monthly` | fromDate/toDate date; units для /units | 62 дня | Обе включены; fromDate < toDate |

units — 1..30 UUID CSV без пробелов. Для точного одного дня/MTD удобен периодный
endpoint с исключающим концом. В daily/monthly задокументированное строгое `<`
не позволяет уверенно заявить работоспособность fromDate=toDate.
В period `/units` текст ошибочно упоминает fromDate/toDate и месячную агрегацию,
но query-схема содержит from/to, response — unitId и итоги без month.
Часовая зона from/to прямо не названа; строковый pattern не содержит offset/Z.
Прибивать UTC или добавлять Z без проверки неправильно.

В описании допускаются Delivery/Dine-in/Takeaway, источники CallCenter/Website/
Dine-in/MobileApp/Manager/Aggregator/Kiosk/ChatBot, платежи Online/Cash/Card/
Aggregator; заменяющие бракованные заказы исключены. В enum schema есть дополнительные
DefectOrder, Staff meal, Tracker, а у paymentMethod enum отсутствует Aggregator:
это расхождение документации; parser должен переносить неизвестную строку,
не обнулять всю выгрузку. Детализация содержит только ненулевые комбинации.
Нельзя складывать итог `sales` и его же `salesBreakdown` как независимые суммы.

Ограничение в 10/31/62 дня — размер одного запроса, **не глубина истории**.
Исторический период год назад можно запросить сейчас, разбив по окнам. Самый ранний
доступный период и полнота по каждой стране не установлены; не объявлять прошлый
год недоступным только потому, что Decimus ещё не собирал эти значения.

## Средние времени

Доставка: `avgDeliveryOrderFulfillmentTime` — от оформления заказа до вручения
клиенту, секунды. `avgOrderTripTime` — только путь курьера, отдельное значение.
Из delivery-statistics исключены короткие поездки и быстрое приготовление;
численные пороги этого исключения не опубликованы. `avgCookingTime` здесь относится
к доставке, не ко всему ресторану.

Ресторан: `production/orders-handover-statistics` с **salesChannels=DineIn**
(query spelling именно DineIn). Ответный `avgCookingTime` — приготовление,
`avgOrderHandoverTime` — время до выдачи, `avgOrderAssemblyTime` — ожидание сборки
заказа приложения и заполняется только при отчёте исключительно DineIn.
Заказы без выпекаемых продуктов и с приготовлением выпекаемых продуктов <1 минуты,
напитки/неприготовляемые продукты исключены. Вес `ordersCount` уже учитывает эти
исключения. Время округлено до целых секунд (≥0.5 вверх).

**Правило агрегации:** сохранять numerator `avg_seconds × count` и denominator
`count`, суммировать их, делить один раз. Для production count из той же строки,
для delivery — deliveryOrdersCount из той же строки. Не усреднять средние юнитов
или дней без весов и не брать общий finances-count. Поставщик не публикует сырые
суммы/внутренний denominator для каждой delivery-метрики; восстановленный numerator
приближён из округлённых средних, точное совпадение со внутренним отчётом не доказано.
Пустое/нечисловое среднее не превращать в 0, его вес исключать именно для этого
показателя. Нулевой denominator — нет значения. Для среднего ресторана данные
salesChannels смешанного запроса не позволяют восстановить отдельный DineIn.

Детальный `/production/orders-handover-time` допускает разбор каждой строки,
но query не содержит salesChannels; фильтровать ответный `salesChannel=Dine-in`.
Здесь spelling канала отличается от query агрегированного endpoint.
`orderTrackingStartAt` прямо описан как **локальное время вместо UTC**.
Для delivery/production кроме явно указанных секторных стопов timezone запросов
и включение правой границы не определены. На стыке окон нельзя предполагать
взаимоисключение без проверки.

## Стопы и сертификаты: что именно считается

Стопы — события остановки продаж, не денежные потери. Каналы: Dine-in, Takeaway,
Delivery; `channelStopType`: Complete или Redirection (перенаправление нельзя
безусловно считать полной недоступностью). Продукты/ингредиенты/сектора — отдельные
измерения остановок; один сбой способен породить несколько строк в нескольких API.

**Проектное правило длительности:** dedup по типу endpoint + unitId + id;
пересечь `[startedAt,endedAt)` с отчётным периодом, открытый конец ограничить
min(конец периода, момент наблюдения). Перед суммированием общего простоя объединять
перекрывающиеся интервалы одинаковой области. Сумма продуктовых минут —
«продукт-минуты», не минуты недоступности заведения. Отношение ко времени работы
требует расписания и определения области; в этих ответах знаменателя нет.

В каналах/продуктах/ингредиентах startedAt/endedAt документированы как локальное
время вместо UTC; предпочтительны явные *AtLocal + часовая зона пиццерии.
В секторах *At — UTC, *AtLocal — время пиццерии. Для секторов отдельно указана дата
01.04.2023, но фраза называет начальную дату `to`; это опечатка/неясность, а не
доказанная точная проверка параметра сервером. Не установлено, вернётся ли стоп,
начавшийся до запрошенного from и продолжающийся внутри окна: без этого полнота
общей длительности на границе не гарантирована.

Сертификаты `/delivery/vouchers` — **за опоздание**, не обучение и не подарочные
сертификаты произвольного назначения. Поля содержат заказ, время обещания/крайний
срок, отметку вручения, источник выдачи `System | Contact Center`. Полей номинала,
стоимости, погашения, уникального voucherId, issuedAt в схеме нет.
Поэтому нельзя из ответа вычислять денежный ущерб или число погашений.
Отбирать страницы skip/take до isEndOfListReached=true; take ≤1000.
Число vouchers не доказано равным числу lateOrdersCount: опоздание и выдача
сертификата — разные признаки, а delivery-statistics дополнительно фильтрует заказы.
Для процента сертификатов нужен отдельно подтверждённый знаменатель всех доставок
того же периода/выборки. Сейчас это не native показатель API.

## Сопоставимые периоды и незаполненные данные

Для обычного YoY выручки/заказов допустима формула `current/base - 1`, если база
положительна, периоды одной длины/согласованного календарного правила и источник
одинаков. Для времени полезна разность секунд; относительный YoY допустим с
ненулевой базой. Это вычисляемые показатели, не native LFL. Календарное год-к-году
и сопоставление по дням недели — разные методики; выбор нельзя маскировать.

Текущий MTD не сравнивать с полным прошлым месяцем или полным прошлогодним месяцем.
Передавать requested period, covered period, источник, момент сбора, состояние
полноты/ошибки. Не пришла строка, 401/403, ограниченное окно, нет базы и настоящий 0 —
разные состояния. Пустой ответ/нет истории не доказывает нулевую выручку/стопы.
Показатель со сломанной базой остаётся доступным за текущий период, сравнение —
«нет данных», без искусственного процента.

## Полные параметры и поля проверенных операций

Ниже типы/nullable/enum и роли перенесены из свежего опубликованного контракта.
Численные ограничения query дополняют текст описания. Вложенные ответные поля
даны полностью; `$ref` раскрыты в JSON-снимке. Идентификаторы сотрудников приведены
как названия полей схемы; персональные значения не собирались.

### `GET /delivery/statistics`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/6149483e4dfb1-dostavka-statistika).

Scope схемы: `deliverystatistics`, `user.role:read`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time.

Ответ 200:
- `unitsStatistics` — array; Основные метрики доставки.
- `unitsStatistics[].unitId` — string; Идентификатор пиццерии.
- `unitsStatistics[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `unitsStatistics[].deliverySales` — number; Выручка с доставки.
- `unitsStatistics[].deliveryOrdersCount` — integer; Количество заказов на доставку.
- `unitsStatistics[].avgDeliveryOrderFulfillmentTime` — integer; Среднее время доставки (от оформления заказа до вручения клиенту) в секундах.
- `unitsStatistics[].avgCookingTime` — integer; Среднее время приготовления в секундах.
- `unitsStatistics[].avgHeatedShelfTime` — integer; Среднее время ожидания на тепловой полке в секундах.
- `unitsStatistics[].avgOrderTripTime` — integer; Среднее время курьера с заказом в пути в секундах.
- `unitsStatistics[].lateOrdersCount` — integer; Количество опоздавших заказов.
- `unitsStatistics[].tripsCount` — integer; Количество поездок курьеров.
- `unitsStatistics[].tripsDuration` — integer; Сумма времени всех поездок курьеров в секундах.
- `unitsStatistics[].couriersShiftsDuration` — integer; Сумма продолжительности смены всех курьеров в секундах.
- `unitsStatistics[].ordersWithCourierAppCount` — integer; Количество доставок с курьерским приложением.

### `GET /delivery/vouchers`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/f3c261f246fc0-dostavka-sertifikaty-za-opozdanie).

Scope схемы: `deliverystatistics`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `skip` — необязательный; Количество записей, которые следует пропустить; type=integer; default=0; minimum=0.
- `take` — необязательный; Количество записей, которые следует выбрать; type=integer; default=100; minimum=0; maximum=1000.

Ответ 200:
- `vouchers` — array; Сертификаты за опоздание.
- `vouchers[].orderId` — string; Id заказа.
- `vouchers[].orderNumber` — string; Номер заказа.
- `vouchers[].orderAcceptedAtLocal` — string; Дата и время приёма заказа (локальное время).
- `vouchers[].unitId` — string; Id юнита (заведения).
- `vouchers[].predictedDeliveryTimeLocal` — string; Предполагаемое время доставки (локальное время).
- `vouchers[].orderFulfilmentFlagAtLocal` — string / null; Время отметки курьером в приложении успешной доставки (время локальное).
- `vouchers[].deliveryDeadlineLocal` — string; Крайний срок доставки (локальное время).
- `vouchers[].issuerName` — string / null; Кем выдан сертификат; enum: System, Contact Center.
- `vouchers[].courierStaffId` — string / null; Id сотрудника-курьера.
- `isEndOfListReached` — boolean; Индикатор того, что достигнут конец списка. Выдаёт true, если достигнут конец списка.

### `GET /delivery/stop-sales-sectors`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/3e817cbe2a17a-dostavka-stop-prodazhi-po-sektoram).

Scope схемы: `stopsales`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`, `Shift supervisor`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601. Время указывается в UTC.; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601. Время указывается в UTC.; type=string; format=date-time.

Ответ 200:
- `stopSalesBySectors` — array; Данные о стопах продаж сгруппированные по заведениям и секторам.
- `stopSalesBySectors[].id` — string; Id стопа.
- `stopSalesBySectors[].unitId` — string; Идентификатор пиццерии.
- `stopSalesBySectors[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `stopSalesBySectors[].sectorName` — string; Сектор поставленный в стоп продажи.
- `stopSalesBySectors[].isSubSector` — boolean; Является ли сектор под-сектором, созданным из менеджера смены.
- `stopSalesBySectors[].startedAt` — string; Время начала стопа в UTC в формате ISO 8601.
- `stopSalesBySectors[].startedAtLocal` — string; Время начала стопа в часовой зоне пиццерии в формате ISO 8601.
- `stopSalesBySectors[].endedAt` — string / null; Время возобновления продаж в UTC в формате ISO 8601 (null - если еще не возобновлено).
- `stopSalesBySectors[].endedAtLocal` — string / null; Время возобновления продаж в часовой зоне пиццерии в формате ISO 8601 (null - если еще не возобновлено).
- `stopSalesBySectors[].suspendedByUserId` — string / null; Id пользователя, который инициировал стоп продаж (null - если данные о пользователе отсутствуют).
- `stopSalesBySectors[].resumedUserId` — string / null; Id пользователя, который возобновил продажи (null - если еще не возобновлено).

### `GET /production/orders-handover-time`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/c48a37d12f9e9-proizvodstvo-vremya-vydachi-zakaza).

Scope схемы: `productionefficiency`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time.

Ответ 200:
- `ordersHandoverTime` — array; Время выдачи заказа.
- `ordersHandoverTime[].unitId` — string; Идентификатор пиццерии.
- `ordersHandoverTime[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `ordersHandoverTime[].orderId` — string; Идентификатор заказа.
- `ordersHandoverTime[].orderNumber` — string; Номер заказа.
- `ordersHandoverTime[].salesChannel` — string; Канал продажи; enum: Dine-in, Takeaway, Delivery.
- `ordersHandoverTime[].orderTrackingStartAtLocal` — string; Время заказа в формате ISO 8601 (локальное время).
- `ordersHandoverTime[].trackingPendingTime` — integer; Время ожидания на трекинге в секундах с округлением.
- `ordersHandoverTime[].cookingTime` — integer; Время приготовления заказа в секундах с округлением.
- `ordersHandoverTime[].heatedShelfTime` — integer; Время ожидания заказа на тепловой полке в секундах с округлением.
- `ordersHandoverTime[].assemblyTime` — integer / null; Время ожидания сборки заказа из приложения в ресторане в секундах с округлением. Заполняется только для заказов типа `Dine-in`, в других случаях - null.
- `ordersHandoverTime[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, DefectiveProduct, MobileApp, Manager, Aggregator, Kiosk.
- `ordersHandoverTime[].orderTrackingStartAt` — string; Возвращает локальное время вместо UTC.

### `GET /production/orders-handover-statistics`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/e82c12e60120b-proizvodstvo-statistika-vydachi-zakazov).

Scope схемы: `productionefficiency`, `user.role:read`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `salesChannels` — необязательный; Фильтр по типу заказа Доставка/Ресторан/Самовывоз; type=string.

Ответ 200:
- `ordersHandoverStatistics` — array; Статистика выдачи заказов.
- `ordersHandoverStatistics[].unitId` — string; Идентификатор пиццерии.
- `ordersHandoverStatistics[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `ordersHandoverStatistics[].avgTrackingPendingTime` — integer; Средняя время ожидания на трекинге в секундах с округлением.
- `ordersHandoverStatistics[].avgCookingTime` — integer; Среднее время приготовления заказа в секундах с округлением.
- `ordersHandoverStatistics[].avgHeatedShelfTime` — integer; Среднее время ожидания заказа на тепловой полке в секундах с округлением.
- `ordersHandoverStatistics[].avgOrderAssemblyTime` — integer / null; Среднее время ожидания сборки заказа из приложения в ресторане в секундах с округлением. Заполняется если отчёт строится только для заказов типа `DineIn`, иначе - null.
- `ordersHandoverStatistics[].avgOrderHandoverTime` — integer; Среднее время до выдачи заказа в секундах с округлением.
- `ordersHandoverStatistics[].ordersCount` — integer; Количество заказов за запрашиваемый период с учётом исключений: в расчет не попадают заказы с временем приготовления выпекаемых продуктов меньше 1 минуты и заказы без выпекаемых продуктов (кусочки, напитки, фонданы и т.д.)..

### `GET /production/stop-sales-channels`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/6bcaeb26e9f28-proizvodstvo-stop-prodazhi-po-kanalam-prodazh).

Scope схемы: `stopsales`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`, `Shift supervisor`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time.

Ответ 200:
- `stopSalesBySalesChannels` — array; Данные о стопах продаж сгруппированные по заведениям и каналам продаж.
- `stopSalesBySalesChannels[].id` — string; Id стопа.
- `stopSalesBySalesChannels[].unitId` — string; Идентификатор пиццерии.
- `stopSalesBySalesChannels[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `stopSalesBySalesChannels[].salesChannelName` — string; Канал продажи поставленный в стоп; enum: Dine-in, Takeaway, Delivery.
- `stopSalesBySalesChannels[].reason` — string; Причина постановки в стоп.
- `stopSalesBySalesChannels[].startedAtLocal` — string; Время начала стопа в формате ISO 8601 (локальное время).
- `stopSalesBySalesChannels[].endedAtLocal` — string / null; Время возобновления продаж в формате ISO 8601 (локальное время) (null - если еще не возобновлено).
- `stopSalesBySalesChannels[].stoppedByUserId` — string; Id сотрудника, который инициировал стоп продаж.
- `stopSalesBySalesChannels[].resumedByUserId` — string / null; Id сотрудника, который возобновил продажи (null - если еще не возобновлено).
- `stopSalesBySalesChannels[].channelStopType` — string; Как были приостановлены продажи; enum: Complete, Redirection.
- `stopSalesBySalesChannels[].startedAt` — string; Возвращает локальное время вместо UTC.
- `stopSalesBySalesChannels[].endedAt` — string / null; Возвращает локальное время вместо UTC (null - если еще не возобновлено).

### `GET /production/stop-sales-ingredients`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/846af18915ab3-proizvodstvo-stop-prodazhi-po-ingredientam).

Scope схемы: `stopsales`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`, `Shift supervisor`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time.

Ответ 200:
- `stopSalesByIngredients` — array; Данные о стопах продаж сгруппированные по заведениям и ингредиентам.
- `stopSalesByIngredients[].id` — string; Id стопа.
- `stopSalesByIngredients[].unitId` — string; Идентификатор пиццерии.
- `stopSalesByIngredients[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `stopSalesByIngredients[].ingredientId` — string; Идентификатор ингредиента поставленного в стоп продажи.
- `stopSalesByIngredients[].ingredientName` — string; наименование ингредиента поставленного в стоп продажи.
- `stopSalesByIngredients[].ingredientCategoryName` — string; Категория ингредиента поставленного в стоп продажи; enum: Ingredient, SemiFinishedProduct, FinishedProduct, Inventory, Packing, Consumables.
- `stopSalesByIngredients[].reason` — string; Причина постановки в стоп.
- `stopSalesByIngredients[].startedAtLocal` — string; Время начала стопа в формате ISO 8601 (локальное время).
- `stopSalesByIngredients[].endedAtLocal` — string / null; Время возобновления продаж в формате ISO 8601 (локальное время) (null - если еще не возобновлено).
- `stopSalesByIngredients[].stoppeddByUserId` — string; Id пользователя, который инициировал стоп продаж.
- `stopSalesByIngredients[].resumedByUserId` — string / null; Id пользователя, который возобновил продажи (null - если еще не возобновлено).
- `stopSalesByIngredients[].startedAt` — string; Возвращает локальное время вместо UTC.
- `stopSalesByIngredients[].endedAt` — string / null; Возвращает локальное время вместо UTC (null - если еще не возобновлено).

### `GET /production/stop-sales-products`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/f90f05153cfac-proizvodstvo-stop-prodazhi-po-produktam).

Scope схемы: `stopsales`, `user.role:read`.

Роли, явно названные в описании: `Division administrator`, `Store Manager`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time.

Ответ 200:
- `stopSalesByProduct` — array; Данные о стопах продаж сгруппированные по заведениям и продуктам.
- `stopSalesByProduct[].id` — string; Id стопа.
- `stopSalesByProduct[].unitId` — string; Идентификатор пиццерии.
- `stopSalesByProduct[].unitName` — string; Название пиццерии в форматах Сыктывкар-1 или Москва 0-1.
- `stopSalesByProduct[].productId` — string; Идентификатор продукта.
- `stopSalesByProduct[].productName` — string; Наименование продукта поставленного в стоп продажи.
- `stopSalesByProduct[].productCategoryName` — string; Категория продукта поставленного в стоп продажи; enum: Pizza, Drinks, Snacks, Sauces, Goods, Desserts, Pieces.
- `stopSalesByProduct[].reason` — string; Причина постановки в стоп.
- `stopSalesByProduct[].startedAtLocal` — string; Время начала стопа в формате ISO 8601 (локальное время).
- `stopSalesByProduct[].endedAtLocal` — string / null; Время возобновления продаж в формате ISO 8601 (локальное время) (null - если еще не возобновлено).
- `stopSalesByProduct[].stoppedByUserId` — string; Id пользователя, который инициировал стоп продаж.
- `stopSalesByProduct[].resumedByUserId` — string / null; Id пользователя, который возобновил продажи (null - если еще не возобновлено).
- `stopSalesByProduct[].startedAt` — string; Возвращает локальное время вместо UTC.
- `stopSalesByProduct[].endedAt` — string / null; Возвращает локальное время вместо UTC (null - если еще не возобновлено).

### `GET /finances/sales/country/daily`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/42e6d9ec7923b-finansy-dnevnye-prodazhi-po-strane).

Scope схемы: `shared`.

Параметры:
- `fromDate` — обязательный; Дата начала периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.
- `toDate` — обязательный; Дата конца периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах по дням.
- `result[].date` — string; Дата в формате ISO 8601.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /finances/sales/units/daily`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/442ee262c9bab-finansy-dnevnye-prodazhi-po-zavedeniyam).

Scope схемы: `shared`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `fromDate` — обязательный; Дата начала периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.
- `toDate` — обязательный; Дата конца периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах по дням и заведениям.
- `result[].date` — string; Дата в формате ISO 8601.
- `result[].unitId` — string; Идентификатор заведения.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /finances/sales/country/monthly`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/774e372ed5435-finansy-mesyachnye-prodazhi-po-strane).

Scope схемы: `shared`.

Параметры:
- `fromDate` — обязательный; Дата начала периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.
- `toDate` — обязательный; Дата конца периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах по месяцам.
- `result[].year` — integer; Год.
- `result[].month` — integer; Месяц.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /finances/sales/units/monthly`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/7b9d046c52353-finansy-mesyachnye-prodazhi-po-zavedeniyam).

Scope схемы: `shared`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `fromDate` — обязательный; Дата начала периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.
- `toDate` — обязательный; Дата конца периода в формате ISO 8601; type=string; format=date; pattern=^\d{4}-\d{2}-\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах по месяцам и заведениям.
- `result[].year` — integer; Год.
- `result[].month` — integer; Месяц.
- `result[].unitId` — string; Идентификатор заведения.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /finances/sales/country`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/837c8c5582f92-finansy-prodazhi-po-strane-za-period).

Scope схемы: `shared`.

Параметры:
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах за период.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /finances/sales/units`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjExMTA4MQ/nodes/4e7fb7a30a284-finansy-prodazhi-po-zavedeniyam-za-period).

Scope схемы: `shared`.

Параметры:
- `units` — обязательный; Список заведений (пиццерий) Dodo IS в формате UUID; type=string; minItems=1; maxItems=30; uniqueItems=True.
- `from` — обязательный; Начало периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.
- `to` — обязательный; Конец периода в формате ISO 8601; type=string; format=date-time; pattern=^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$.

Ответ 200:
- `result` — array; Данные о продажах по заведениям за период.
- `result[].unitId` — string; Идентификатор заведения.
- `result[].sales` — number; Объём продаж без учёта VAT.
- `result[].ordersCount` — integer; Количество заказов.
- `result[].salesBreakdown` — array; Продажи и количество заказов по каналам продаж, источникам заказа и типам платежей.
- `result[].salesBreakdown[].orderSource` — string; Источник заказа; enum: CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator, Kiosk, ChatBot, DefectOrder.
- `result[].salesBreakdown[].salesChannel` — string; Канал продаж заказа; enum: Dine-in, Takeaway, Delivery, Staff meal, Tracker.
- `result[].salesBreakdown[].paymentMethod` — string; Метод оплаты; enum: Cash, Card, Online.
- `result[].salesBreakdown[].sales` — number; Объём продаж без учёта VAT.
- `result[].salesBreakdown[].ordersCount` — integer; Количество заказов.

### `GET /lfl/by-units`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7a9cf987af1d6-lfl-lfl-po-zavedeniyam).

Scope схемы: не назначен в operation; см. service и замечание о LFL выше.

Параметры:
- `from` — обязательный; Начало периода (дата без времени); type=string; format=date.
- `to` — обязательный; Конец периода (дата без времени); type=string; format=date.
- `units` — обязательный; Список заведений Dodo IS в формате UUID, перечисленных через запятую; type=string; minLength=32; maxLength=990.
- `granularity` — необязательный; Грануляция данных по времени (дни, недели, месяцы); type=string; default=Day; enum=['Day', 'Week', 'Month'].

Ответ 200:
- `lfl` — array; .
- `lfl[].unitId` — string; Идентификатор заведения.
- `lfl[].countryId` — string; Код страны (ISO 3166-1 alpha-2).
- `lfl[].date` — string; Дата начала периода. Для granularity `Week` или `Month` - дата первого дня недели или месяца соответственно. Для granularity `Day` - период целиком.
- `lfl[].lflRevenue` — number; LFL по выручке.
- `lfl[].lflOrder` — number; LFL по количеству заказов.

### `GET /lfl/by-countries`

[Первичная операция](https://stoplight.io/api/v1/projects/cHJqOjI4OTk1Mg/nodes/7f63c84f4d4ec-lfl-lfl-po-stranam).

Scope схемы: не назначен в operation; см. service и замечание о LFL выше.

Параметры:
- `from` — обязательный; Начало периода (дата без времени); type=string; format=date.
- `to` — обязательный; Конец периода (дата без времени); type=string; format=date.
- `countries` — обязательный; Список кодов стран (ISO 3166-1 alpha-2), перечисленных через запятую; type=string; minLength=2; maxLength=300.
- `granularity` — необязательный; Грануляция данных по времени (дни, недели, месяцы); type=string; default=Day; enum=['Day', 'Week', 'Month'].

Ответ 200:
- `lfl` — array; .
- `lfl[].countryId` — string; Код страны (ISO 3166-1 alpha-2).
- `lfl[].date` — string; Дата начала периода. Для granularity `Week` или `Month` - дата первого дня недели или месяца соответственно. Для granularity `Day` - период целиком.
- `lfl[].lflRevenue` — number; LFL по выручке.
- `lfl[].lflOrder` — number; LFL по количеству заказов.
