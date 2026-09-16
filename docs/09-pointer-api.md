# Pointer API — внешний источник оценок и отзывов с карт

> Статус: разведка, ключа доступа нет. Документация вычитана 16.09.2026, факты ниже взяты
> из самой доки (Redoc-страница), а не по памяти.

**Документация:** https://api.pntr.io/ (там же кнопка «Download OpenAPI specification»).
**База:** `https://api.pntr.io/v1`.

## Зачем нам

Будущий блок аналитики по странам на платформе: внешняя оценка пиццерии глазами гостя
(рейтинг и отзывы на картах) рядом с внутренней оценкой аудита. Гипотеза связи —
пиццерия ↔ филиал (`company`) Поинтера.

## Что это за сервис

Собирает оценки, отзывы и комментарии с картографических сервисов по сети точек,
позволяет отвечать на отзывы и вести переписку. Иерархия: **сеть (network)** → **филиал
(company)** → **отзыв (review)**.

## Доступ

- Схема `bearerAuthToken`: HTTP `Authorization: Bearer <TOKEN>` в каждом запросе.
- Ключ выдаёт поддержка Поинтера по заявке с названиями сетей и списком методов,
  которые планируем использовать. Самообслуживания нет — ключ надо запрашивать.
- **Rate limit: не более 1 запроса в секунду.** Это проектное ограничение, а не деталь:
  аналитика на лету по такому лимиту не строится, нужен свой кэш/ETL.

## Эндпоинты (полный список путей со страницы документации)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/providers` | список геосервисов |
| GET | `/networks` | список сетей |
| GET | `/networks/{uuid}/ratings` | рейтинги сети в геосервисах |
| GET | `/networks/{uuid}/tags` | ручные теги отзывов сети |
| GET | `/networks/{uuid}/traffic/{provider_id}` | статистика трафика сети |
| GET | `/networks/{uuid}/competitors` | филиалы сети с конкурентами (платная опция «Карта конкурентов») |
| GET | `/companies` | список филиалов |
| GET | `/companies/{uuid}/ratings` | рейтинги филиала в геосервисах |
| GET | `/reviews` | список отзывов |
| POST/PATCH/DELETE | `/reviews/{id}/reply` | ответ на отзыв |
| PATCH | `/reviews/{id}/report` | пожаловаться на отзыв |
| GET/POST | `/reviews/{id}/comments` | комментарии к отзыву |
| GET | `/conversations`, `/conversations/{uuid}/messages` | чаты и сообщения |
| GET/POST/PUT/DELETE | `/webhooks`, `/webhooks/{uuid}` | вебхуки |
| GET | `/export/json/companies`, `/export/json/companies/ratings`, `/export/json/reviews` | экспорт |
| POST | `/feedback-activator/review-email-requests` | письмо с запросом отзыва |

Геосервисы из примера ответа `/providers`: `1` — Яндекс Карты, `2` — Google Карты, `3` — 2ГИС.

## Пагинация

Везде `limit` (по умолчанию 10, максимум 100) и `offset` (по умолчанию 0);
в ответе `meta: { total, limit, offset }`.

## Фильтры

`GET /companies`: `network_uuid`, `yandex_xml_ids`, `with_ratings`, `with_info`, `q`
(поиск по имени филиала), `limit`, `offset`.

`GET /reviews`: `network_uuids`, `company_uuids`, `provider_ids`, `has_reply`,
`is_reply_published`, `has_comment`, `rating` (список значений), `published_at_from/to`,
`created_at_from/to`, `reply_created_at_from/to`, `reply_published_at_from/to`,
`is_activator`, `is_changed`, `with_photos`, `with_tags`, `with_smart_tags`, `tag_ids`,
`smart_tag_ids`, `limit`, `offset`.

`GET /networks/{uuid}/competitors`: `locality_name` (фильтр по населённому пункту).

## Главное для аналитики по странам

**Фильтра по стране в API нет** — ни у филиалов, ни у отзывов. География есть только
как поля объекта филиала:

- `address_fields`: `country` (название строкой, напр. «Россия»), `area`, `city`,
  `street`, `building`, `postcode`, `address_notes[]`;
- `country_code` (напр. `RU`), `latitude`, `longitude`.

Отсюда порядок работы для странового среза: выгрузить филиалы (лучше через
`/export/json/companies`), сгруппировать у себя по `country_code`, и только потом тянуть
отзывы и рейтинги по `company_uuids`. То есть страновая агрегация — наша, а не их.
Для инкремента есть вебхуки, чтобы не опрашивать заново.

## Открытые вопросы (до запроса ключа)

1. Есть ли у Dodo подключение к Поинтеру и по каким странам заведены сети — у нас сеть
   международная, а провайдеры в доке российские (Яндекс, Google, 2ГИС).
2. Как связать филиал Поинтера с нашей пиццерией: у филиала есть `uuid` и
   `yandex_xml_id`, кода нашей юнит-сети в доке не видно.
3. Поля объекта отзыва целиком (в т. ч. язык отзыва) — в вычитанном фрагменте не
   подтверждены, проверять по OpenAPI-спеке после получения ключа.
