-- 0124_service_settings_home_attention.sql
--
-- Пиццерии в карточке «Требует внимания» на «Главной» (D728) включаются настройкой сети.
-- Ключ `home_attention_units` кладётся в ту же `service_settings` (`0109`), что и переключатель
-- экшн-планов; здесь только расширяется перечень допустимых ключей. Строки нет — выключено.
-- Права и политики таблицы не меняются: читает приложение, пишет админская роль.
alter table service_settings drop constraint service_settings_key_check;
alter table service_settings add constraint service_settings_key_check
    check (key in ('action_plans_enabled', 'home_attention_units'));
