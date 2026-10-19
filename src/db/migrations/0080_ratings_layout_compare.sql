-- 0080_ratings_layout_compare.sql
--
-- D551 (#972): блок «Сравнение девелоперов и стран» на «Рейтингах» — только УК.
-- Код блока закрыт проверкой `layout_block_check`, а `save_layout` строк не
-- добавляет, только правит: без строки здесь контролинг не смог бы ни спрятать,
-- ни сдвинуть новый блок — галочка молча не ложилась бы.
--
-- Встаёт сразу под средними РС и РКО (как в `src/ratings/layout.py: BLOCKS`):
-- блоки ниже сдвигаются на одно место, чужой порядок остаётся порядком.
-- Код `aggregators` остаётся в проверке: его строка из 0050 ещё лежит в базе.

alter table ratings.layout drop constraint layout_block_check;
alter table ratings.layout add constraint layout_block_check
    check (block in ('scores', 'compare', 'violations', 'top', 'hard', 'risk', 'maps', 'aggregators'));

update ratings.layout
   set position = position + 1
 where position > coalesce((select position from ratings.layout where block = 'scores'), -1);

insert into ratings.layout (block, position, updated_by)
values (
    'compare',
    coalesce((select position from ratings.layout where block = 'scores'), -1) + 1,
    'migration 0080'
);
