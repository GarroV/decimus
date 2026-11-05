-- 0119_ratings_clusters_six.sql
--
-- Шесть кластеров стран вместо четырёх (просьба контролинга 05.11.2026, меняет D502):
-- CEE — Европа, TR — Турция, ASIA — Азия (Индонезия, Киргизия, Монголия,
-- Таджикистан), CAUCASUS — Кавказ, NG — Нигерия, MX — Мексика. OTHER остаётся
-- запасным: новая страна из загрузки справочника встаёт туда, пока её не перенесут;
-- пустой кластер на экранах не показывается.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table ratings.countries drop constraint countries_cluster_check;

alter table ratings.countries
    add constraint countries_cluster_check
    check (cluster in ('CEE', 'TR', 'ASIA', 'CAUCASUS', 'NG', 'MX', 'OTHER'));

update ratings.countries set cluster = 'ASIA' where code in ('ID', 'KG', 'MN', 'TJ');

update ratings.countries set cluster = 'NG' where code = 'NG';

update ratings.countries set cluster = 'MX' where code = 'MX';
