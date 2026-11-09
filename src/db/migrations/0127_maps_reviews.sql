-- 0127_maps_reviews.sql
--
-- Оценки на картах поштучно (D732, D733, #1562): карта в «Качестве» считается по оценкам,
-- поставленным за месяц, а не по общей оценке карточки на конец месяца. Pointer отдаёт
-- оценки списком `/reviews`; текст отзыва не храним — он для расчёта не нужен.
--
-- `maps.reviews` — одна оценка (id Pointer — ключ, повторная загрузка обновляет строку:
-- правка оценки, удаление). Месяц оценки — `published_at`, дата, когда её поставили.
-- `maps.reviews_sync` — что по паре (филиал, карта) уже загружено: с какой даты залита
-- история и когда в последний раз догружались два последних месяца. Дозагрузка идёт
-- порциями и переживает перезапуск бота: что легло, знает база, а не память процесса.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table maps.reviews (
    id text primary key,
    company_uuid uuid not null references maps.companies (uuid),
    provider_id integer not null,
    rating smallint not null check (rating between 1 and 5),
    published_at date not null,
    is_deleted boolean not null default false,
    updated_at timestamptz not null default now()
);
create index reviews_company_provider_month_idx
    on maps.reviews (company_uuid, provider_id, published_at);

create table maps.reviews_sync (
    company_uuid uuid not null references maps.companies (uuid),
    provider_id integer not null,
    backfilled_from date,
    topped_up_on date,
    primary key (company_uuid, provider_id)
);

grant select on maps.reviews, maps.reviews_sync to dodo_audit_app, dodo_audit_admin;
grant insert, update on maps.reviews, maps.reviews_sync to dodo_audit_app;
