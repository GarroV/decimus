-- 0072_ratings_clusters_four.sql
--
-- Четыре кластера стран вместо двух (D502): CEE — Европа, TR — Турция
-- (большой отдельный проект), CAUCASUS — Кавказ, OTHER — остальные страны.
-- Меняет D383/D384 (0048). Новая страна из загрузки справочника по-прежнему
-- встаёт в OTHER, пока её не перенесут.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table ratings.countries drop constraint countries_cluster_check;

alter table ratings.countries
    add constraint countries_cluster_check
    check (cluster in ('CEE', 'TR', 'CAUCASUS', 'OTHER'));

update ratings.countries set cluster = 'TR' where code = 'TR';

update ratings.countries set cluster = 'CAUCASUS' where code in ('AM', 'AZ', 'GE');
