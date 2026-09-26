#!/usr/bin/env bash
# Дописывает в окружение площадки настройки своего хранилища файлов (D166,
# #318) — Linux-двойник tools/storage_env.ps1.
#
#   tools/storage_env.sh [путь к файлу окружения, по умолчанию .env]
#
# Секрет рождается здесь и наружу не печатается. Ключ, который уже есть,
# не трогается: повторный запуск ничего не меняет и существующий доступ к
# хранилищу не ломает.
set -euo pipefail

env_path="${1:-.env}"

if [ ! -f "$env_path" ]; then
    echo "Файла $env_path нет. Скрипт дописывает настройки в существующее окружение площадки, а не заводит его с нуля." >&2
    exit 1
fi

secret_name="S3_""SECRET_ACCESS_KEY"
names=(S3_BUCKET S3_ACCESS_KEY_ID "$secret_name" S3_ENDPOINT_URL S3_REGION)

value_for() {
    case "$1" in
        S3_BUCKET) echo "inspection-frames" ;;
        S3_ACCESS_KEY_ID) echo "decimus-storage" ;;
        S3_ENDPOINT_URL) echo "http://storage-live:9000" ;;
        S3_REGION) echo "us-east-1" ;;
        *) secret ;;
    esac
}

# Конечный кусок случайных байтов, а не `tr </dev/urandom | head`: под
# pipefail обрезка потока роняет tr по SIGPIPE, и set -e молча завершал
# скрипт, ничего не дописав.
secret() {
    local raw
    raw=$(head -c 1024 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')
    if [ "${#raw}" -lt 40 ]; then
        echo "не удалось получить случайный ключ" >&2
        exit 1
    fi
    echo "${raw:0:40}"
}

added=()
kept=()
lines=()
for name in "${names[@]}"; do
    if grep -q "^${name}=" "$env_path"; then
        kept+=("$name")
    else
        added+=("$name")
        lines+=("${name}=$(value_for "$name")")
    fi
done

if [ "${#added[@]}" -eq 0 ]; then
    echo "Всё уже настроено, ничего не менял. Ключей на месте: ${#kept[@]}"
    exit 0
fi

{
    echo ""
    echo "# --- своё хранилище файлов на площадке (D166, #318) ---"
    printf '%s\n' "${lines[@]}"
} >>"$env_path"

echo "Добавлено: ${added[*]}"
if [ "${#kept[@]}" -gt 0 ]; then
    echo "Оставлено как было: ${kept[*]}"
fi
