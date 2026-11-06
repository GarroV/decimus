-- 0121_api_sales_scope.sql
--
-- Право `sales:month` — метод `GET /api/v1/sales` (D723): продажи пиццерий за месяц из
-- Dodo IS, которые Децимус собирает раз в сутки в `dodois.unit_sales_month`. Главная Swarm
-- показывает по ним выручку каждой пиццерии страны.
--
-- Закрытый перечень прав в схеме (`0052`) расширяется одним значением. Токен Swarm получает
-- право сразу — как в `0052` получил оценки агрегаторов и статистику нарушений: ключ, который
-- уже стоит в Swarm, не перевыпускается, а новых секретов раскатка не требует. Остальным
-- токенам право включает владелец переключателем на «Подключениях».
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table api.tokens drop constraint tokens_scopes_check;

update api.tokens
set scopes = array_append(scopes, 'sales:month')
where consumer = 'swarm' and not ('sales:month' = any(scopes));

alter table api.tokens add constraint tokens_scopes_check
    check (cardinality(scopes) > 0 and scopes <@ array[
        'ratings:scores', 'ratings:checkups', 'ratings:violations', 'maps:ratings',
        'aggregators:ratings', 'inspections:list', 'inspections:detail',
        'inspections:violations', 'sales:month'
    ]);
