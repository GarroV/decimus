-- 0083_ratings_layout_aggregators.sql
--
-- D585: агрегаторы на «Рейтингах» — своя плитка выше, а не часть блока карт.
-- Строка `aggregators` лежит в `ratings.layout` с 0050 (место 6, после того как
-- блок слили с картами — выпадала как незнакомая). Теперь код снова блок:
-- встаёт сразу под «Сравнением» (как в `src/ratings/layout.py: BLOCKS`), виден.
-- Блоки ниже сдвигаются на одно место: чужой порядок остаётся порядком.
--
-- Раннер оборачивает файл в одну транзакцию сам.

-- Сначала убрать строку из старого места, чтобы сдвиг её не задел.
delete from ratings.layout where block = 'aggregators';

update ratings.layout
   set position = position + 1
 where position > coalesce((select position from ratings.layout where block = 'compare'), -1);

insert into ratings.layout (block, position, updated_by)
values (
    'aggregators',
    coalesce((select position from ratings.layout where block = 'compare'), -1) + 1,
    'migration 0083'
);
