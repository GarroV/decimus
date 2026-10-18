#!/usr/bin/env bash
# Вернуть открытое демо (D524) к исходному виду: база, кадры и состояние — заново.
#
# Зовётся cron'ом раз в час (deploy/demo/README.md) и из update.sh. Сносит
# ТОЛЬКО тома проекта decimus-demo: имя проекта задано здесь константой, а не
# приходит снаружи, чтобы этим скриптом нечем было снести прод.
set -euo pipefail
cd "$(dirname "$0")/../.."

project=decimus-demo
compose=(docker compose -p "$project" -f docker-compose.yml -f docker-compose.prod.yml
         -f deploy/demo/compose.demo.yaml)

exec 9>"/tmp/$project-reset.lock"
flock -n 9 || { echo "сброс демо уже идёт" >&2; exit 0; }

# Удалить, а не остановить: остановленный контейнер держит том, и `volume rm`
# отказывает («volume is in use») — сброс падал со второго запуска.
"${compose[@]}" rm -sf web walk db storage
for volume in pgdata state methodology; do
    docker volume rm -f "${project}_${volume}" >/dev/null
done
"${compose[@]}" up -d --wait db storage
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" run --rm --no-deps seed
"${compose[@]}" up -d --wait web walk
echo "демо пересобрано: $(date -u +%FT%TZ)"
