-- 0104_mailing_templates.sql
--
-- Шаблоны писем УК (D550, D608, #977, #1130): текст письма партнёру по проверке, который
-- правит админ УК, с историей версий. Слот — вид письма (`plan` — с планом действий,
-- `clean` — без D2 и D3, `empty` — без записей), язык — язык письма. Движок собирает письмо
-- по текущей версии слота; нет строки — по встроенному тексту (`engine/report.py`).
--
-- ВЕРСИИ. Строка не правится и не удаляется: каждая правка — новая строка с номером на
-- единицу больше, у неё свои автор и время. `body` NULL — «вернуть встроенный»: тоже версия,
-- чтобы история показывала, кто и когда вернул.
--
-- ТЕКСТ. База не разбирает подстановки (это делает код: `domain/letter_template.py`), она
-- держит длину и управляющие знаки.
--
-- КТО ПИШЕТ И КТО ЧИТАЕТ — как `mailing_cc` (0103): пишет администратор истории, кто из УК
-- вправе, решает веб (`mailing.manage`); приложение читает только из пространства УК.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table mailing_templates (
    kind text not null check (kind in ('inspection')),
    slot text not null check (slot in ('plan', 'clean', 'empty')),
    lang text not null check (lang in ('ru', 'en')),
    version integer not null check (version >= 1),
    body text check (
        body is null
        or (length(btrim(body)) > 0 and length(body) <= 6000
            and body !~ '[\x00-\x08\x0b\x0c\x0e-\x1f]')
    ),
    saved_by text not null check (length(btrim(saved_by)) > 0),
    saved_at timestamptz not null default now(),
    primary key (kind, slot, lang, version)
);

comment on table mailing_templates is
    'Шаблоны писем УК с версиями (D608). Текущая версия — наибольший номер; body NULL — встроенный текст движка.';

grant select on mailing_templates to dodo_audit_app;
grant select, insert on mailing_templates to dodo_audit_admin;

alter table mailing_templates enable row level security;
alter table mailing_templates force row level security;

create policy mailing_templates_app_read on mailing_templates
    for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));

create policy mailing_templates_admin on mailing_templates
    for all to dodo_audit_admin
    using (true) with check (true);
