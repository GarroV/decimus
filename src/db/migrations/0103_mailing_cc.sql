-- 0103_mailing_cc.sql
--
-- Списки копий раздела «Письма и уведомления» (D608, #1130, #977): почты сотрудников УК,
-- которые подставляются в «Копию» черновика письма. Список свой у каждого вида рассылки:
-- письма по проверкам, предписания, экшн-планы (D608).
--
-- ТОЛЬКО ХРАНЕНИЕ. Таблица ничего не отправляет: черновик кладёт в почту человека сам
-- человек, нажав кнопку (`google_mail.create_draft`), и уходит он его рукой.
--
-- Почта — персональные данные, как контакты по ДКК (0088): приложение читает только из
-- пространства УК (или служебного `*`), партнёр и бот пространства партнёра таблицу не
-- видят. Пишет администратор истории — роль, которой веб делает действия УК; кто из УК
-- вправе, решает веб (`mailing.manage`: админ и главный админ), база видит подпись
-- `added_by`. Адрес хранится в нижнем регистре, без повторов в пределах вида; формат такой
-- же строгий, как у `country_contracts.dkk_emails`: адрес уходит в заголовок `Cc:`, а CR/LF
-- или запятая внутри адреса — это подмена заголовков.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table mailing_cc (
    kind text not null check (kind in ('inspection', 'prescription', 'plan')),
    email text not null
        check (
            length(email) <= 200
            and email = lower(email)
            and email ~ ('^[^@[:space:],;<>"''[:cntrl:]]+@[^@[:space:],;<>"''[:cntrl:]]+'
                         || '\.[^@[:space:],;<>"''[:cntrl:]]+$')
        ),
    added_by text not null check (length(btrim(added_by)) > 0),
    added_at timestamptz not null default now(),
    primary key (kind, email)
);

comment on table mailing_cc is
    'Списки копий писем УК по видам рассылки (D608). Подставляются в «Копию» черновика; ничего не отправляют. Почты — персональные данные: только пространство УК.';

grant select on mailing_cc to dodo_audit_app;
grant select, insert, delete on mailing_cc to dodo_audit_admin;

alter table mailing_cc enable row level security;
alter table mailing_cc force row level security;

create policy mailing_cc_app_read on mailing_cc
    for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));

create policy mailing_cc_admin on mailing_cc
    for all to dodo_audit_admin
    using (true) with check (true);
