-- 0101_ratings_layout_clients.sql
--
-- D658: страница «Рейтинги» — три яруса блоков, в среднем новый блок `clients`
-- («Оценки клиентов», источник — Dodo IS, #1303). Код блока закрыт проверкой
-- `layout_block_check` (0080), а `save_layout` строк не создаёт — без строки
-- галочка нового блока не легла бы. Строка встаёт первой в среднем ярусе:
-- перед самым ранним из `maps`, `aggregators`, `risk`; блоки с этого места
-- сдвигаются на одно — чужой порядок остаётся порядком.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table ratings.layout drop constraint layout_block_check;
alter table ratings.layout add constraint layout_block_check
    check (block in ('scores', 'compare', 'violations', 'top', 'hard', 'risk', 'maps',
                     'aggregators', 'clients'));

update ratings.layout
   set position = position + 1
 where position >= coalesce(
     (select min(position) from ratings.layout where block in ('maps', 'aggregators', 'risk')),
     (select coalesce(max(position), -1) + 1 from ratings.layout));

insert into ratings.layout (block, position, updated_by)
values (
    'clients',
    coalesce(
        (select min(position) - 1 from ratings.layout where block in ('maps', 'aggregators', 'risk')),
        (select coalesce(max(position), -1) + 1 from ratings.layout)),
    'migration 0101'
);
