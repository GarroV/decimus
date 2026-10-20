-- 0084 — ключи внешних сервисов на экране «Подключения» (D576, #906).
--
-- Таблица `vault.secrets` (0070) с первого дня хранила один секрет — `model_key` — и
-- стерегла это `check`-ом по имени. Теперь главный админ ставит на экране и ключи других
-- сервисов (iSpring, Pointer), поэтому список имён расширяется до закрытого перечня из
-- `src/domain/service_keys.py` (VAULT_NAMES): имя по-прежнему не свободное, а чужое —
-- отказ базы, а не только кода. Список здесь и в реестре правятся вместе; их равенство
-- сверяет `tests/test_service_keys_registry.py`.
--
-- Права не меняются: читает роль приложения, пишет и удаляет роль администратора истории
-- (они выданы на таблицу целиком в 0070). Шифртекст, nonce и AAD — как раньше.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table vault.secrets drop constraint secrets_name_check;
alter table vault.secrets add constraint secrets_name_check check (
    name in ('model_key', 'pointer.api_key', 'ispring.client_id', 'ispring.client_secret')
);
