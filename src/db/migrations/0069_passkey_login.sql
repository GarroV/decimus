-- 0069 — ключ доступа как способ ВХОДА (D485).
--
-- Вход ключом идёт с формы входа, до того как известно, кто пришёл: вызов выдаётся
-- браузеру без учётки (ключ находится по номеру, а не по логину). Поэтому:
-- 1. `web_webauthn_challenges.user_id` может быть пустым, а назначение — `login`.
--    Привязка — отпечаток случайного токена в куке браузера (как у полупройденного входа).
-- 2. `login_journal.method` принимает `passkey`.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_webauthn_challenges alter column user_id drop not null;
alter table web_webauthn_challenges drop constraint web_webauthn_challenges_purpose_check;
alter table web_webauthn_challenges add constraint web_webauthn_challenges_purpose_check
    check (purpose in ('register', 'authenticate', 'login'));
alter table web_webauthn_challenges add constraint web_webauthn_challenges_user_check
    check ((purpose = 'login') = (user_id is null));

alter table login_journal drop constraint login_journal_method_check;
alter table login_journal add constraint login_journal_method_check
    check (method in ('password', 'google', 'oauth-claude', 'personal-mcp-token', 'bot-link',
                      'second-step', 'passkey'));
