-- 0052_api_methods.sql
--
-- Права сервисного токена — по методам API, а не двумя крупными кусками (D425).
-- Владелец выдаёт сервису ровно те методы, что включил переключателями на
-- «Подключениях»; `ratings:read` открывал разом баллы, собираемость, нарушения и
-- карты, `inspections:read` — и список, и подробности проверок.
--
-- Живые токены переводятся без перерыва: каждое старое право становится набором
-- методов, которые оно открывало. Swarm сверх того получает оценки агрегаторов и
-- статистику нарушений по проверкам — их владелец назвал в D426.
--
-- Тем же заходом у токена появляются: имя сервиса для людей («Рога и копыта»),
-- контакт ответственного, срок действия и страны, которые он видит (без них —
-- вся сеть; аудит 12.10.2026: утечка одного токена была утечкой всей сети).
-- Просроченный токен API не пускает так же, как отозванный
-- (`src/db/api_access.py: resolve`).
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table api.tokens drop constraint tokens_scopes_check;

update api.tokens set scopes = array(
    select distinct s from unnest(
        scopes
        || case when 'ratings:read' = any(scopes) then array[
               'ratings:scores', 'ratings:checkups', 'ratings:violations', 'maps:ratings'
           ] else array[]::text[] end
        || case when 'inspections:read' = any(scopes) then array[
               'inspections:list', 'inspections:detail'
           ] else array[]::text[] end
        || case when consumer = 'swarm' then array[
               'aggregators:ratings', 'inspections:violations'
           ] else array[]::text[] end
    ) as s
    where s not in ('ratings:read', 'inspections:read')
    order by s
);

alter table api.tokens add constraint tokens_scopes_check
    check (cardinality(scopes) > 0 and scopes <@ array[
        'ratings:scores', 'ratings:checkups', 'ratings:violations', 'maps:ratings',
        'aggregators:ratings', 'inspections:list', 'inspections:detail',
        'inspections:violations'
    ]);

alter table api.tokens
    add column title text check (title is null or btrim(title) <> ''),
    add column contact text check (contact is null or btrim(contact) <> ''),
    add column expires_at timestamptz,
    -- Страны, данные которых токен видит; пусто — вся сеть, как у Swarm (D387).
    add column countries text[] check (
        countries is null
        or (cardinality(countries) > 0
            and array_to_string(countries, ',') ~ '^[A-Z]{2}(,[A-Z]{2})*$')
    );

comment on column api.tokens.title is 'Имя сервиса для людей: «Swarm», «Рога и копыта».';
comment on column api.tokens.contact is 'Кто отвечает за подключение на той стороне.';
comment on column api.tokens.countries is
    'Страны, которые токен видит; пусто — вся сеть. Чужую страну запрос получает 403.';
comment on column api.tokens.expires_at is
    'Срок действия; после него токен не пускает, как отозванный. Пусто — бессрочно.';

-- Переключатели методов, имя и контакт правятся на месте, без нового ключа.
-- Право той же роли администратора истории, что выдаёт и отзывает.
grant update (scopes, title, contact, expires_at, countries) on api.tokens to dodo_audit_admin;
