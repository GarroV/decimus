-- 0048_ratings_clusters.sql
--
-- Кластер страны IMF для сводки рейтингов (D383, D384): CEE — вся Европа,
-- остальные — OTHER (Other countries). Новая страна из загрузки справочника
-- встаёт в OTHER, пока её не перенесут.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table ratings.countries
    add column cluster text not null default 'OTHER' check (cluster in ('CEE', 'OTHER'));

update ratings.countries set cluster = 'CEE'
where code in ('RS', 'HR', 'SI', 'BG', 'ME', 'RO', 'PL', 'LT', 'EE', 'BY', 'CY', 'ES');
