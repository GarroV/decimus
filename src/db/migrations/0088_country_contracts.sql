-- 0088_country_contracts.sql
--
-- Блок «Договор» в карточке страны (шаг 2 спеки 2026-10-21-osb-prescriptions-design,
-- D603, D606): юрлицо партнёра, договор одной строкой и КОНТАКТЫ ПО ДКК — почты,
-- которые форма предписания подставляет в «Кому».
--
-- ДКК в системе НЕ моделируется (D603): название и дата договора — свободный текст
-- одной строкой, пунктов и сроков нет. На страну — список строк (партнёров в стране
-- бывает несколько), обычно одна.
--
-- ПОЧТЫ. Хранятся одной строкой «a@x.ge, b@y.ge» — как `prescriptions.recipients`
-- (0037): так они ложатся в заголовок `To:` письма. Поэтому проверка здесь строже,
-- чем «длина»: каждый адрес целиком, без пробелов и управляющих знаков (CR/LF в
-- заголовке — подмена заголовков), разделитель строго «, ». Веб приводит ввод к
-- этому виду сам (`parse_recipients`), база не верит вебу.
--
-- ОДНОСТРОЧНЫЕ ПОЛЯ без управляющих знаков: они показываются на экране и уходят в
-- текст предписания.
--
-- КТО ПИШЕТ И КТО ЧИТАЕТ. Пишет только администратор истории (роль, которой веб
-- делает действия УК); кто именно из УК вправе — решает веб (`contract.manage`),
-- база видит лишь подпись `updated_by`. Роль приложения читает, но только из
-- пространства УК: почты контактов — персональные данные, партнёр в вебе и бот
-- (пространство партнёра) эту таблицу не видят вовсе (политика ниже).
--
-- `country_recipients` (0037, «запомненные на отправке») остаётся: форма берёт
-- контакты по ДКК, а при их отсутствии — запомненных.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table country_contracts (
    id uuid primary key default gen_random_uuid(),
    country text not null check (country ~ '^[A-Z]{2}$'),
    legal_name text not null default ''
        check (length(legal_name) <= 200 and legal_name !~ '[[:cntrl:]]'),
    registration_country text not null default ''
        check (length(registration_country) <= 100 and registration_country !~ '[[:cntrl:]]'),
    company_number text not null default ''
        check (length(company_number) <= 60 and company_number !~ '[[:cntrl:]]'),
    address text not null default ''
        check (length(address) <= 300 and address !~ '[[:cntrl:]]'),
    -- Название и дата одной строкой, как написано в договоре.
    agreement text not null default ''
        check (length(agreement) <= 300 and agreement !~ '[[:cntrl:]]'),
    dkk_emails text not null default ''
        check (
            length(dkk_emails) <= 2000
            and (dkk_emails = ''
                 or dkk_emails ~ ('^[^@[:space:],;<>"''[:cntrl:]]+@[^@[:space:],;<>"''[:cntrl:]]+'
                                  || '\.[^@[:space:],;<>"''[:cntrl:]]+'
                                  || '(, [^@[:space:],;<>"''[:cntrl:]]+@[^@[:space:],;<>"''[:cntrl:]]+'
                                  || '\.[^@[:space:],;<>"''[:cntrl:]]+)*$')
            )
        ),
    updated_by text not null check (length(btrim(updated_by)) > 0),
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    -- Пустая строка договора никому не нужна.
    check (legal_name || registration_country || company_number || address || agreement
           || dkk_emails <> '')
);

create index country_contracts_country_idx on country_contracts (country, created_at, id);

comment on table country_contracts is
    'Договор страны для карточки: юрлицо партнёра, договор одной строкой, контакты по ДКК (D603). ДКК не моделируется. Почты — персональные данные: только пространство УК.';
comment on column country_contracts.dkk_emails is
    'Почты через «, » — их форма предписания подставляет в «Кому». Каждый адрес целиком, без управляющих знаков (уходит в заголовок письма).';

grant select on country_contracts to dodo_audit_app;
grant select, insert, delete on country_contracts to dodo_audit_admin;
grant update (legal_name, registration_country, company_number, address, agreement,
              dkk_emails, updated_by, updated_at)
    on country_contracts to dodo_audit_admin;

alter table country_contracts enable row level security;
alter table country_contracts force row level security;

-- Приложение: только из пространства УК (или служебного `*`).
create policy country_contracts_app_read on country_contracts
    for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));

-- Администратор истории: пространства у его соединения нет, как у соседних таблиц.
create policy country_contracts_admin on country_contracts
    for all to dodo_audit_admin
    using (true) with check (true);
