-- Входы в Dodo IS по странам (D640, #951): чем кончился вход по ссылке, если он не применён.
--
-- Новый вход заменяет рабочий вход страны только после проверки: учётка должна открывать хоть
-- одну пиццерию. Иначе прежняя пара ключей остаётся, ссылка гасится, а здесь записано, что
-- вход не применён и чья это была учётка — чтобы админ видел, почему «ничего не изменилось».

alter table dodois.invites
    add column result text check (result is null or result = 'not_applied'),
    add column result_account text,
    add check (result is null or used_at is not null);

comment on column dodois.invites.result is
    'NULL — вход применён (или ссылку ещё не использовали); not_applied — учётка не открыла ни '
    'одной пиццерии, прежний вход страны оставлен.';
comment on column dodois.invites.result_account is
    'Имя или почта учётки Dodo IS, чей вход не применён; только при result = not_applied.';
